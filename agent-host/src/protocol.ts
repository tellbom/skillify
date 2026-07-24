export type ProviderName = "opencode" | "claude-code";

export interface McpServerSpec {
  type?: "local" | "remote";
  command?: string | string[];
  args?: string[];
  url?: string;
  environment?: Record<string, string>;
  env?: Record<string, string>;
  headers?: Record<string, string>;
  enabled?: boolean;
}

export interface StartSessionCommand {
  id: string;
  type: "session.start";
  provider: ProviderName;
  taskId: string;
  workerId: string;
  workspace: string;
  prompt: string;
  model?: string;
  mcpServers: Record<string, McpServerSpec>;
  mcpAllowedTools: string[];
  allowedTools?: string[];
  environment?: Record<string, string>;
  resumeSessionId?: string;
  initialSequence?: number;
}

export interface InteractionResponseCommand {
  id: string;
  type: "interaction.respond";
  providerSessionId: string;
  providerRequestId: string;
  responseVersion: number;
  choice?: string;
  answer?: string;
  comment?: string;
}

export interface SessionCommand {
  id: string;
  type: "session.abort" | "session.state" | "session.diff" | "session.close";
  providerSessionId: string;
}

export type HostCommand =
  | StartSessionCommand
  | InteractionResponseCommand
  | SessionCommand;

export interface HostEvent {
  type: string;
  commandId?: string;
  taskId?: string;
  workerId?: string;
  provider?: ProviderName;
  providerSessionId?: string;
  runtimeInstanceId?: string;
  sequence?: number;
  occurredAt: string;
  payload: Record<string, unknown>;
}

export interface ProviderSessionHandle {
  provider: ProviderName;
  taskId: string;
  workerId: string;
  providerSessionId: string;
  abort(): Promise<void>;
  state(): Promise<Record<string, unknown>>;
  diff(): Promise<Record<string, unknown>>;
  respond(
    providerRequestId: string,
    response: {
      responseVersion: number;
      choice?: string;
      answer?: string;
      comment?: string;
    },
  ): Promise<void>;
  close(): Promise<void>;
}

export interface ProviderAdapter {
  start(command: StartSessionCommand): Promise<ProviderSessionHandle>;
}
