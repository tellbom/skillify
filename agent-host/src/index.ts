import { createInterface } from "node:readline";
import { ClaudeAdapter } from "./claude-adapter.js";
import { EventSink } from "./event-sink.js";
import { OpenCodeAdapter } from "./opencode-adapter.js";
import type {
  HostCommand,
  ProviderAdapter,
  ProviderSessionHandle,
} from "./protocol.js";

const sink = new EventSink();
const adapters: Record<string, ProviderAdapter> = {
  opencode: new OpenCodeAdapter(sink),
  "claude-code": new ClaudeAdapter(sink),
};
const sessions = new Map<string, ProviderSessionHandle>();

async function execute(command: HostCommand): Promise<void> {
  if (command.type === "session.start") {
    const adapter = adapters[command.provider];
    if (!adapter) throw new Error(`unsupported provider: ${command.provider}`);
    const handle = await adapter.start(command);
    if (sessions.has(handle.providerSessionId)) {
      await handle.close();
      throw new Error("provider session ID is already hosted");
    }
    sessions.set(handle.providerSessionId, handle);
    sink.emit("command.completed", {
      providerSessionId: handle.providerSessionId,
      runtimeInstanceId: sink.runtimeInstanceId,
    }, { commandId: command.id });
    return;
  }
  const handle = sessions.get(command.providerSessionId);
  if (!handle) throw new Error("provider session is not hosted by this process");
  if (command.type === "interaction.respond") {
    await handle.respond(command.providerRequestId, {
      responseVersion: command.responseVersion,
      choice: command.choice,
      answer: command.answer,
      comment: command.comment,
    });
    sink.emit("command.completed", {}, { commandId: command.id });
  } else if (command.type === "session.abort") {
    await handle.abort();
    sink.emit("command.completed", {}, { commandId: command.id });
  } else if (command.type === "session.state") {
    sink.emit("command.completed", await handle.state(), { commandId: command.id });
  } else if (command.type === "session.diff") {
    sink.emit("command.completed", await handle.diff(), { commandId: command.id });
  } else if (command.type === "session.close") {
    await handle.close();
    sessions.delete(command.providerSessionId);
    sink.emit("command.completed", {}, { commandId: command.id });
  }
}

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", (line) => {
  void (async () => {
    let commandId: string | undefined;
    try {
      const command = JSON.parse(line) as HostCommand;
      commandId = command.id;
      if (!command.id || !command.type) throw new Error("invalid host command");
      await execute(command);
    } catch (error) {
      sink.emit("command.failed", {
        error: error instanceof Error ? error.message : String(error),
      }, { commandId });
    }
  })();
});

async function shutdown(): Promise<void> {
  await Promise.allSettled([...sessions.values()].map((item) => item.close()));
  process.exit(0);
}
process.once("SIGINT", () => void shutdown());
process.once("SIGTERM", () => void shutdown());
