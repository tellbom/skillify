import MarkdownIt from 'markdown-it'
import { createHighlighter } from 'shiki'

const THEME = 'github-dark'
const LANGS = ['javascript', 'typescript', 'python', 'bash', 'yaml', 'json', 'markdown']

let highlighterPromise = null
function getHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({ themes: [THEME], langs: LANGS })
  }
  return highlighterPromise
}

export async function renderMarkdown(source) {
  if (!source) return ''
  const highlighter = await getHighlighter()
  const md = new MarkdownIt({
    html: false,
    linkify: true,
    highlight(code, lang) {
      try {
        return highlighter.codeToHtml(code, { lang: lang || 'text', theme: THEME })
      } catch {
        return `<pre><code>${md.utils.escapeHtml(code)}</code></pre>`
      }
    },
  })
  return md.render(source)
}
