import { afterEach, describe, expect, it } from "vitest";
import { createServer, type Server } from "node:http";
import { OpenAICompatibleClient } from "./llm-client.js";

let server: Server | undefined;

afterEach(async () => {
  if (server) await new Promise<void>((resolve) => server!.close(() => resolve()));
  server = undefined;
});

describe("OpenAICompatibleClient", () => {
  it("calls an OpenAI-compatible chat completions endpoint", async () => {
    let authorization = "";
    server = createServer((request, response) => {
      authorization = String(request.headers.authorization);
      response.setHeader("content-type", "application/json");
      response.end(JSON.stringify({ choices: [{ message: { content: "{\"ok\":true}" } }] }));
    });
    await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("missing server address");
    const client = new OpenAICompatibleClient({
      baseUrl: `http://127.0.0.1:${address.port}/v1`,
      model: "internal-model",
      apiKey: "secret",
      timeoutMs: 1000,
      maxRetries: 0,
    });

    await expect(client.complete("prompt", "system")).resolves.toBe("{\"ok\":true}");
    expect(authorization).toBe("Bearer secret");
  });

  it("rejects malformed provider responses", async () => {
    server = createServer((_request, response) => response.end("not json"));
    await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("missing server address");
    const client = new OpenAICompatibleClient({
      baseUrl: `http://127.0.0.1:${address.port}/v1`,
      model: "internal-model",
      timeoutMs: 1000,
      maxRetries: 0,
    });

    await expect(client.complete("prompt", "system")).rejects.toThrow("non-JSON");
  });
});
