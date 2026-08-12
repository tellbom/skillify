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

export const CLAUDE_NATIVE_SETTING_SOURCES = ["user", "project", "local"] as const;

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

function normalizedAssistant(message: Record<string, unknown>): Record<string, unknown> {
  const body = message.message && typeof message.message === "object"
    ? message.message as Record<string, unknown>
    : {};
  const content = Array.isArray(body.content) ? body.content : [];
  const items = content.filter(
    (item): item is Record<string, unknown> => Boolean(item && typeof item === "object"),
  );
  const text = items
    .filter((item) => item.type === "text" && typeof item.text === "string")
    .map((item) => String(item.text))
    .join("\n")
    .slice(0, 8000);
  const tools = items
    .filter((item) => item.type === "tool_use" && typeof item.name === "string")
    .map((item) => String(item.name));
  return {
    text: text || undefined,
    tools,
    isError: message.error != null,
  };
}

function claudeResultFailed(message: Record<string, unknown>): boolean {
  return (
    message.subtype !== "success"
    || message.is_error === true
    || typeof message.api_error_status === "number"
    || message.terminal_reason === "api_error"
  );
}

function normalizedResult(message: Record<string, unknown>): Record<string, unknown> {
  return {
    isError: claudeResultFailed(message),
    subtype: message.subtype,
    terminalReason: message.terminal_reason,
    apiErrorStatus: message.api_error_status,
    summary: typeof message.result === "string"
      ? message.result.slice(0, 1000)
      : undefined,
  };
}

export function shouldEmitClaudeProviderEvent(
  message: Record<string, unknown>,
): boolean {
  return message.subtype !== "thinking_tokens";
}

function safeDecisionDetail(
  toolName: string,
  input: Record<string, unknown>,
  options: Record<string, unknown>,
): string | undefined {
  const provided = options.description ?? options.decisionReason;
  if (typeof provided === "string" && provided) return provided.slice(0, 1000);
  const raw = toolName === "Bash"
    ? input.command
    : (input.file_path ?? input.path ?? options.blockedPath);
  if (typeof raw !== "string" || !raw) return undefined;
  const value = raw
    .replace(/(sk-)[A-Za-z0-9_-]{8,}/gi, "$1[redacted]")
    .replace(/(Bearer\s+)[^\s"']+/gi, "$1[redacted]")
    .slice(0, 1000);
  return `${toolName === "Bash" ? "Command" : "Path"}: ${value}`;
}

type ClaudeQuestion = {
  key: string;
  header: string;
  question: string;
  options: Array<{ id: string; label: string; description?: unknown }>;
};

function claudeQuestions(input: Record<string, unknown>): ClaudeQuestion[] {
  return (Array.isArray(input.questions) ? input.questions : [])
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    .map((item, index) => {
      const question = String(item.question ?? item.header ?? index);
      const options = (Array.isArray(item.options) ? item.options : [])
        .filter((option): option is Record<string, unknown> => Boolean(option && typeof option === "object"))
        .map((option) => {
          const label = String(option.label ?? option.value ?? "");
          return { id: label, label, description: option.description };
        })
        .filter((option) => option.label);
      return {
        key: question,
        header: String(item.header ?? "Agent question").slice(0, 200),
        question: question.slice(0, 2000),
        options,
      };
    });
}

function claudeQuestionPresentation(input: Record<string, unknown>): {
  title: string;
  description: string;
  choices: ClaudeQuestion["options"];
} {
  const questions = claudeQuestions(input);
  if (questions.length === 1) {
    return {
      title: questions[0].header,
      description: questions[0].question,
      choices: questions[0].options,
    };
  }
  return {
    title: "Agent questions",
    description: questions.map((item, index) => {
      const options = item.options.map((option) => option.label).join(", ");
      return `${index + 1}. ${item.question}${options ? ` [${options}]` : ""}`;
    }).join("\n"),
    choices: [],
  };
}

export function answersForClaudeQuestions(
  input: Record<string, unknown>,
  response: { choice?: string; answer?: string },
): Record<string, string> {
  const questions = claudeQuestions(input);
  const raw = response.answer?.trim() || response.choice?.trim();
  if (!questions.length || !raw) throw new Error("Claude question response is empty");
  if (questions.length === 1) return { [questions[0].key]: raw };
  const lines = raw.split(/\r?\n/).map((item) => item.trim());
  if (lines.length !== questions.length || lines.some((item) => !item)) {
    throw new Error("Claude multi-question response requires one non-empty line per question");
  }
  return Object.fromEntries(questions.map((item, index) => [item.key, lines[index]]));
}

export class ClaudeAdapter implements ProviderAdapter {
  constructor(private readonly sink: EventSink) {}

  async start(command: StartSessionCommand): Promise<ProviderSessionHandle> {
    const abortController = new AbortController();
    const pending = new Map<string, PendingDecision>();
    const mcpServers = claudeMcp(command.mcpServers);
    let providerSessionId = command.resumeSessionId ?? "";
    let terminal = false;
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
        // Provider routing, credentials and model selection belong to Claude Code
        // (and tools such as CC Switch), not to Skillify.
        settingSources: [...CLAUDE_NATIVE_SETTING_SOURCES],
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
          const question = toolName === "AskUserQuestion"
            ? claudeQuestionPresentation(input)
            : null;
          this.sink.emit("interaction.requested", {
            providerRequestId: options.requestId,
            toolUseId: options.toolUseID,
            agentId: options.agentID,
            kind: toolName === "AskUserQuestion" ? "question" : "permission",
            title: question?.title ?? options.title ?? options.displayName ?? toolName,
            description: question?.description ?? safeDecisionDetail(
                toolName,
                input,
                options as unknown as Record<string, unknown>,
              ),
            toolName,
            choices: question
              ? question.choices
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
            this.sink.emit(
              "message.completed",
              normalizedAssistant(message as unknown as Record<string, unknown>),
              context(),
            );
          } else if (message.type === "result") {
            const result = message as unknown as Record<string, unknown>;
            if (terminal) continue;
            terminal = true;
            this.sink.emit(
              claudeResultFailed(result) ? "provider.failed" : "provider.completed",
              { result: normalizedResult(result) },
              context(),
            );
          } else if (shouldEmitClaudeProviderEvent(
            message as unknown as Record<string, unknown>,
          )) {
            this.sink.emit("provider.event", {
              kind: message.type,
              subtype: "subtype" in message ? message.subtype : undefined,
            }, context());
          }
        }
      } catch (error) {
        const normalized = error instanceof Error ? error : new Error(String(error));
        startedReject(normalized);
        if (!terminal) {
          terminal = true;
          this.sink.emit("provider.failed", {
            error: normalized.message.slice(0, 1000),
          }, context());
        }
      }
    })();
    await started;

    return {
      provider: "claude-code",
      taskId: command.taskId,
      workerId: command.workerId,
      providerSessionId,
      abort: async () => {
        if (!terminal) {
          terminal = true;
          this.sink.emit("provider.aborted", {}, context());
        }
        abortController.abort();
        try {
          await Promise.race([
            sdkQuery.interrupt(),
            new Promise<void>((resolve) => setTimeout(resolve, 2000)),
          ]);
        } catch {
          // The AbortController already terminated the local provider process.
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
          waiter.resolve({
            behavior: "allow",
            updatedInput: {
              ...waiter.input,
              answers: answersForClaudeQuestions(waiter.input, response),
            },
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
