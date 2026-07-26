#!/usr/bin/env node
import { createServer } from "node:http";

const port = Number(process.argv[2] ?? 18080);

function completion(prompt) {
  if (prompt.includes('"steps" array')) {
    return {
      steps: [{
        order: 1,
        title: "项目入口",
        description: "从 Python 入口开始理解这个多语言项目。",
        nodeIds: ["file:main.py"],
      }],
    };
  }
  if (prompt.includes("identify the logical architectural layers")) {
    return [{
      name: "核心层",
      description: "主要源代码",
      filePatterns: ["main.py", "src/"],
    }];
  }
  if (prompt.includes("describing the project")) {
    return {
      description: "用于验证 Python、Java 和 C# 的多语言项目。",
      frameworks: [],
      layers: [],
    };
  }
  return {
    fileSummary: "多语言 MVP 验证文件。",
    tags: ["mvp"],
    complexity: "simple",
    functionSummaries: { main: "程序入口。" },
    classSummaries: { App: "Java 应用类。", Program: "C# 程序类。" },
  };
}

const server = createServer(async (request, response) => {
  if (request.method !== "POST" || request.url !== "/v1/chat/completions") {
    response.statusCode = 404;
    response.end();
    return;
  }
  let raw = "";
  for await (const chunk of request) raw += String(chunk);
  const body = JSON.parse(raw);
  const prompt = body.messages?.at(-1)?.content ?? "";
  response.setHeader("content-type", "application/json");
  response.end(JSON.stringify({
    choices: [{ message: { content: JSON.stringify(completion(prompt)) } }],
  }));
});

server.listen(port, "0.0.0.0", () => {
  process.stdout.write(`mock-openai listening on ${port}\n`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
