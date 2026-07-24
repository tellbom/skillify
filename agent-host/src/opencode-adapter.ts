import { createOpencode } from "@opencode-ai/sdk";
import type { Config, Event } from "@opencode-ai/sdk";
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
  if (value && typeof value === "object" && "data" in value) {
    return (value as { data: T }).data;
  }
  return value as T;
}

export class OpenCodeAdapter implements ProviderAdapter {
  constructor(private readonly sink: EventSink) {}

  async start(command: StartSessionCommand): Promise<ProviderSessionHandle> {
    const scopedTools = Object.fromEntries(
      command.mcpAllowedTools.map((name) => [name, true]),
    );
    const agentTools = { ...scopedTools };
    const controller = new AbortController();
    const runtime = await createOpencode({
      hostname: "127.0.0.1",
      port: 0,
      signal: controller.signal,
      config: {
        share: "disabled",
        mcp: opencodeMcp(command.mcpServers),
        tools: scopedTools,
        // OpenCode native subagents receive the same explicit MCP tool surface.
        agent: {
          general: { mode: "subagent", tools: agentTools },
          explore: { mode: "subagent", tools: agentTools },
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
    const providerSessionId = created.id;
    this.sink.seed(providerSessionId, command.initialSequence ?? 0);
    const context = {
      commandId: command.id,
      taskId: command.taskId,
      workerId: command.workerId,
      provider: "opencode" as const,
      providerSessionId,
    };
    const permissionSessions = new Map<string, string>();
    this.sink.emit("session.started", {
      mcpServers: Object.keys(command.mcpServers),
      mcpAllowedTools: command.mcpAllowedTools,
    }, context);

    const eventStream = await runtime.client.event.subscribe({
      query: { directory: command.workspace },
    });
    void (async () => {
      try {
        for await (const raw of eventStream.stream) {
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
              description: event.properties.type,
              choices: [
                { id: "once", label: "Allow once" },
                { id: "always", label: "Always allow in this session" },
                { id: "reject", label: "Reject" },
              ],
            }, context);
          } else if (event.type === "message.part.updated") {
            this.sink.emit("message.delta", {
              part: event.properties.part,
              delta: event.properties.delta,
              nativeSessionId: sessionId,
            }, context);
          } else if (
            event.type === "session.idle"
            && event.properties.sessionID === providerSessionId
          ) {
            this.sink.emit("provider.completed", {}, context);
          } else if (
            event.type === "session.error"
            && (!sessionId || sessionId === providerSessionId)
          ) {
            this.sink.emit("provider.failed", { error: event.properties }, context);
          }
        }
      } catch (error) {
        this.sink.emit("provider.failed", { error: String(error) }, context);
      }
    })();

    void runtime.client.session.promptAsync({
      path: { id: providerSessionId },
      query: { directory: command.workspace },
      body: {
        parts: [{ type: "text", text: command.prompt }],
        tools: scopedTools,
      },
    }).catch((error: unknown) => {
      this.sink.emit("provider.failed", { error: String(error) }, context);
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
