import { randomUUID } from "node:crypto";
import type { HostEvent, ProviderName } from "./protocol.js";

export class EventSink {
  readonly runtimeInstanceId = `host-${randomUUID()}`;
  private readonly sequences = new Map<string, number>();

  seed(providerSessionId: string, sequence: number): void {
    if (sequence > 0) this.sequences.set(providerSessionId, sequence);
  }

  emit(
    type: string,
    payload: Record<string, unknown>,
    context: {
      commandId?: string;
      taskId?: string;
      workerId?: string;
      provider?: ProviderName;
      providerSessionId?: string;
    } = {},
  ): void {
    const sessionId = context.providerSessionId;
    const sequence = sessionId
      ? (this.sequences.get(sessionId) ?? 0) + 1
      : undefined;
    if (sessionId && sequence) this.sequences.set(sessionId, sequence);
    const event: HostEvent = {
      type,
      ...context,
      runtimeInstanceId: this.runtimeInstanceId,
      sequence,
      occurredAt: new Date().toISOString(),
      payload,
    };
    process.stdout.write(`${JSON.stringify(event)}\n`);
  }
}
