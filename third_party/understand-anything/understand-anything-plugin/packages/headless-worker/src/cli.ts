#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { runWorker, type WorkerOptions } from "./worker.js";

interface ParsedArguments {
  command: "analyze";
  projectRoot: string;
  outputDir: string;
  projectName?: string;
  sourceCommit?: string;
  outputLanguage: string;
  exclude?: string;
}

function usage(): string {
  return `Usage:
  understand-anything-worker analyze --project <dir> --output <dir> [options]

Options:
  --language <code>   Output language (default: UA_OUTPUT_LANGUAGE or en)
  --exclude <globs>   Comma-separated .gitignore-style patterns
  --project-name <n>  Source project name supplied by the staging service
  --source-commit <h> Source commit supplied by the staging service

Required environment:
  UA_LLM_BASE_URL     OpenAI-compatible API base ending in /v1
  UA_LLM_MODEL        Model name

Optional environment:
  UA_LLM_API_KEY
  UA_LLM_API_KEY_FILE      preferred over UA_LLM_API_KEY
  UA_LLM_CONCURRENCY       default 3
  UA_LLM_TIMEOUT_SECONDS   default 120
  UA_LLM_MAX_RETRIES       default 2`;
}

export function parseArguments(argv: string[]): ParsedArguments {
  if (argv[0] !== "analyze") throw new Error(usage());
  let projectRoot = "";
  let outputDir = "";
  let outputLanguage = process.env.UA_OUTPUT_LANGUAGE || "en";
  let exclude: string | undefined;
  let projectName: string | undefined;
  let sourceCommit: string | undefined;
  for (let index = 1; index < argv.length; index++) {
    const argument = argv[index];
    const value = argv[index + 1];
    if (argument === "--project" && value) {
      projectRoot = value;
      index++;
    } else if (argument === "--output" && value) {
      outputDir = value;
      index++;
    } else if (argument === "--language" && value) {
      outputLanguage = value;
      index++;
    } else if (argument === "--exclude" && value) {
      exclude = value;
      index++;
    } else if (argument === "--project-name" && value) {
      projectName = value;
      index++;
    } else if (argument === "--source-commit" && value) {
      sourceCommit = value;
      index++;
    } else if (argument === "--help" || argument === "-h") {
      throw new Error(usage());
    } else {
      throw new Error(`Unknown or incomplete argument: ${argument}\n${usage()}`);
    }
  }
  if (!projectRoot || !outputDir) throw new Error(usage());
  return {
    command: "analyze",
    projectRoot: resolve(projectRoot),
    outputDir: resolve(outputDir),
    outputLanguage,
    exclude,
    projectName,
    sourceCommit,
  };
}

function integerEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 0) throw new Error(`${name} must be an integer`);
  return value;
}

function booleanEnv(name: string): boolean {
  return ["1", "true", "yes", "on"].includes((process.env[name] || "").toLowerCase());
}

async function apiKey(): Promise<string | undefined> {
  const keyFile = process.env.UA_LLM_API_KEY_FILE;
  if (keyFile) {
    const value = (await readFile(keyFile, "utf8")).trim();
    if (!value) throw new Error("UA_LLM_API_KEY_FILE is empty");
    return value;
  }
  return process.env.UA_LLM_API_KEY;
}

async function main(): Promise<void> {
  const parsed = parseArguments(process.argv.slice(2));
  const llmBaseUrl = process.env.UA_LLM_BASE_URL || "";
  const llmModel = process.env.UA_LLM_MODEL || "";
  if (!llmBaseUrl || !llmModel) {
    throw new Error("UA_LLM_BASE_URL and UA_LLM_MODEL are required");
  }
  const options: WorkerOptions = {
    projectRoot: parsed.projectRoot,
    outputDir: parsed.outputDir,
    projectName: parsed.projectName,
    sourceCommit: parsed.sourceCommit,
    llmBaseUrl,
    llmModel,
    llmApiKey: await apiKey(),
    outputLanguage: parsed.outputLanguage,
    concurrency: integerEnv("UA_LLM_CONCURRENCY", 3),
    requestTimeoutMs: integerEnv("UA_LLM_TIMEOUT_SECONDS", 120) * 1000,
    maxRetries: integerEnv("UA_LLM_MAX_RETRIES", 2),
    jsonMode: booleanEnv("UA_LLM_JSON_MODE"),
    thinkingMode:
      process.env.UA_LLM_THINKING === "enabled" ||
      process.env.UA_LLM_THINKING === "disabled"
        ? process.env.UA_LLM_THINKING
        : undefined,
    exclude: parsed.exclude,
  };
  const result = await runWorker(options);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

main().catch((error) => {
  process.stderr.write(`understand-anything-worker: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
