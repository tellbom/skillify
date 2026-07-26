import { useCallback, useEffect, useRef, useState } from "react";
import { runtimeUrl } from "../portal-url";

type ProjectStatus = "queued" | "cloning" | "extracting" | "analyzing" | "ready" | "failed";
type SourceType = "folder" | "zip" | "git";

interface ProjectJob {
  id: string;
  name: string;
  sourceType: SourceType;
  sourceLabel: string;
  status: ProjectStatus;
  phase: string;
  progress: number;
  createdAt: string;
  updatedAt: string;
  error?: string;
  stats?: { files?: number; nodes?: number; edges?: number };
}

interface ProjectLauncherProps {
  accessToken: string;
}

const STATUS_LABELS: Record<ProjectStatus, string> = {
  queued: "等待分析",
  cloning: "正在获取源码",
  extracting: "正在展开源码",
  analyzing: "正在构建图谱",
  ready: "可以查看",
  failed: "分析失败",
};

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

const UPLOAD_BATCH_SIZE = 100;

function sourceRelativePath(file: File): string {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
}

function shouldUploadSourceFile(file: File): boolean {
  return !sourceRelativePath(file)
    .replaceAll("\\", "/")
    .split("/")
    .some((segment) => IGNORED_SOURCE_SEGMENTS.has(segment.toLowerCase()));
}

function projectUrl(projectId: string): string {
  const url = new URL(window.location.href);
  url.search = "";
  url.searchParams.set("project", projectId);
  return `${url.pathname}${url.search}`;
}

function displayTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
}

export default function ProjectLauncher({ accessToken }: ProjectLauncherProps) {
  const [sourceType, setSourceType] = useState<SourceType>("folder");
  const [projects, setProjects] = useState<ProjectJob[]>([]);
  const [folderFiles, setFolderFiles] = useState<File[]>([]);
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [projectName, setProjectName] = useState("");
  const [gitUrl, setGitUrl] = useState("");
  const [gitBranch, setGitBranch] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ sent: number; total: number } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const zipInput = useRef<HTMLInputElement>(null);

  const loadProjects = useCallback(async () => {
    try {
      const response = await fetch(runtimeUrl("/api/projects", accessToken), {
        cache: "no-store",
      });
      const payload = (await response.json()) as { projects?: ProjectJob[]; error?: string };
      if (!response.ok) throw new Error(payload.error ?? `HTTP ${response.status}`);
      setProjects(payload.projects ?? []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [accessToken]);

  useEffect(() => {
    void loadProjects();
    const timer = window.setInterval(() => void loadProjects(), 2000);
    return () => window.clearInterval(timer);
  }, [loadProjects]);

  const responsePayload = async <T,>(response: Response): Promise<T & { error?: string }> => {
    const text = await response.text();
    try {
      return JSON.parse(text) as T & { error?: string };
    } catch {
      throw new Error(`服务端返回了无法识别的响应（HTTP ${response.status}）`);
    }
  };

  const submitFolder = async (uploadableFolderFiles: File[]) => {
    const createResponse = await fetch(runtimeUrl("/api/uploads", accessToken), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sourceType: "folder", projectName: projectName.trim() }),
    });
    const session = await responsePayload<{ id: string }>(createResponse);
    if (!createResponse.ok) throw new Error(session.error ?? `HTTP ${createResponse.status}`);

    try {
      for (let start = 0; start < uploadableFolderFiles.length; start += UPLOAD_BATCH_SIZE) {
        const batch = uploadableFolderFiles.slice(start, start + UPLOAD_BATCH_SIZE);
        const form = new FormData();
        for (const file of batch) {
          form.append("files", file, sourceRelativePath(file));
        }
        const batchResponse = await fetch(
          runtimeUrl(`/api/uploads/${session.id}/files`, accessToken),
          {
            method: "POST",
            body: form,
          },
        );
        const batchResult = await responsePayload<{ receivedFiles?: number }>(batchResponse);
        if (!batchResponse.ok) {
          throw new Error(batchResult.error ?? `HTTP ${batchResponse.status}`);
        }
        setUploadProgress({
          sent: Math.min(start + batch.length, uploadableFolderFiles.length),
          total: uploadableFolderFiles.length,
        });
      }

      const completeResponse = await fetch(
        runtimeUrl(`/api/uploads/${session.id}/complete`, accessToken),
        { method: "POST" },
      );
      const job = await responsePayload<ProjectJob>(completeResponse);
      if (!completeResponse.ok) throw new Error(job.error ?? `HTTP ${completeResponse.status}`);
    } catch (reason) {
      await fetch(runtimeUrl(`/api/uploads/${session.id}`, accessToken), {
        method: "DELETE",
      }).catch(() => undefined);
      throw reason;
    }
  };

  const submitUpload = async () => {
    const uploadableFolderFiles = folderFiles.filter(shouldUploadSourceFile);
    const files = sourceType === "folder" ? uploadableFolderFiles : zipFile ? [zipFile] : [];
    if (files.length === 0) {
      setError(sourceType === "folder" ? "请选择一个源码文件夹。" : "请选择 ZIP 文件。");
      return;
    }
    if (sourceType === "folder") {
      await submitFolder(uploadableFolderFiles);
      return;
    }
    const form = new FormData();
    form.set("sourceType", sourceType);
    form.set("projectName", projectName.trim());
    if (zipFile) {
      form.append("files", zipFile, zipFile.name);
    }
    const response = await fetch(runtimeUrl("/api/projects/upload", accessToken), {
      method: "POST",
      body: form,
    });
    const payload = await responsePayload<ProjectJob>(response);
    if (!response.ok) throw new Error(payload.error ?? `HTTP ${response.status}`);
  };

  const submitGit = async () => {
    if (!gitUrl.trim()) {
      setError("请输入 Forgejo Git 地址。");
      return;
    }
    const response = await fetch(runtimeUrl("/api/projects/git", accessToken), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: gitUrl.trim(),
        branch: gitBranch.trim() || undefined,
        projectName: projectName.trim() || undefined,
      }),
    });
    const payload = (await response.json()) as ProjectJob & { error?: string };
    if (!response.ok) throw new Error(payload.error ?? `HTTP ${response.status}`);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setUploadProgress(null);
    setError(null);
    try {
      if (sourceType === "git") await submitGit();
      else await submitUpload();
      setFolderFiles([]);
      setZipFile(null);
      setProjectName("");
      setGitUrl("");
      setGitBranch("");
      if (folderInput.current) folderInput.current.value = "";
      if (zipInput.current) zipInput.current.value = "";
      await loadProjects();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(
        /load failed|failed to fetch|networkerror/i.test(message)
          ? "浏览器与分析服务的连接中断。请确认页面地址仍可访问，然后重试；已上传的临时分片会自动清理。"
          : message,
      );
    } finally {
      setSubmitting(false);
      setUploadProgress(null);
    }
  };

  const uploadableFolderCount = folderFiles.filter(shouldUploadSourceFile).length;
  const ignoredFolderCount = folderFiles.length - uploadableFolderCount;
  const selectedSummary =
    sourceType === "folder"
      ? folderFiles.length > 0
        ? `${uploadableFolderCount} 个源码文件${
            ignoredFolderCount > 0 ? ` · 已忽略 ${ignoredFolderCount} 个依赖/构建文件` : ""
          } · ${folderFiles[0]?.webkitRelativePath?.split("/")[0] ?? "源码文件夹"}`
        : "保留目录结构，不上传到外部服务"
      : sourceType === "zip"
        ? zipFile
          ? `${zipFile.name} · ${(zipFile.size / 1024 / 1024).toFixed(1)} MB`
          : "服务端安全展开，不执行项目脚本"
        : "支持内网 HTTP(S) 与 SSH Clone 地址";

  return (
    <div className="min-h-screen bg-root text-text-primary noise-overlay">
      <div className="min-h-screen grid grid-cols-1 xl:grid-cols-[minmax(520px,0.9fr)_minmax(560px,1.1fr)]">
        <section className="relative px-6 py-8 sm:px-10 lg:px-16 lg:py-14 border-b xl:border-b-0 xl:border-r border-border-subtle overflow-hidden">
          <div className="absolute inset-0 pointer-events-none opacity-50 portal-grid" />
          <div className="relative max-w-2xl mx-auto">
            <div className="flex items-center gap-3 mb-12">
              <span className="w-2 h-2 rounded-full bg-accent shadow-[0_0_16px_var(--glow-accent-pulse)]" />
              <span className="font-mono text-[10px] uppercase tracking-[0.32em] text-text-muted">
                Understand Anything · Source intake
              </span>
            </div>

            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-accent mb-4">
              从源码到可浏览架构
            </p>
            <h1 className="font-heading text-4xl sm:text-5xl lg:text-6xl leading-[1.04] tracking-tight max-w-xl">
              装载一个项目，
              <br />
              让结构开始显形。
            </h1>
            <p className="mt-6 text-sm sm:text-base leading-7 text-text-secondary max-w-xl">
              选择源码文件夹、ZIP，或内网 Forgejo 地址。分析在独立 Worker 中运行，
              完成后进入同一个知识图谱画布。
            </p>

            <form onSubmit={submit} className="mt-12">
              <div className="flex border-b border-border-medium" role="tablist" aria-label="源码来源">
                {([
                  ["folder", "文件夹"],
                  ["zip", "ZIP"],
                  ["git", "Forgejo"],
                ] as const).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    role="tab"
                    aria-selected={sourceType === value}
                    onClick={() => {
                      setSourceType(value);
                      setError(null);
                    }}
                    className={`relative px-5 py-3 text-xs font-semibold tracking-[0.12em] transition-colors ${
                      sourceType === value
                        ? "text-accent"
                        : "text-text-muted hover:text-text-secondary"
                    }`}
                  >
                    {label}
                    {sourceType === value && (
                      <span className="absolute left-0 right-0 -bottom-px h-px bg-accent" />
                    )}
                  </button>
                ))}
              </div>

              <div className="mt-6">
                {sourceType === "folder" && (
                  <>
                    <input
                      ref={folderInput}
                      type="file"
                      multiple
                      className="sr-only"
                      {...({ webkitdirectory: "", directory: "" } as React.InputHTMLAttributes<HTMLInputElement>)}
                      onChange={(event) => setFolderFiles(Array.from(event.target.files ?? []))}
                    />
                    <button
                      type="button"
                      onClick={() => folderInput.current?.click()}
                      className="portal-dropzone w-full min-h-44 px-7 py-8 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      <span className="portal-orbit" aria-hidden="true">
                        <i /><i /><i />
                      </span>
                      <span className="block font-heading text-xl mt-7">选择源码文件夹</span>
                      <span className="block text-xs text-text-muted mt-2">{selectedSummary}</span>
                    </button>
                  </>
                )}

                {sourceType === "zip" && (
                  <>
                    <input
                      ref={zipInput}
                      type="file"
                      accept=".zip,application/zip"
                      className="sr-only"
                      onChange={(event) => setZipFile(event.target.files?.[0] ?? null)}
                    />
                    <button
                      type="button"
                      onClick={() => zipInput.current?.click()}
                      className="portal-dropzone w-full min-h-44 px-7 py-8 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      <span className="portal-orbit" aria-hidden="true">
                        <i /><i /><i />
                      </span>
                      <span className="block font-heading text-xl mt-7">选择 ZIP 源码包</span>
                      <span className="block text-xs text-text-muted mt-2">{selectedSummary}</span>
                    </button>
                  </>
                )}

                {sourceType === "git" && (
                  <div className="space-y-4">
                    <label className="block">
                      <span className="block font-mono text-[10px] uppercase tracking-[0.18em] text-text-muted mb-2">
                        Forgejo Git 地址
                      </span>
                      <input
                        type="text"
                        value={gitUrl}
                        onChange={(event) => setGitUrl(event.target.value)}
                        placeholder="http://forgejo.internal/team/project.git"
                        className="portal-input"
                      />
                    </label>
                    <label className="block">
                      <span className="block font-mono text-[10px] uppercase tracking-[0.18em] text-text-muted mb-2">
                        分支或 Tag · 可选
                      </span>
                      <input
                        type="text"
                        value={gitBranch}
                        onChange={(event) => setGitBranch(event.target.value)}
                        placeholder="main"
                        className="portal-input"
                      />
                    </label>
                  </div>
                )}
              </div>

              <label className="block mt-5">
                <span className="block font-mono text-[10px] uppercase tracking-[0.18em] text-text-muted mb-2">
                  项目名称 · 可选
                </span>
                <input
                  type="text"
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  placeholder="默认从文件夹、ZIP 或仓库名称识别"
                  className="portal-input"
                />
              </label>

              {error && (
                <div className="mt-4 px-4 py-3 border border-red-500/30 bg-red-500/10 text-red-300 text-sm">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="mt-6 w-full sm:w-auto min-w-52 px-7 py-3.5 bg-accent text-root font-semibold text-sm tracking-wide hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition"
              >
                {submitting
                  ? uploadProgress
                    ? `正在上传 ${uploadProgress.sent}/${uploadProgress.total}`
                    : "正在接收源码…"
                  : "开始构建图谱"}
              </button>
            </form>
          </div>
        </section>

        <section className="px-6 py-8 sm:px-10 lg:px-14 lg:py-14 bg-surface/40">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-end justify-between gap-6 mb-8">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-text-muted">
                  Analysis queue
                </p>
                <h2 className="font-heading text-2xl mt-2">项目与分析进度</h2>
              </div>
              <span className="font-mono text-[11px] text-text-muted">
                {projects.length} 个项目
              </span>
            </div>

            {projects.length === 0 ? (
              <div className="border border-dashed border-border-medium min-h-64 flex items-center justify-center px-8 text-center">
                <div>
                  <div className="w-2 h-2 bg-node-file rounded-full mx-auto mb-5" />
                  <p className="font-heading text-lg">还没有图谱</p>
                  <p className="text-sm text-text-muted mt-2">
                    装载第一个源码项目后，分析轨迹会出现在这里。
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {projects.map((project) => {
                  const ready = project.status === "ready";
                  const failed = project.status === "failed";
                  return (
                    <article
                      key={project.id}
                      className="group border border-border-subtle bg-surface hover:border-border-medium transition-colors"
                    >
                      <div className="grid grid-cols-[10px_1fr_auto] gap-4 p-5 items-start">
                        <div className="pt-1.5">
                          <span
                            className={`block w-2 h-2 rounded-full ${
                              ready
                                ? "bg-node-function"
                                : failed
                                  ? "bg-red-400"
                                  : "bg-accent animate-accent-pulse"
                            }`}
                          />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-3">
                            <h3 className="font-heading text-lg truncate">{project.name}</h3>
                            <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted border border-border-subtle px-2 py-0.5">
                              {project.sourceType}
                            </span>
                          </div>
                          <p className="font-mono text-[10px] text-text-muted truncate mt-1">
                            {project.sourceLabel}
                          </p>
                          <div className="mt-4 h-px bg-elevated overflow-hidden">
                            <div
                              className={`h-full transition-all duration-700 ${
                                failed ? "bg-red-400" : ready ? "bg-node-function" : "bg-accent"
                              }`}
                              style={{ width: `${Math.max(2, Math.min(100, project.progress))}%` }}
                            />
                          </div>
                          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 font-mono text-[10px] text-text-muted">
                            <span>{STATUS_LABELS[project.status]}</span>
                            <span>{project.phase}</span>
                            <span>{displayTime(project.updatedAt)}</span>
                            {project.stats?.nodes !== undefined && (
                              <span>
                                {project.stats.nodes} 节点 · {project.stats.edges ?? 0} 关系
                              </span>
                            )}
                          </div>
                          {project.error && (
                            <p className="mt-3 text-xs text-red-300 leading-5">{project.error}</p>
                          )}
                        </div>
                        {ready && (
                          <a
                            href={projectUrl(project.id)}
                            className="self-center px-4 py-2 border border-accent/40 text-accent text-xs font-semibold hover:bg-accent hover:text-root transition-colors"
                          >
                            打开图谱
                          </a>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
