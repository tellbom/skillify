import { createOpencode } from "@opencode-ai/sdk";
import type { Config, Event } from "@opencode-ai/sdk";
import { createOpencodeClient as createV2OpencodeClient } from "@opencode-ai/sdk/v2/client";
import type { EventSink } from "./event-sink.js";
import type {
  McpServerSpec,
  ProviderAdapter,
  ProviderSessionHandle,
  StartSessionCommand,
} from "./protocol.js";

function opencodeMcp(servers: Record<string, McpServerSpec>): Config["mcp"] {
  return Object.fromEntries(
    Object.entries(servers).map(([name, item]) => {
      if (item.url) {
        return [name, {
          type: "remote",
          url: item.url,
          headers: item.headers,
          enabled: item.enabled ?? true,
        }];
      }
      if (!item.command?.length) throw new Error(`MCP server ${name} has no command`);
      const command = Array.isArray(item.command)
        ? item.command
        : [item.command, ...(item.args ?? [])];
      return [name, {
        type: "local",
        command,
        environment: item.environment ?? item.env,
        enabled: item.enabled ?? true,
      }];
    }),
  ) as Config["mcp"];
}

function responseData<T>(value: unknown): T {
  if (value && typeof value === "object") {
    if ("error" in value && (value as { error?: unknown }).error) {
      const error = (value as { error: unknown }).error;
      throw new Error(`OpenCode API request failed: ${JSON.stringify(error).slice(0, 1000)}`);
    }
    if ("data" in value) {
      return (value as { data: T }).data;
    }
  }
  return value as T;
}

function normalizedError(value: unknown): Record<string, unknown> {
  const outer = value && typeof value === "object"
    ? value as Record<string, unknown>
    : {};
  const error = outer.error && typeof outer.error === "object"
    ? outer.error as Record<string, unknown>
    : outer;
  const data = error.data && typeof error.data === "object"
    ? error.data as Record<string, unknown>
    : error;
  return {
    name: typeof error.name === "string" ? error.name : "ProviderError",
    message: typeof data.message === "string"
      ? data.message.slice(0, 1000)
      : "OpenCode provider error",
    statusCode: typeof data.statusCode === "number" ? data.statusCode : undefined,
    retryable: typeof data.isRetryable === "boolean" ? data.isRetryable : undefined,
  };
}

function normalizedPart(
  part: unknown,
  delta: unknown,
  originalPrompt: string,
): Record<string, unknown> | null {
  if (!part || typeof part !== "object") return null;
  const item = part as Record<string, unknown>;
  const type = typeof item.type === "string" ? item.type : "unknown";
  const fullText = typeof item.text === "string" ? item.text : "";
  if (fullText === originalPrompt) return null;
  const text = typeof delta === "string" ? delta : fullText;
  if (type === "text" && text) {
    return { kind: "text", text: text.slice(0, 8000) };
  }
  const tool = typeof item.tool === "string"
    ? item.tool
    : (typeof item.name === "string" ? item.name : undefined);
  const state = item.state && typeof item.state === "object"
    ? item.state as Record<string, unknown>
    : {};
  if (tool || type === "tool") {
    return {
      kind: "tool",
      tool: tool ?? "unknown",
      status: typeof state.status === "string" ? state.status : undefined,
    };
  }
  return { kind: type };
}

type QuestionInfo = {
  question: string;
  header: string;
  options: Array<{ label: string; description?: string }>;
  multiple: boolean;
};

type PendingQuestion = {
  requestId: string;
  sessionId: string;
  questions: QuestionInfo[];
};

export function normalizeQuestionRequest(value: unknown): PendingQuestion | null {
  if (!value || typeof value !== "object") return null;
  const properties = value as Record<string, unknown>;
  const requestId = properties.requestID ?? properties.id;
  const sessionId = properties.sessionID;
  if (typeof requestId !== "string" || typeof sessionId !== "string") return null;
  const questions = (Array.isArray(properties.questions) ? properties.questions : [])
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    .map((item) => ({
      question: typeof item.question === "string" ? item.question.slice(0, 2000) : "Agent question",
      header: typeof item.header === "string" ? item.header.slice(0, 200) : "Agent question",
      options: (Array.isArray(item.options) ? item.options : [])
        .filter((option): option is Record<string, unknown> => Boolean(option && typeof option === "object"))
        .map((option) => ({
          label: String(option.label ?? "").slice(0, 200),
          description: typeof option.description === "string"
            ? option.description.slice(0, 500)
            : undefined,
        }))
        .filter((option) => option.label),
      multiple: item.multiple === true,
    }));
  return questions.length ? { requestId, sessionId, questions } : null;
}

function questionInteraction(question: PendingQuestion): Record<string, unknown> {
  const first = question.questions[0];
  if (question.questions.length === 1) {
    return {
      providerRequestId: question.requestId,
      nativeSessionId: question.sessionId,
      kind: "question",
      title: first.header,
      description: first.question,
      choices: first.options.map((option) => ({
        id: option.label,
        label: option.label,
        description: option.description,
      })),
      allowFreeText: true,
    };
  }
  const description = question.questions.map((item, index) => {
    const options = item.options.map((option) => option.label).join(", ");
    return `${index + 1}. ${item.question}${options ? ` [${options}]` : ""}`;
  }).join("\n");
  return {
    providerRequestId: question.requestId,
    nativeSessionId: question.sessionId,
    kind: "question",
    title: "Agent questions",
    description,
    choices: [],
    allowFreeText: true,
  };
}

export function answersForQuestionRequest(
  question: PendingQuestion,
  response: { choice?: string; answer?: string },
): string[][] {
  const raw = response.answer?.trim() || response.choice?.trim();
  if (!raw) throw new Error("OpenCode question response requires a choice or answer");
  if (question.questions.length === 1) {
    const answers = question.questions[0].multiple
      ? raw.split(",").map((item) => item.trim()).filter(Boolean)
      : [raw];
    return [answers];
  }
  const lines = raw.split(/\r?\n/).map((item) => item.trim());
  if (lines.length !== question.questions.length || lines.some((item) => !item)) {
    throw new Error("OpenCode multi-question response requires one non-empty line per question");
  }
  return lines.map((line, index) => (
    question.questions[index].multiple
      ? line.split(",").map((item) => item.trim()).filter(Boolean)
      : [line]
  ));
}

export class OpenCodeAdapter implements ProviderAdapter {
  constructor(private readonly sink: EventSink) {}

  async start(command: StartSessionCommand): Promise<ProviderSessionHandle> {
    const controller = new AbortController();
    const runtime = await createOpencode({
      hostname: "127.0.0.1",
      port: 0,
      signal: controller.signal,
      config: {
        share: "disabled",
        mcp: opencodeMcp(command.mcpServers),
        // Native subagents inherit this Worker's per-session MCP server set.
        agent: {
          general: { mode: "subagent" },
          explore: { mode: "subagent" },
        },
      },
    });
    const created = command.resumeSessionId
      ? responseData<{ id: string }>(await runtime.client.session.get({
          path: { id: command.resumeSessionId },
          query: { directory: command.workspace },
        }))
      : responseData<{ id: string }>(await runtime.client.session.create({
          body: { title: `Skillify ${command.taskId}/${command.workerId}` },
          query: { directory: command.workspace },
        }));
    const providerSessionId = created?.id;
    if (!providerSessionId) {
      runtime.server.close();
      controller.abort();
      throw new Error("OpenCode did not return a provider session ID");
    }
    this.sink.seed(providerSessionId, command.initialSequence ?? 0);
    const context = {
      commandId: command.id,
      taskId: command.taskId,
      workerId: command.workerId,
      provider: "opencode" as const,
      providerSessionId,
    };
    let terminal = false;
    const permissionSessions = new Map<string, string>();
    const questionRequests = new Map<string, PendingQuestion>();
    const questionClient = createV2OpencodeClient({
      baseUrl: runtime.server.url,
      directory: command.workspace,
    });
    this.sink.emit("session.started", {
      mcpServers: Object.keys(command.mcpServers),
      mcpAllowedTools: command.mcpAllowedTools,
      nativeSubagentMcpServers: Object.keys(command.mcpServers),
    }, context);

    const eventStream = await runtime.client.event.subscribe({
      query: { directory: command.workspace },
    });
    void (async () => {
      try {
        for await (const raw of eventStream.stream) {
          const untyped = raw as unknown as {
            type?: string;
            properties?: unknown;
            data?: unknown;
          };
          if (untyped.type === "question.asked" || untyped.type === "question.v2.asked") {
            const question = normalizeQuestionRequest(untyped.properties ?? untyped.data);
            if (question) {
              questionRequests.set(question.requestId, question);
              this.sink.emit("interaction.requested", questionInteraction(question), context);
            }
            continue;
          }
          const event = raw as Event;
          const properties = "properties" in event ? event.properties : {};
          const sessionId = properties && typeof properties === "object"
            ? ("sessionID" in properties
                ? String(properties.sessionID)
                : ("part" in properties
                    && properties.part
                    && typeof properties.part === "object"
                    && "sessionID" in properties.part
                    ? String(properties.part.sessionID)
                    : undefined))
            : undefined;
          if (event.type === "permission.updated") {
            permissionSessions.set(event.properties.id, event.properties.sessionID);
            this.sink.emit("interaction.requested", {
              providerRequestId: event.properties.id,
              nativeSessionId: event.properties.sessionID,
              kind: "permission",
              title: event.properties.title,
              description: Array.isArray(event.properties.pattern)
                ? event.properties.pattern.join(", ").slice(0, 1000)
                : String(event.properties.pattern ?? event.properties.type).slice(0, 1000),
              choices: [
                { id: "once", label: "Allow once" },
                { id: "always", label: "Always allow in this session" },
                { id: "reject", label: "Reject" },
              ],
            }, context);
          } else if (event.type === "message.part.updated") {
            const payload = normalizedPart(
              event.properties.part,
              event.properties.delta,
              command.prompt,
            );
            if (payload) {
              this.sink.emit("message.delta", {
                ...payload,
                nativeSessionId: sessionId,
              }, context);
            }
          } else if (
            event.type === "session.idle"
            && event.properties.sessionID === providerSessionId
            && !terminal
          ) {
            terminal = true;
            this.sink.emit("provider.completed", {}, context);
          } else if (
            event.type === "session.error"
            && (!sessionId || sessionId === providerSessionId)
            && !terminal
          ) {
            terminal = true;
            this.sink.emit("provider.failed", {
              error: normalizedError(event.properties),
            }, context);
          }
        }
      } catch (error) {
        if (!terminal) {
          terminal = true;
          this.sink.emit("provider.failed", { error: normalizedError(error) }, context);
        }
      }
    })();

    void runtime.client.session.promptAsync({
      path: { id: providerSessionId },
      query: { directory: command.workspace },
      body: {
        parts: [{ type: "text", text: command.prompt }],
      },
    }).catch((error: unknown) => {
      if (!terminal) {
        terminal = true;
        this.sink.emit("provider.failed", { error: normalizedError(error) }, context);
      }
    });

    return {
      provider: "opencode",
      taskId: command.taskId,
      workerId: command.workerId,
      providerSessionId,
      abort: async () => {
        await runtime.client.session.abort({
          path: { id: providerSessionId },
          query: { directory: command.workspace },
        });
        this.sink.emit("provider.aborted", {}, context);
      },
      state: async () => responseData<Record<string, unknown>>(
        await runtime.client.session.get({
          path: { id: providerSessionId },
          query: { directory: command.workspace },
        }),
      ),
      diff: async () => ({
        items: responseData<unknown[]>(await runtime.client.session.diff({
          path: { id: providerSessionId },
          query: { directory: command.workspace },
        })),
      }),
      respond: async (providerRequestId, response) => {
        const question = questionRequests.get(providerRequestId);
        if (question) {
          await questionClient.question.reply({
            requestID: providerRequestId,
            directory: command.workspace,
            answers: answersForQuestionRequest(question, response),
          });
          questionRequests.delete(providerRequestId);
          this.sink.emit("interaction.applied", {
            providerRequestId,
            responseVersion: response.responseVersion,
          }, context);
          return;
        }
        const choice = response.choice;
        if (choice !== "once" && choice !== "always" && choice !== "reject") {
          throw new Error("OpenCode permission response must be once, always or reject");
        }
        const targetSessionId = permissionSessions.get(providerRequestId) ?? providerSessionId;
        await runtime.client.postSessionIdPermissionsPermissionId({
          path: { id: targetSessionId, permissionID: providerRequestId },
          query: { directory: command.workspace },
          body: { response: choice },
        });
        permissionSessions.delete(providerRequestId);
        this.sink.emit("interaction.applied", {
          providerRequestId,
          responseVersion: response.responseVersion,
        }, context);
      },
      close: async () => {
        runtime.server.close();
        controller.abort();
      },
    };
  }
}
