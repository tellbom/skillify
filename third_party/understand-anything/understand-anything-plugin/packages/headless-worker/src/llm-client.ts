export interface LlmClientOptions {
  baseUrl: string;
  model: string;
  apiKey?: string;
  timeoutMs: number;
  maxRetries: number;
  jsonMode?: boolean;
  thinkingMode?: "enabled" | "disabled";
}

interface ChatCompletionResponse {
  choices?: Array<{
    message?: {
      content?: string | Array<{ type?: string; text?: string }>;
    };
  }>;
  error?: { message?: string };
}

function completionUrl(baseUrl: string): string {
  const normalized = baseUrl.replace(/\/+$/, "");
  return normalized.endsWith("/chat/completions")
    ? normalized
    : `${normalized}/chat/completions`;
}

function responseText(payload: ChatCompletionResponse): string {
  const content = payload.choices?.[0]?.message?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter((part) => part.type === "text" && typeof part.text === "string")
      .map((part) => part.text)
      .join("");
  }
  throw new Error(payload.error?.message ?? "LLM response did not contain text");
}

function retryDelay(attempt: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, Math.min(250 * 2 ** attempt, 2000)));
}

export class OpenAICompatibleClient {
  private readonly options: LlmClientOptions;

  constructor(options: LlmClientOptions) {
    if (!options.baseUrl) throw new Error("LLM base URL is required");
    if (!options.model) throw new Error("LLM model is required");
    this.options = options;
  }

  async complete(prompt: string, systemPrompt: string): Promise<string> {
    let lastError: Error | undefined;
    for (let attempt = 0; attempt <= this.options.maxRetries; attempt++) {
      try {
        const headers: Record<string, string> = {
          "content-type": "application/json",
        };
        if (this.options.apiKey) {
          headers.authorization = `Bearer ${this.options.apiKey}`;
        }
        const requestBody: Record<string, unknown> = {
          model: this.options.model,
          temperature: 0.1,
          messages: [
            { role: "system", content: systemPrompt },
            { role: "user", content: prompt },
          ],
        };
        if (this.options.jsonMode) {
          requestBody.response_format = { type: "json_object" };
        }
        if (this.options.thinkingMode) {
          requestBody.thinking = { type: this.options.thinkingMode };
        }
        const response = await fetch(completionUrl(this.options.baseUrl), {
          method: "POST",
          headers,
          body: JSON.stringify(requestBody),
          signal: AbortSignal.timeout(this.options.timeoutMs),
        });
        const body = await response.text();
        let payload: ChatCompletionResponse;
        try {
          payload = JSON.parse(body) as ChatCompletionResponse;
        } catch {
          throw new Error(`LLM returned non-JSON HTTP ${response.status}`);
        }
        if (!response.ok) {
          throw new Error(payload.error?.message ?? `LLM returned HTTP ${response.status}`);
        }
        return responseText(payload);
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
        if (attempt < this.options.maxRetries) await retryDelay(attempt);
      }
    }
    throw lastError ?? new Error("LLM request failed");
  }
}
