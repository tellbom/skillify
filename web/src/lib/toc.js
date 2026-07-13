// Pure Markdown heading/TOC helpers for the skill detail page's README/SKILL.md sticky sidebar
// table of contents. Operate on plain strings (raw Markdown source + rendered HTML), never the
// DOM, so they're unit-testable in plain Node without jsdom (see web/src/lib/versions.js for the
// pattern this follows).

/**
 * Slugify heading text into a URL-safe id (prototype's `_slug`): lowercase, non-alphanumeric runs
 * collapsed to a single "-", leading/trailing "-" trimmed.
 * @param {string} text
 */
export function slugify(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/[^a-z0-9一-龥]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/**
 * Scan raw Markdown source for ATX headings (`#`/`##`/`###`), skipping the contents of fenced
 * code blocks so a `#` inside a ```-fence is never mistaken for a heading. Duplicate slugs get a
 * "-2", "-3", ... suffix so ids stay unique within a document.
 * @param {string} markdownSource
 * @returns {Array<{level: number, text: string, id: string}>}
 */
export function extractHeadings(markdownSource) {
  const headings = []
  const seen = new Map()
  let inFence = false

  for (const rawLine of String(markdownSource || '').split('\n')) {
    const line = rawLine.trim()
    if (/^```/.test(line)) {
      inFence = !inFence
      continue
    }
    if (inFence) continue

    const match = /^(#{1,3})\s+(.*)$/.exec(line)
    if (!match) continue

    const level = match[1].length
    const text = match[2].trim().replace(/\s*#*$/, '')
    if (!text) continue

    const base = slugify(text) || `heading-${headings.length + 1}`
    const count = seen.get(base) || 0
    seen.set(base, count + 1)
    const id = count === 0 ? base : `${base}-${count + 1}`

    headings.push({ level, text, id })
  }

  return headings
}

/**
 * Inject `id` attributes into the first N `<h1>`/`<h2>`/`<h3>` opening tags of a rendered HTML
 * string, in document order, matching them 1:1 against `headings` (as produced by
 * `extractHeadings()` on the same source). Pure string replacement — no DOMParser/jsdom
 * dependency — so a heading beyond the given list, or a mismatched count, simply stops early
 * rather than throwing.
 * @param {string} html
 * @param {Array<{id: string}>} headings
 */
export function injectHeadingIds(html, headings) {
  if (!html || !headings?.length) return html || ''
  let index = 0
  return String(html).replace(/<h([1-3])(\s[^>]*)?>/g, (fullMatch, level, attrs = '') => {
    if (index >= headings.length) return fullMatch
    const { id } = headings[index]
    index += 1
    return `<h${level} id="${id}"${attrs || ''}>`
  })
}
