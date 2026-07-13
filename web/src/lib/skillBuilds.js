// Pure helpers for the Skill create/import/preview/publish flow (UploadView.vue +
// components/skillBuilds/**). Kept separate from components so field defaults and path
// validation are unit-testable without mounting Vue (see lib/mySkills.js for the pattern).
//
// Field names below are taken verbatim from spec/skill-manifest-v1.md §3 (manifest v1) and
// README.md's "Skill 创建、导入、预览与发布" section — no separate frontend field set.

export const RUNTIME_OPTIONS = ['claude-agent-skill', 'custom']

export const TARGET_OPTIONS = ['claude', 'opencode', 'codex', 'aider', 'project']

/** Blank manifest v1 draft for the guided-creation entry point. */
export function emptyManifestDraft() {
  return {
    namespace: '',
    name: '',
    version: '',
    description: '',
    author: '',
    license: '',
    runtime: '',
    targets: [],
    dependencies: { python: [], system: [], skills: [] },
    permissions: [],
    tags: [],
  }
}

/**
 * Reshape a (possibly partial) BuildPreview.manifest into a complete, form-editable draft —
 * missing fields fall back to the same blanks as emptyManifestDraft() so inputs never bind to
 * undefined. The save action always PATCHes the full draft back, so this round-trips cleanly.
 * @param {Record<string, any>} [manifest]
 */
export function manifestDraftFrom(manifest) {
  const base = emptyManifestDraft()
  const src = manifest || {}
  return {
    ...base,
    ...src,
    author: src.author ?? base.author,
    targets: Array.isArray(src.targets) ? [...src.targets] : base.targets,
    dependencies: {
      python: Array.isArray(src.dependencies?.python) ? [...src.dependencies.python] : [],
      system: Array.isArray(src.dependencies?.system) ? [...src.dependencies.system] : [],
      skills: Array.isArray(src.dependencies?.skills) ? [...src.dependencies.skills] : [],
    },
    permissions: Array.isArray(src.permissions) ? [...src.permissions] : base.permissions,
    tags: Array.isArray(src.tags) ? [...src.tags] : base.tags,
  }
}

/**
 * skill.yaml and SKILL.md are reserved build-tree paths — only the structured
 * create/PATCH endpoints may write them, never the ad-hoc file upload/delete endpoints.
 * @param {string} path
 */
export function isReservedBuildPath(path) {
  return path === 'skill.yaml' || path === 'SKILL.md'
}

/**
 * Client-side pre-check mirroring the backend's safe-relative-POSIX-path rule (README §五):
 * no absolute paths, no `..` segments, no backslashes, no drive letters. This is a UX
 * shortcut only — the backend remains the sole authority and still rejects unsafe paths (400).
 * @param {string} path
 */
export function isSafeRelativePath(path) {
  if (!path || typeof path !== 'string') return false
  if (path.startsWith('/')) return false
  if (path.includes('\\')) return false
  if (/^[A-Za-z]:/.test(path)) return false
  const segments = path.split('/')
  if (segments.some((segment) => segment === '..' || segment === '')) return false
  return true
}

/**
 * Trim + drop empties + dedupe, for the tags/permissions/dependency chip-list inputs shared by
 * ManifestForm.vue's five list fields.
 * @param {string[]} list
 */
export function dedupeList(list) {
  const seen = new Set()
  const out = []
  for (const raw of list || []) {
    const value = typeof raw === 'string' ? raw.trim() : raw
    if (!value || seen.has(value)) continue
    seen.add(value)
    out.push(value)
  }
  return out
}
