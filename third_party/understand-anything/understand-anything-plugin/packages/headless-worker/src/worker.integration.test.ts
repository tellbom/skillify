import { afterEach, describe, expect, it } from "vitest";
import { createServer, type Server } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { runWorker } from "./worker.js";

let server: Server | undefined;
const temporaryDirectories: string[] = [];

afterEach(async () => {
  if (server) await new Promise<void>((resolve) => server!.close(() => resolve()));
  server = undefined;
  await Promise.all(temporaryDirectories.splice(0).map((dir) => rm(dir, { recursive: true })));
});

function mockResponse(prompt: string): unknown {
  if (prompt.includes('"steps" array')) {
    return {
      steps: [
        {
          order: 1,
          title: "Project entry",
          description: "Start with the Python entry point.",
          nodeIds: ["file:main.py"],
        },
      ],
    };
  }
  if (prompt.includes("identify the logical architectural layers")) {
    return [
      {
        name: "Core",
        description: "Main source files",
        filePatterns: ["main.py", "src/"],
      },
    ];
  }
  if (prompt.includes("describing the project")) {
    return {
      description: "A mixed-language fixture.",
      frameworks: [],
      layers: [],
    };
  }
  return {
    fileSummary: "Fixture source file.",
    tags: ["fixture"],
    complexity: "simple",
    functionSummaries: { main: "Program entry point." },
    classSummaries: { App: "Application class.", Program: "Program class." },
  };
}

describe("headless worker integration", () => {
  it("builds a viewer-compatible graph for Python, Java, and C#", async () => {
    const root = await mkdtemp(join(tmpdir(), "ua-headless-test-"));
    temporaryDirectories.push(root);
    const project = join(root, "project");
    const output = join(root, "output");
    await import("node:fs/promises").then(({ mkdir }) => mkdir(join(project, "src"), { recursive: true }));
    await Promise.all([
      writeFile(join(project, "main.py"), "def main():\n    return 1\n", "utf8"),
      writeFile(
        join(project, "src", "App.java"),
        "public class App { public static void main(String[] args) {} }\n",
        "utf8",
      ),
      writeFile(
        join(project, "src", "Program.cs"),
        "public class Program { public static void Main() {} }\n",
        "utf8",
      ),
    ]);

    server = createServer(async (request, response) => {
      let raw = "";
      for await (const chunk of request) raw += String(chunk);
      const body = JSON.parse(raw) as { messages: Array<{ content: string }> };
      const prompt = body.messages.at(-1)?.content ?? "";
      response.setHeader("content-type", "application/json");
      response.end(
        JSON.stringify({
          choices: [{ message: { content: JSON.stringify(mockResponse(prompt)) } }],
        }),
      );
    });
    await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("missing server address");

    const result = await runWorker({
      projectRoot: project,
      outputDir: output,
      llmBaseUrl: `http://127.0.0.1:${address.port}/v1`,
      llmModel: "mock-model",
      outputLanguage: "en",
      concurrency: 2,
      requestTimeoutMs: 5000,
      maxRetries: 0,
    });

    const graph = JSON.parse(await readFile(result.graphPath, "utf8")) as {
      project: { languages: string[] };
      nodes: Array<{ id: string }>;
      layers: unknown[];
      tour: unknown[];
    };
    expect(result.llmFailures).toBe(0);
    expect(graph.project.languages).toEqual(["csharp", "java", "python"]);
    expect(graph.nodes.some((node) => node.id.startsWith("function:main.py:main"))).toBe(true);
    expect(graph.nodes.some((node) => node.id.startsWith("class:src/App.java:App"))).toBe(true);
    expect(graph.nodes.some((node) => node.id.startsWith("class:src/Program.cs:Program"))).toBe(true);
    expect(graph.layers.length).toBeGreaterThan(0);
    expect(graph.tour.length).toBe(1);

    const status = JSON.parse(await readFile(join(output, "status.json"), "utf8")) as {
      state: string;
      phase: string;
    };
    expect(status).toMatchObject({ state: "ready", phase: "complete" });
  });
});
