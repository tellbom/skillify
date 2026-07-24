import {
  query,
  type McpServerConfig,
  type PermissionResult,
  type Query,
} from "@anthropic-ai/claude-agent-sdk";
import type { EventSink } from "./event-sink.js";
import type {
  McpServerSpec,
  ProviderAdapter,
  ProviderSessionHandle,
  StartSessionCommand,
} from "./protocol.js";

type PendingDecision = {
  resolve: (result: PermissionResult) => void;
  reject: (error: Error) => void;
  toolName: string;
  input: Record<string, unknown>;
};

function claudeMcp(servers: Record<string, McpServerSpec>): Record<string, McpServerConfig> {
  return Object.fromEntries(Object.entries(servers).map(([name, item]) => {
    if (item.url) {
      return [name, {
        type: "http",
        url: item.url,
        headers: item.headers,
      }];
    }
    if (!item.command?.length) throw new Error(`MCP server ${name} has no command`);
    const [command, ...embeddedArgs] = Array.isArray(item.command)
      ? item.command
      : [item.command];
    const args = [...embeddedArgs, ...(item.args ?? [])];
    return [name, {
      type: "stdio",
      command,
      args,
      env: item.environment ?? item.env,
    }];
  })) as Record<string, McpServerConfig>;
}

export class ClaudeAdapter implements ProviderAdapter {
  constructor(private readonly sink: EventSink) {}

  async start(command: StartSessionCommand): Promise<ProviderSessionHandle> {
    const abortController = new AbortController();
    const pending = new Map<string, PendingDecision>();
    const mcpServers = claudeMcp(command.mcpServers);
    let providerSessionId = command.resumeSessionId ?? "";
    let sdkQuery: Query;
    const context = () => ({
      commandId: command.id,
      taskId: command.taskId,
      workerId: command.workerId,
      provider: "claude-code" as const,
      providerSessionId,
    });
    sdkQuery = query({
      prompt: command.prompt,
      options: {
        abortController,
        cwd: command.workspace,
        model: command.model,
        resume: command.resumeSessionId,
        mcpServers,
        strictMcpConfig: true,
        tools: command.allowedTools ?? { type: "preset", preset: "claude_code" },
        allowedTools: command.mcpAllowedTools,
        agents: {
          "skillify-worker": {
            description: "Scoped child worker for this Skillify work package",
            prompt: "Complete only the delegated work package and report evidence.",
            // Explicit names make MCP availability deterministic in native subagents.
            mcpServers: Object.keys(mcpServers),
          },
        },
        canUseTool: async (toolName, input, options) => {
          providerSessionId ||= `pending-${command.taskId}-${command.workerId}`;
          const firstQuestion = Array.isArray(input.questions)
            ? input.questions[0] as Record<string, unknown> | undefined
            : undefined;
          const questionOptions = firstQuestion && Array.isArray(firstQuestion.options)
            ? firstQuestion.options
                .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
                .map((item) => ({
                  id: String(item.label ?? item.value ?? ""),
                  label: String(item.label ?? item.value ?? ""),
                  description: item.description,
                }))
            : [];
          this.sink.emit("interaction.requested", {
            providerRequestId: options.requestId,
            toolUseId: options.toolUseID,
            agentId: options.agentID,
            kind: toolName === "AskUserQuestion" ? "question" : "permission",
            title: options.title ?? options.displayName ?? toolName,
            description: options.description ?? options.decisionReason,
            input,
            choices: toolName === "AskUserQuestion" && questionOptions.length
              ? questionOptions
              : [
              { id: "allow", label: "Allow" },
              { id: "deny", label: "Deny" },
                ],
            allowFreeText: toolName === "AskUserQuestion",
          }, context());
          return new Promise<PermissionResult>((resolve, reject) => {
            pending.set(options.requestId, { resolve, reject, toolName, input });
            options.signal.addEventListener(
              "abort",
              () => {
                pending.delete(options.requestId);
                reject(new Error("permission request aborted"));
              },
              { once: true },
            );
          });
        },
      },
    });

    let startedResolve!: () => void;
    let startedReject!: (error: Error) => void;
    const started = new Promise<void>((resolve, reject) => {
      startedResolve = resolve;
      startedReject = reject;
    });
    void (async () => {
      try {
        for await (const message of sdkQuery) {
          if (message.session_id) providerSessionId = message.session_id;
          if (message.type === "system" && message.subtype === "init") {
            this.sink.seed(providerSessionId, command.initialSequence ?? 0);
            this.sink.emit("session.started", {
              mcpServers: message.mcp_servers,
              mcpAllowedTools: command.mcpAllowedTools,
              nativeSubagentMcpServers: Object.keys(mcpServers),
            }, context());
            startedResolve();
          } else if (message.type === "assistant") {
            this.sink.emit("message.completed", { message }, context());
          } else if (message.type === "result") {
            this.sink.emit(
              message.subtype === "success" ? "provider.completed" : "provider.failed",
              { result: message },
              context(),
            );
          } else {
            this.sink.emit("provider.event", { message }, context());
          }
        }
      } catch (error) {
        const normalized = error instanceof Error ? error : new Error(String(error));
        startedReject(normalized);
        this.sink.emit("provider.failed", { error: normalized.message }, context());
      }
    })();
    await started;

    return {
      provider: "claude-code",
      taskId: command.taskId,
      workerId: command.workerId,
      providerSessionId,
      abort: async () => {
        try {
          await sdkQuery.interrupt();
        } finally {
          abortController.abort();
          this.sink.emit("provider.aborted", {}, context());
        }
      },
      state: async () => ({
        providerSessionId,
        mcpServers: await sdkQuery.mcpServerStatus(),
        pendingInteractions: [...pending.keys()],
      }),
      diff: async () => ({ supported: false, reason: "use structured file events and gate diff" }),
      respond: async (providerRequestId, response) => {
        const waiter = pending.get(providerRequestId);
        if (!waiter) throw new Error("provider request is no longer pending");
        pending.delete(providerRequestId);
        if (response.choice === "deny") {
          waiter.resolve({ behavior: "deny", message: response.comment ?? "Denied by user" });
        } else if (waiter.toolName === "AskUserQuestion") {
          const answer = response.answer ?? response.choice ?? "";
          const questions = Array.isArray(waiter.input.questions)
            ? waiter.input.questions as Array<Record<string, unknown>>
            : [];
          const answers = Object.fromEntries(
            questions.map((question, index) => [
              String(question.question ?? question.header ?? index),
              answer,
            ]),
          );
          waiter.resolve({
            behavior: "allow",
            updatedInput: { ...waiter.input, answers },
          });
        } else {
          waiter.resolve({ behavior: "allow" });
        }
        this.sink.emit("interaction.applied", {
          providerRequestId,
          responseVersion: response.responseVersion,
        }, context());
      },
      close: async () => {
        abortController.abort();
        sdkQuery.close();
        for (const waiter of pending.values()) waiter.reject(new Error("session closed"));
        pending.clear();
      },
    };
  }
}
