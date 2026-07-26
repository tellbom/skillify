#!/usr/bin/env node

import { createServer } from "node:http";
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Busboy from "busboy";
import yauzl from "yauzl";

const PACKAGE_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const DIST_DIR = path.join(PACKAGE_ROOT, "dist");
const DATA_DIR = path.resolve(process.env.UA_PORTAL_DATA_DIR || "/data/projects");
const WORKER_CLI = process.env.UA_WORKER_CLI || "/opt/understand-worker/dist/cli.js";
const HOST = process.env.UA_PORTAL_HOST || "0.0.0.0";
const PORT = Number(process.env.UA_PORTAL_PORT || "5173");
const MAX_UPLOAD_BYTES = Number(process.env.UA_MAX_UPLOAD_BYTES || 10 * 1024 * 1024 * 1024);
const MAX_UNPACKED_BYTES = Number(process.env.UA_MAX_UNPACKED_BYTES || 20 * 1024 * 1024 * 1024);
const MAX_UPLOAD_FILES = Number(process.env.UA_MAX_UPLOAD_FILES || 100_000);
const ANALYSIS_CONCURRENCY = Math.max(1, Number(process.env.UA_ANALYSIS_CONCURRENCY || "1"));
const MAX_SOURCE_FILE_BYTES = 1024 * 1024;
const PROJECT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{7,63}$/;
const IGNORED_SOURCE_SEGMENTS = new Set([
  ".cache",
  ".git",
  ".gradle",
  ".idea",
  ".mypy_cache",
  ".nox",
  ".pytest_cache",
  ".runtime",
  ".ruff_cache",
  ".tox",
  ".ua",
  ".understand-anything",
  ".venv",
  ".vs",
  ".worktrees",
  "__pycache__",
  "bin",
  "build",
  "coverage",
  "dist",
  "node_modules",
  "obj",
  "target",
  "venv",
]);
const GRAPH_FILES = new Set([
  "knowledge-graph.json",
  "domain-graph.json",
  "diff-overlay.json",
  "meta.json",
  "config.json",
]);
const CONTENT_TYPES = {
  ".css": "text/css",
  ".html": "text/html",
  ".ico": "image/x-icon",
  ".js": "text/javascript",
  ".json": "application/json",
  ".map": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain",
  ".wasm": "application/wasm",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

function failStartup(message) {
  console.error(`[portal] ${message}`);
  process.exit(1);
}

if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) failStartup("invalid UA_PORTAL_PORT");
if (!fs.existsSync(DIST_DIR)) failStartup(`dashboard assets not found: ${DIST_DIR}`);
if (!fs.existsSync(WORKER_CLI)) failStartup(`worker CLI not found: ${WORKER_CLI}`);
fs.mkdirSync(DATA_DIR, { recursive: true });

function readAccessToken() {
  const tokenFile = process.env.UNDERSTAND_ACCESS_TOKEN_FILE;
  if (tokenFile) {
    const value = fs.readFileSync(tokenFile, "utf8").trim();
    if (!value) failStartup(`access token file is empty: ${tokenFile}`);
    return value;
  }
  return process.env.UNDERSTAND_ACCESS_TOKEN || crypto.randomBytes(16).toString("hex");
}

const ACCESS_TOKEN = readAccessToken();

function sendJson(response, statusCode, payload) {
  response.statusCode = statusCode;
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.setHeader("Cache-Control", "no-store");
  response.end(JSON.stringify(payload));
}

function authorized(url, request) {
  if (url.searchParams.get("token") === ACCESS_TOKEN) return true;
  const header = request.headers.authorization;
  return header === `Bearer ${ACCESS_TOKEN}`;
}

function projectDirectory(id) {
  if (!PROJECT_ID_PATTERN.test(id)) throw new Error("Invalid project id");
  return path.join(DATA_DIR, id);
}

function jobFile(id) {
  return path.join(projectDirectory(id), "job.json");
}

function readJob(id) {
  return JSON.parse(fs.readFileSync(jobFile(id), "utf8"));
}

function writeJsonAtomic(filePath, value) {
  const temporary = `${filePath}.${process.pid}.${crypto.randomBytes(4).toString("hex")}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, filePath);
}

function updateJob(id, patch) {
  const current = readJob(id);
  const next = { ...current, ...patch, updatedAt: new Date().toISOString() };
  writeJsonAtomic(jobFile(id), next);
  return next;
}

function newProjectId() {
  return `${Date.now().toString(36)}-${crypto.randomBytes(5).toString("hex")}`;
}

function safeName(value, fallback = "未命名项目") {
  const cleaned = String(value || "")
    .replace(/[\u0000-\u001f\u007f]/g, "")
    .replace(/[\\/]+/g, "-")
    .trim()
    .slice(0, 80);
  return cleaned || fallback;
}

function safeRelativePath(value) {
  if (typeof value !== "string" || !value || value.includes("\0") || path.isAbsolute(value)) {
    return null;
  }
  const portable = value.replaceAll("\\", "/").replace(/\/+$/, "");
  if (!portable) return null;
  const normalized = path.posix.normalize(portable).replace(/^\.\/+/, "");
  if (
    !normalized ||
    normalized === "." ||
    normalized === ".." ||
    normalized.startsWith("../") ||
    normalized.split("/").some((part) => !part || part === "." || part === "..")
  ) {
    return null;
  }
  return normalized;
}

function shouldIgnoreSourcePath(value) {
  return value
    .replaceAll("\\", "/")
    .split("/")
    .some((segment) => IGNORED_SOURCE_SEGMENTS.has(segment.toLowerCase()));
}

function redactGitUrl(value) {
  try {
    const parsed = new URL(value);
    parsed.username = "";
    parsed.password = "";
    return parsed.toString();
  } catch {
    return value.replace(/^(?:[^@/\s]+)@([^:\s]+):/, "$1:");
  }
}

function gitHost(value) {
  try {
    return new URL(value).hostname.toLowerCase();
  } catch {
    const match = value.match(/^(?:[^@/\s]+@)?([^:\s]+):/);
    return match?.[1]?.toLowerCase() ?? null;
  }
}

function validateGitUrl(value) {
  if (typeof value !== "string" || value.length > 2048 || value.includes("\0")) {
    throw new Error("Git 地址无效");
  }
  const host = gitHost(value);
  if (!host) throw new Error("只支持 HTTP(S) 或 SSH Forgejo Git 地址");
  try {
    const parsed = new URL(value);
    if (parsed.username || parsed.password) {
      throw new Error("Git 地址中不能包含账号或令牌，请使用服务端凭据配置");
    }
  } catch (error) {
    if (error instanceof Error && error.message.includes("账号或令牌")) throw error;
    // SCP-style SSH addresses are handled by gitHost().
  }
  const allowed = (process.env.UA_ALLOWED_GIT_HOSTS || "")
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);
  if (allowed.length > 0 && !allowed.includes(host)) {
    throw new Error(`Git 主机不在允许列表中: ${host}`);
  }
  return value;
}

function runProcess(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env ?? process.env,
      stdio: options.stdio ?? ["ignore", "pipe", "pipe"],
      shell: false,
    });
    let stdout = "";
    let stderr = "";
    if (child.stdout) child.stdout.on("data", (chunk) => (stdout += chunk.toString()));
    if (child.stderr) child.stderr.on("data", (chunk) => (stderr += chunk.toString()));
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        const tail = stderr.trim().split(/\r?\n/).slice(-8).join("\n");
        reject(new Error(tail || `${command} exited with ${code ?? signal}`));
      }
    });
  });
}

function walkFiles(root) {
  let count = 0;
  const stack = [root];
  while (stack.length > 0) {
    const directory = stack.pop();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const candidate = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) throw new Error("源码中不允许符号链接");
      if (entry.isDirectory()) stack.push(candidate);
      else if (entry.isFile()) count += 1;
    }
  }
  return count;
}

function openZip(filePath) {
  return new Promise((resolve, reject) => {
    yauzl.open(filePath, { lazyEntries: true, validateEntrySizes: true }, (error, archive) => {
      if (error) reject(error);
      else resolve(archive);
    });
  });
}

async function extractZip(archivePath, destination) {
  fs.mkdirSync(destination, { recursive: true });
  const archive = await openZip(archivePath);
  let totalBytes = 0;
  let totalFiles = 0;
  await new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      archive.close();
      if (error) reject(error);
      else resolve();
    };
    archive.once("error", finish);
    archive.once("end", () => finish());
    archive.on("entry", (entry) => {
      const relative = safeRelativePath(entry.fileName);
      if (!relative) return finish(new Error(`ZIP 包含不安全路径: ${entry.fileName}`));
      const mode = (entry.externalFileAttributes >>> 16) & 0xffff;
      if ((mode & 0o170000) === 0o120000) {
        return finish(new Error(`ZIP 包含符号链接: ${entry.fileName}`));
      }
      if (shouldIgnoreSourcePath(relative)) {
        archive.readEntry();
        return;
      }
      if (entry.fileName.endsWith("/")) {
        fs.mkdirSync(path.join(destination, relative), { recursive: true });
        archive.readEntry();
        return;
      }
      totalFiles += 1;
      totalBytes += entry.uncompressedSize;
      if (totalFiles > MAX_UPLOAD_FILES) return finish(new Error("ZIP 文件数量超过限制"));
      if (totalBytes > MAX_UNPACKED_BYTES) return finish(new Error("ZIP 展开后大小超过限制"));
      const output = path.join(destination, relative);
      fs.mkdirSync(path.dirname(output), { recursive: true });
      archive.openReadStream(entry, (error, input) => {
        if (error) return finish(error);
        const target = fs.createWriteStream(output, { flags: "wx", mode: 0o600 });
        input.once("error", finish);
        target.once("error", finish);
        target.once("close", () => archive.readEntry());
        input.pipe(target);
      });
    });
    archive.readEntry();
  });
  return totalFiles;
}

function readBodyJson(request, limit = 64 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(new Error("请求内容过大"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.once("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(new Error("JSON 请求无效"));
      }
    });
    request.once("error", reject);
  });
}

function uploadStagingDirectory(id) {
  return path.join(DATA_DIR, `.incoming-${id}`);
}

function uploadSessionFile(id) {
  return path.join(uploadStagingDirectory(id), "upload.json");
}

function createUploadSession(input) {
  if (input.sourceType !== "folder") throw new Error("分片上传只支持源码文件夹");
  const id = newProjectId();
  const staging = uploadStagingDirectory(id);
  fs.mkdirSync(path.join(staging, "incoming"), { recursive: true });
  writeJsonAtomic(uploadSessionFile(id), {
    id,
    sourceType: "folder",
    projectName: safeName(input.projectName, ""),
    receivedFiles: 0,
    receivedBytes: 0,
    firstRelative: "",
    createdAt: new Date().toISOString(),
  });
  return { id };
}

async function receiveUploadBatch(request, id) {
  const staging = uploadStagingDirectory(id);
  const sessionPath = uploadSessionFile(id);
  if (!PROJECT_ID_PATTERN.test(id) || !fs.existsSync(sessionPath)) {
    throw new Error("上传会话不存在或已经结束");
  }
  const session = JSON.parse(fs.readFileSync(sessionPath, "utf8"));
  const incoming = path.join(staging, "incoming");
  const writes = [];
  let batchFiles = 0;
  let batchBytes = 0;
  let firstRelative = "";
  let uploadError = null;

  const parser = Busboy({
    headers: request.headers,
    preservePath: true,
    limits: {
      fileSize: MAX_UPLOAD_BYTES,
      files: Math.min(MAX_UPLOAD_FILES, 1_000),
      fields: 4,
    },
  });
  const completed = new Promise((resolve) => {
    parser.on("file", (_name, input, info) => {
      let relative;
      try {
        relative = safeRelativePath(info.filename);
        if (!relative) uploadError ??= new Error(`上传路径无效: ${info.filename}`);
        if (!relative || uploadError || shouldIgnoreSourcePath(relative)) {
          input.resume();
          return;
        }
        const output = path.join(incoming, relative);
        fs.mkdirSync(path.dirname(output), { recursive: true });
        const write = new Promise((resolveWrite, rejectWrite) => {
          const target = fs.createWriteStream(output, { flags: "wx", mode: 0o600 });
          input.on("data", (chunk) => {
            batchBytes += chunk.length;
            if (session.receivedBytes + batchBytes > MAX_UPLOAD_BYTES && !uploadError) {
              uploadError = new Error("上传总大小超过限制");
              input.unpipe(target);
              target.destroy(uploadError);
              input.resume();
            }
          });
          input.once("limit", () => {
            uploadError ??= new Error(`文件超过上传限制: ${relative}`);
          });
          input.once("error", rejectWrite);
          target.once("error", (error) => {
            input.resume();
            rejectWrite(error);
          });
          target.once("close", resolveWrite);
          input.pipe(target);
        });
        writes.push(
          write.catch((error) => {
            uploadError ??= error instanceof Error ? error : new Error(String(error));
          }),
        );
        batchFiles += 1;
        firstRelative ||= relative;
      } catch (error) {
        uploadError ??= error instanceof Error ? error : new Error(String(error));
        input.resume();
      }
    });
    parser.once("filesLimit", () => {
      uploadError ??= new Error("单批上传文件数量超过限制");
    });
    parser.once("error", (error) => {
      uploadError ??= error;
    });
    parser.once("close", resolve);
  });
  request.pipe(parser);
  await completed;
  await Promise.all(writes);
  if (uploadError) throw uploadError;
  if (session.receivedFiles + batchFiles > MAX_UPLOAD_FILES) {
    throw new Error("上传文件数量超过限制");
  }
  const next = {
    ...session,
    receivedFiles: session.receivedFiles + batchFiles,
    receivedBytes: session.receivedBytes + batchBytes,
    firstRelative: session.firstRelative || firstRelative,
    updatedAt: new Date().toISOString(),
  };
  writeJsonAtomic(sessionPath, next);
  return { receivedFiles: next.receivedFiles, receivedBytes: next.receivedBytes };
}

function completeUploadSession(id) {
  const staging = uploadStagingDirectory(id);
  const sessionPath = uploadSessionFile(id);
  if (!PROJECT_ID_PATTERN.test(id) || !fs.existsSync(sessionPath)) {
    throw new Error("上传会话不存在或已经结束");
  }
  const session = JSON.parse(fs.readFileSync(sessionPath, "utf8"));
  if (session.receivedFiles < 1 || !session.firstRelative) throw new Error("没有收到源码文件");
  fs.rmSync(sessionPath, { force: true });
  const finalDirectory = projectDirectory(id);
  fs.renameSync(staging, finalDirectory);
  const now = new Date().toISOString();
  const fallbackName = session.firstRelative.split("/")[0];
  const job = {
    id,
    name: safeName(session.projectName, safeName(fallbackName)),
    sourceType: "folder",
    sourceLabel: `${session.receivedFiles} 个文件`,
    status: "queued",
    phase: "源码已接收",
    progress: 5,
    createdAt: now,
    updatedAt: now,
  };
  writeJsonAtomic(jobFile(id), job);
  enqueue(id);
  return job;
}

function discardUploadSession(id) {
  if (!PROJECT_ID_PATTERN.test(id)) throw new Error("上传会话无效");
  fs.rmSync(uploadStagingDirectory(id), { recursive: true, force: true });
}

async function receiveUpload(request) {
  const id = newProjectId();
  const staging = path.join(DATA_DIR, `.incoming-${id}`);
  const incoming = path.join(staging, "incoming");
  fs.mkdirSync(incoming, { recursive: true });
  const fields = {};
  const writes = [];
  const uploaded = [];
  let totalBytes = 0;
  let uploadError = null;

  try {
    const parser = Busboy({
      headers: request.headers,
      preservePath: true,
      limits: {
        fileSize: MAX_UPLOAD_BYTES,
        files: MAX_UPLOAD_FILES,
        fields: 16,
      },
    });
    const completed = new Promise((resolve, reject) => {
      parser.on("field", (name, value) => {
        fields[name] = value;
      });
      parser.on("file", (_name, input, info) => {
        let relative;
        try {
          relative = safeRelativePath(info.filename);
          if (!relative) {
            uploadError ??= new Error(`上传路径无效: ${info.filename}`);
          }
          if (!relative || uploadError) {
            input.resume();
            return;
          }
          if (shouldIgnoreSourcePath(relative)) {
            input.resume();
            return;
          }
          const output = path.join(incoming, relative);
          fs.mkdirSync(path.dirname(output), { recursive: true });
          const write = new Promise((resolveWrite, rejectWrite) => {
            const target = fs.createWriteStream(output, { flags: "wx", mode: 0o600 });
            input.on("data", (chunk) => {
              totalBytes += chunk.length;
              if (totalBytes > MAX_UPLOAD_BYTES && !uploadError) {
                uploadError = new Error("上传总大小超过限制");
                input.unpipe(target);
                target.destroy(uploadError);
                input.resume();
              }
            });
            input.once("limit", () => {
              uploadError ??= new Error(`文件超过上传限制: ${relative}`);
            });
            input.once("error", rejectWrite);
            target.once("error", (error) => {
              input.resume();
              rejectWrite(error);
            });
            target.once("close", resolveWrite);
            input.pipe(target);
          });
          writes.push(
            write.catch((error) => {
              uploadError ??= error instanceof Error ? error : new Error(String(error));
            }),
          );
          uploaded.push({ relative, output });
        } catch (error) {
          uploadError ??= error instanceof Error ? error : new Error(String(error));
          input.resume();
        }
      });
      parser.once("filesLimit", () => {
        uploadError ??= new Error("上传文件数量超过限制");
      });
      parser.once("error", (error) => {
        uploadError ??= error;
      });
      parser.once("close", resolve);
    });
    request.pipe(parser);
    await completed;
    await Promise.all(writes);
    if (uploadError) throw uploadError;
    if (uploaded.length === 0) throw new Error("没有收到源码文件");

    const sourceType = fields.sourceType === "zip" ? "zip" : "folder";
    if (sourceType === "zip" && uploaded.length !== 1) {
      throw new Error("ZIP 上传只能包含一个文件");
    }
    const firstSegment = uploaded[0].relative.split("/")[0];
    const fallbackName =
      sourceType === "zip"
        ? path.basename(uploaded[0].relative, path.extname(uploaded[0].relative))
        : firstSegment;
    const finalDirectory = projectDirectory(id);
    fs.renameSync(staging, finalDirectory);
    const now = new Date().toISOString();
    const job = {
      id,
      name: safeName(fields.projectName, safeName(fallbackName)),
      sourceType,
      sourceLabel: sourceType === "zip" ? uploaded[0].relative : `${uploaded.length} 个文件`,
      status: "queued",
      phase: "源码已接收",
      progress: 5,
      createdAt: now,
      updatedAt: now,
    };
    writeJsonAtomic(jobFile(id), job);
    enqueue(id);
    return job;
  } catch (error) {
    fs.rmSync(staging, { recursive: true, force: true });
    throw error;
  }
}

function createGitJob(input) {
  const url = validateGitUrl(input.url);
  const id = newProjectId();
  const directory = projectDirectory(id);
  fs.mkdirSync(directory, { recursive: true });
  const repositoryName = path.basename(redactGitUrl(url).replace(/\/$/, ""), ".git");
  const now = new Date().toISOString();
  const job = {
    id,
    name: safeName(input.projectName, safeName(repositoryName)),
    sourceType: "git",
    sourceLabel: redactGitUrl(url),
    gitUrl: url,
    gitBranch: typeof input.branch === "string" ? input.branch.trim().slice(0, 200) : "",
    status: "queued",
    phase: "等待获取源码",
    progress: 2,
    createdAt: now,
    updatedAt: now,
  };
  writeJsonAtomic(jobFile(id), job);
  enqueue(id);
  return { ...job, gitUrl: undefined };
}

const pending = [];
const queued = new Set();
let active = 0;

function enqueue(id) {
  if (queued.has(id)) return;
  queued.add(id);
  pending.push(id);
  queueMicrotask(drainQueue);
}

async function prepareSource(job) {
  const directory = projectDirectory(job.id);
  const source = path.join(directory, "source");
  if (job.sourceType === "folder") {
    fs.renameSync(path.join(directory, "incoming"), source);
    return walkFiles(source);
  }
  if (job.sourceType === "zip") {
    updateJob(job.id, { status: "extracting", phase: "安全展开 ZIP", progress: 10 });
    const incoming = path.join(directory, "incoming");
    const entries = fs.readdirSync(incoming);
    if (entries.length !== 1) throw new Error("ZIP 暂存区内容无效");
    const archive = path.join(incoming, entries[0]);
    const count = await extractZip(archive, source);
    fs.rmSync(incoming, { recursive: true, force: true });
    return count;
  }
  updateJob(job.id, { status: "cloning", phase: "从 Forgejo 获取源码", progress: 8 });
  const args = ["clone", "--depth", "1", "--single-branch"];
  if (job.gitBranch) args.push("--branch", job.gitBranch);
  args.push(job.gitUrl, source);
  const env = {
    ...process.env,
    GIT_TERMINAL_PROMPT: "0",
    ...(process.env.UA_GIT_TOKEN_FILE
      ? {
          GIT_ASKPASS: path.join(PACKAGE_ROOT, "bin", "git-askpass.mjs"),
          GIT_ASKPASS_REQUIRE: "force",
        }
      : {}),
    ...(process.env.UA_GIT_TLS_VERIFY === "0" ? { GIT_SSL_NO_VERIFY: "1" } : {}),
  };
  await runProcess("git", args, { env });
  return walkFiles(source);
}

async function analyzeProject(id, fileCount) {
  const directory = projectDirectory(id);
  const source = path.join(directory, "source");
  const graph = path.join(directory, "graph");
  fs.mkdirSync(graph, { recursive: true });
  const job = updateJob(id, {
    status: "analyzing",
    phase: "Worker 正在构建语义图谱",
    progress: 20,
    stats: { files: fileCount },
  });
  let commit = "";
  try {
    commit = (await runProcess("git", ["rev-parse", "HEAD"], { cwd: source })).stdout.trim();
  } catch {
    // Uploaded folders and ZIPs do not need to be Git repositories.
  }
  const args = [
    WORKER_CLI,
    "analyze",
    "--project",
    source,
    "--output",
    graph,
    "--project-name",
    job.name,
  ];
  if (commit) args.push("--source-commit", commit);
  const log = fs.openSync(path.join(directory, "worker.log"), "a", 0o600);
  try {
    await runProcess(process.execPath, args, { stdio: ["ignore", log, log] });
  } finally {
    fs.closeSync(log);
  }
  const knowledgeGraph = JSON.parse(
    fs.readFileSync(path.join(graph, "knowledge-graph.json"), "utf8"),
  );
  return {
    files: fileCount,
    nodes: Array.isArray(knowledgeGraph.nodes) ? knowledgeGraph.nodes.length : 0,
    edges: Array.isArray(knowledgeGraph.edges) ? knowledgeGraph.edges.length : 0,
  };
}

async function runJob(id) {
  try {
    const job = readJob(id);
    const source = path.join(projectDirectory(id), "source");
    const fileCount = fs.existsSync(source) ? walkFiles(source) : await prepareSource(job);
    const stats = await analyzeProject(id, fileCount);
    updateJob(id, {
      status: "ready",
      phase: "图谱已生成",
      progress: 100,
      stats,
      error: undefined,
      gitUrl: undefined,
    });
  } catch (error) {
    updateJob(id, {
      status: "failed",
      phase: "分析停止",
      error: error instanceof Error ? error.message.slice(0, 1200) : String(error),
    });
  }
}

function drainQueue() {
  while (active < ANALYSIS_CONCURRENCY && pending.length > 0) {
    const id = pending.shift();
    queued.delete(id);
    active += 1;
    void runJob(id).finally(() => {
      active -= 1;
      drainQueue();
    });
  }
}

function currentJobView(job) {
  const view = { ...job };
  delete view.gitUrl;
  if (job.status === "analyzing") {
    try {
      const status = JSON.parse(
        fs.readFileSync(path.join(projectDirectory(job.id), "graph", "status.json"), "utf8"),
      );
      if (typeof status.progress === "number") {
        view.progress = Math.min(
          99,
          Math.round(20 + Math.max(0, Math.min(100, status.progress)) * 0.8),
        );
      } else if (
        status.progress &&
        typeof status.progress.completed === "number" &&
        typeof status.progress.total === "number" &&
        status.progress.total > 0
      ) {
        const ratio = status.progress.completed / status.progress.total;
        view.progress = Math.min(
          99,
          Math.round(20 + Math.max(0, Math.min(1, ratio)) * 80),
        );
      }
      if (typeof status.phase === "string") view.phase = status.phase;
    } catch {
      // The worker creates status.json after its first phase starts.
    }
  }
  return view;
}

function listProjects() {
  const projects = [];
  for (const entry of fs.readdirSync(DATA_DIR, { withFileTypes: true })) {
    if (!entry.isDirectory() || !PROJECT_ID_PATTERN.test(entry.name)) continue;
    try {
      projects.push(currentJobView(readJob(entry.name)));
    } catch {
      // A partially copied directory is not exposed as a project.
    }
  }
  return projects.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

function recoverQueue() {
  for (const entry of fs.readdirSync(DATA_DIR, { withFileTypes: true })) {
    if (entry.isDirectory() && entry.name.startsWith(".incoming-")) {
      fs.rmSync(path.join(DATA_DIR, entry.name), { recursive: true, force: true });
    }
  }
  for (const project of listProjects()) {
    if (["queued", "cloning", "extracting", "analyzing"].includes(project.status)) {
      const source = path.join(projectDirectory(project.id), "source");
      if (project.status === "cloning" || project.status === "extracting") {
        fs.rmSync(source, { recursive: true, force: true });
      }
      if (fs.existsSync(source)) {
        updateJob(project.id, {
          status: "queued",
          phase: "服务重启后重新进入队列",
          progress: Math.min(project.progress, 20),
        });
      } else if (project.sourceType === "git") {
        updateJob(project.id, { status: "queued", phase: "等待重新获取源码", progress: 2 });
      }
      enqueue(project.id);
    }
  }
}

function projectContext(url) {
  const id = url.searchParams.get("project") || "";
  if (!PROJECT_ID_PATTERN.test(id)) return null;
  try {
    const job = readJob(id);
    const directory = projectDirectory(id);
    const graphDir = path.join(directory, "graph");
    const projectRoot = path.join(directory, "source");
    if (job.status !== "ready" || !fs.existsSync(path.join(graphDir, "knowledge-graph.json"))) {
      return null;
    }
    return { id, job, graphDir, projectRoot };
  } catch {
    return null;
  }
}

function normalizeGraphPath(filePath, projectRoot) {
  const rawPath = path.isAbsolute(filePath)
    ? filePath.startsWith(projectRoot)
      ? path.relative(projectRoot, filePath)
      : null
    : filePath;
  if (rawPath === null) return null;
  return safeRelativePath(rawPath);
}

function graphFilePathSet(context) {
  const allowed = new Set();
  try {
    const raw = JSON.parse(
      fs.readFileSync(path.join(context.graphDir, "knowledge-graph.json"), "utf8"),
    );
    for (const node of raw.nodes ?? []) {
      if (typeof node.filePath !== "string") continue;
      const normalized = normalizeGraphPath(node.filePath, context.projectRoot);
      if (normalized) allowed.add(normalized);
    }
  } catch {
    // Return an empty allowlist.
  }
  return allowed;
}

function detectLanguage(filePath) {
  const ext = path.extname(filePath).slice(1).toLowerCase();
  const byExt = {
    bash: "bash", c: "c", cc: "cpp", cpp: "cpp", cs: "csharp", css: "css",
    go: "go", h: "c", hpp: "cpp", html: "markup", java: "java",
    js: "javascript", jsx: "jsx", json: "json", md: "markdown",
    mjs: "javascript", py: "python", rb: "ruby", rs: "rust", sh: "bash",
    ts: "typescript", tsx: "tsx", txt: "text", yaml: "yaml", yml: "yaml",
  };
  return byExt[ext] ?? "text";
}

function readSourceFile(url, context) {
  const requested = safeRelativePath(url.searchParams.get("path") || "");
  if (!requested) return { statusCode: 400, payload: { error: "源码路径无效" } };
  if (!graphFilePathSet(context).has(requested)) {
    return { statusCode: 404, payload: { error: "文件不在当前知识图谱中" } };
  }
  const candidate = path.resolve(context.projectRoot, requested);
  const relative = path.relative(context.projectRoot, candidate);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    return { statusCode: 400, payload: { error: "源码路径越界" } };
  }
  try {
    const stat = fs.statSync(candidate);
    if (!stat.isFile()) throw new Error("not a file");
    if (stat.size > MAX_SOURCE_FILE_BYTES) {
      return { statusCode: 413, payload: { error: "文件过大，无法在线预览" } };
    }
    const buffer = fs.readFileSync(candidate);
    if (buffer.includes(0)) {
      return { statusCode: 415, payload: { error: "二进制文件无法在线预览" } };
    }
    const content = buffer.toString("utf8");
    return {
      statusCode: 200,
      payload: {
        path: requested,
        language: detectLanguage(requested),
        content,
        sizeBytes: buffer.byteLength,
        lineCount: content.length === 0 ? 0 : content.split(/\r\n|\n|\r/).length,
      },
    };
  } catch {
    return { statusCode: 404, payload: { error: "源码文件不存在" } };
  }
}

function serveGraph(response, fileName, context) {
  const candidate = path.join(context.graphDir, fileName);
  if (!fs.existsSync(candidate)) {
    response.statusCode = 404;
    response.end();
    return;
  }
  try {
    const raw = JSON.parse(fs.readFileSync(candidate, "utf8"));
    if (Array.isArray(raw.nodes)) {
      raw.nodes = raw.nodes.map((node) => {
        if (typeof node.filePath !== "string") return node;
        const filePath = normalizeGraphPath(node.filePath, context.projectRoot);
        return { ...node, filePath: filePath ?? path.basename(node.filePath) };
      });
    }
    sendJson(response, 200, raw);
  } catch {
    sendJson(response, 500, { error: "读取图谱文件失败" });
  }
}

function serveStatic(response, pathname) {
  const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  let absolute = path.resolve(DIST_DIR, relative);
  if (absolute !== DIST_DIR && !absolute.startsWith(`${DIST_DIR}${path.sep}`)) {
    response.statusCode = 403;
    response.end("Forbidden");
    return;
  }
  if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) {
    absolute = path.join(DIST_DIR, "index.html");
  }
  response.setHeader(
    "Content-Type",
    CONTENT_TYPES[path.extname(absolute).toLowerCase()] ?? "application/octet-stream",
  );
  response.setHeader(
    "Cache-Control",
    path.extname(absolute).toLowerCase() === ".html"
      ? "no-store"
      : "public, max-age=31536000, immutable",
  );
  response.end(fs.readFileSync(absolute));
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://127.0.0.1");
  const pathname = url.pathname;

  if (
    pathname === "/" &&
    !url.searchParams.has("portal") &&
    !url.searchParams.has("project")
  ) {
    url.searchParams.set("portal", "1");
    response.statusCode = 302;
    response.setHeader("Location", `/${url.search}`);
    response.end();
    return;
  }

  if (pathname === "/healthz") {
    sendJson(response, 200, {
      status: "ok",
      queue: { active, pending: pending.length },
    });
    return;
  }

  const isApi = pathname.startsWith("/api/");
  const isGraphRequest =
    pathname === "/file-content.json" ||
    pathname === "/staleness.json" ||
    GRAPH_FILES.has(pathname.slice(1));
  if (!isApi && !isGraphRequest) {
    serveStatic(response, pathname);
    return;
  }
  if (!authorized(url, request)) {
    sendJson(response, 403, { error: "访问令牌无效" });
    return;
  }

  if (pathname === "/api/projects" && request.method === "GET") {
    sendJson(response, 200, { projects: listProjects() });
    return;
  }
  if (pathname === "/api/uploads" && request.method === "POST") {
    void readBodyJson(request)
      .then((input) => createUploadSession(input))
      .then((session) => sendJson(response, 201, session))
      .catch((error) =>
        sendJson(response, 400, {
          error: error instanceof Error ? error.message : String(error),
        }),
      );
    return;
  }
  const uploadRoute = pathname.match(
    /^\/api\/uploads\/([a-z0-9][a-z0-9-]{7,63})(?:\/(files|complete))?$/,
  );
  if (uploadRoute && request.method === "POST" && uploadRoute[2] === "files") {
    void receiveUploadBatch(request, uploadRoute[1])
      .then((result) => sendJson(response, 200, result))
      .catch((error) => {
        console.error(`[portal] upload batch failed (${uploadRoute[1]}):`, error);
        sendJson(response, 400, {
          error: error instanceof Error ? error.message : String(error),
        });
      });
    return;
  }
  if (uploadRoute && request.method === "POST" && uploadRoute[2] === "complete") {
    try {
      sendJson(response, 202, completeUploadSession(uploadRoute[1]));
    } catch (error) {
      sendJson(response, 400, {
        error: error instanceof Error ? error.message : String(error),
      });
    }
    return;
  }
  if (uploadRoute && request.method === "DELETE" && !uploadRoute[2]) {
    try {
      discardUploadSession(uploadRoute[1]);
      sendJson(response, 200, { discarded: true });
    } catch (error) {
      sendJson(response, 400, {
        error: error instanceof Error ? error.message : String(error),
      });
    }
    return;
  }
  if (pathname === "/api/projects/upload" && request.method === "POST") {
    void receiveUpload(request)
      .then((job) => sendJson(response, 202, job))
      .catch((error) =>
        sendJson(response, 400, {
          error: error instanceof Error ? error.message : String(error),
        }),
      );
    return;
  }
  if (pathname === "/api/projects/git" && request.method === "POST") {
    void readBodyJson(request)
      .then((input) => createGitJob(input))
      .then((job) => sendJson(response, 202, job))
      .catch((error) =>
        sendJson(response, 400, {
          error: error instanceof Error ? error.message : String(error),
        }),
      );
    return;
  }

  const context = projectContext(url);
  if (!context) {
    sendJson(response, 404, { error: "项目不存在、尚未完成或图谱不可用" });
    return;
  }
  if (pathname === "/file-content.json") {
    const result = readSourceFile(url, context);
    sendJson(response, result.statusCode, result.payload);
    return;
  }
  if (pathname === "/staleness.json") {
    sendJson(response, 200, {
      graphs: {
        knowledge: {
          status: "unknown",
          reason: "git-head-unavailable",
        },
      },
    });
    return;
  }
  if (pathname === "/config.json") {
    const candidate = path.join(context.graphDir, "config.json");
    if (fs.existsSync(candidate)) serveGraph(response, "config.json", context);
    else sendJson(response, 200, { autoUpdate: false, outputLanguage: "zh" });
    return;
  }
  if (GRAPH_FILES.has(pathname.slice(1))) {
    serveGraph(response, pathname.slice(1), context);
    return;
  }
  sendJson(response, 404, { error: "接口不存在" });
});

recoverQueue();
server.listen(PORT, HOST, () => {
  const displayHost = HOST === "0.0.0.0" || HOST === "::" ? "127.0.0.1" : HOST;
  console.log(`[portal] listening on http://${displayHost}:${PORT}/?portal=1&token=${ACCESS_TOKEN}`);
  console.log(`[portal] data directory: ${DATA_DIR}`);
});

function shutdown() {
  server.close(() => process.exit(0));
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
