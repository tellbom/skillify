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
export function manifestDraftFrom(manifest, defaultAuthor = '') {
  const base = emptyManifestDraft()
  const src = manifest || {}
  const hasAuthor = typeof src.author === 'string'
    ? Boolean(src.author.trim())
    : Boolean(src.author && typeof src.author === 'object' && String(src.author.name || '').trim())
  return {
    ...base,
    ...src,
    author: hasAuthor
      ? (typeof src.author === 'object' ? { ...src.author } : src.author)
      : defaultAuthor,
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

const SKILL_MD_SECTION_ALIASES = new Map([
  ['overview', 'overview'],
  ['purpose', 'overview'],
  ['whentouse', 'overview'],
  ['技能用途', 'overview'],
  ['适用场景', 'overview'],
  ['技能用途与适用场景', 'overview'],
  ['inputs', 'inputs'],
  ['input', 'inputs'],
  ['inputrequirements', 'inputs'],
  ['输入', 'inputs'],
  ['输入要求', 'inputs'],
  ['steps', 'steps'],
  ['instructions', 'steps'],
  ['procedure', 'steps'],
  ['操作步骤', 'steps'],
  ['执行步骤', 'steps'],
  ['outputs', 'outputs'],
  ['output', 'outputs'],
  ['outputrequirements', 'outputs'],
  ['输出', 'outputs'],
  ['输出要求', 'outputs'],
  ['notes', 'notes'],
  ['precautions', 'notes'],
  ['cautions', 'notes'],
  ['注意事项', 'notes'],
  ['限制与注意事项', 'notes'],
  ['examples', 'examples'],
  ['example', 'examples'],
  ['usageexample', 'examples'],
  ['示例', 'examples'],
  ['使用示例', 'examples'],
])

/** Blank, form-editable representation of the human-facing SKILL.md body. */
export function emptySkillMdDraft() {
  return {
    title: '',
    overview: '',
    inputs: '',
    steps: '',
    outputs: '',
    notes: '',
    examples: '',
    extra: '',
    extraFrontmatter: '',
  }
}

function normalizeHeading(value) {
  return String(value || '').trim().toLowerCase().replace(/[\s_\-/：:（）()]+/g, '')
}

function splitFrontmatter(skillMd) {
  const normalized = String(skillMd || '').replace(/\r\n?/g, '\n')
  const match = normalized.match(/^---\n([\s\S]*?)\n---(?:\n|$)/)
  if (!match) return { frontmatter: '', body: normalized }
  return { frontmatter: match[1], body: normalized.slice(match[0].length) }
}

function withoutGeneratedFrontmatterFields(frontmatter) {
  const lines = String(frontmatter || '').split('\n')
  const kept = []
  for (let index = 0; index < lines.length;) {
    if (/^(name|description)\s*:/i.test(lines[index])) {
      index += 1
      while (index < lines.length && (/^\s+/.test(lines[index]) || lines[index] === '')) index += 1
      continue
    }
    kept.push(lines[index])
    index += 1
  }
  return kept.join('\n').trim()
}

function appendDraftContent(draft, key, content) {
  const value = content.trim()
  if (!value) return
  draft[key] = draft[key] ? `${draft[key]}\n\n${value}` : value
}

/**
 * Convert an existing native/imported SKILL.md into fields suitable for non-technical users.
 * Unknown Markdown and extra YAML keys are retained for a lossless round trip.
 */
export function parseSkillMd(skillMd, manifest = {}) {
  const draft = emptySkillMdDraft()
  const { frontmatter, body } = splitFrontmatter(skillMd)
  draft.extraFrontmatter = withoutGeneratedFrontmatterFields(frontmatter)
  draft.title = String(manifest.name || '')

  let currentKey = 'overview'
  let currentHeading = ''
  let lines = []
  const flush = () => {
    const content = lines.join('\n').trim()
    if (currentKey === 'extra') {
      appendDraftContent(draft, 'extra', [currentHeading, content].filter(Boolean).join('\n\n'))
    } else {
      appendDraftContent(draft, currentKey, content)
    }
    lines = []
  }

  for (const line of body.replace(/^\n+|\n+$/g, '').split('\n')) {
    const titleMatch = line.match(/^#\s+(.+)$/)
    if (titleMatch) {
      flush()
      draft.title = titleMatch[1].trim()
      currentKey = 'overview'
      currentHeading = ''
      continue
    }

    const sectionMatch = line.match(/^##\s+(.+)$/)
    if (sectionMatch) {
      flush()
      const key = SKILL_MD_SECTION_ALIASES.get(normalizeHeading(sectionMatch[1]))
      currentKey = key || 'extra'
      currentHeading = key ? '' : `## ${sectionMatch[1].trim()}`
      continue
    }
    lines.push(line)
  }
  flush()
  return draft
}

function yamlString(value) {
  return JSON.stringify(String(value || ''))
}

/** Generate the standards-compliant file sent to the existing Build PATCH API. */
export function composeSkillMd(fields, manifest = {}) {
  const draft = { ...emptySkillMdDraft(), ...(fields || {}) }
  const frontmatter = [
    '---',
    `name: ${yamlString(manifest.name)}`,
    `description: ${yamlString(manifest.description)}`,
    draft.extraFrontmatter.trim(),
    '---',
  ].filter(Boolean).join('\n')

  const body = []
  const title = String(draft.title || manifest.name || '').trim()
  if (title) body.push(`# ${title}`)
  if (draft.overview.trim()) body.push(draft.overview.trim())

  for (const [key, heading] of [
    ['inputs', '输入要求'],
    ['steps', '操作步骤'],
    ['outputs', '输出要求'],
    ['notes', '注意事项'],
    ['examples', '使用示例'],
  ]) {
    if (draft[key].trim()) body.push(`## ${heading}\n\n${draft[key].trim()}`)
  }
  if (draft.extra.trim()) body.push(draft.extra.trim())
  return `${frontmatter}\n\n${body.join('\n\n')}\n`
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
