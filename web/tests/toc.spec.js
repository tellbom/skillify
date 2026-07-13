import { describe, it, expect } from 'vitest'
import { slugify, extractHeadings, injectHeadingIds } from '../src/lib/toc.js'

describe('slugify', () => {
  it('lowercases and collapses non-alphanumeric runs to a single dash', () => {
    expect(slugify('Getting Started!')).toBe('getting-started')
    expect(slugify('  Leading/Trailing  ')).toBe('leading-trailing')
  })

  it('keeps CJK characters intact', () => {
    expect(slugify('安装说明')).toBe('安装说明')
  })
})

describe('extractHeadings', () => {
  it('extracts ATX headings with levels and deduped ids', () => {
    const md = '# Title\n\nSome text\n\n## Usage\n\n### Usage\n'
    expect(extractHeadings(md)).toEqual([
      { level: 1, text: 'Title', id: 'title' },
      { level: 2, text: 'Usage', id: 'usage' },
      { level: 3, text: 'Usage', id: 'usage-2' },
    ])
  })

  it('ignores headings inside fenced code blocks', () => {
    const md = '# Real Heading\n\n```\n# Not a heading\n```\n\n## Also Real\n'
    expect(extractHeadings(md)).toEqual([
      { level: 1, text: 'Real Heading', id: 'real-heading' },
      { level: 2, text: 'Also Real', id: 'also-real' },
    ])
  })

  it('ignores levels beyond h3 and non-heading lines', () => {
    const md = '#### Too Deep\nplain text\n# Kept\n'
    expect(extractHeadings(md)).toEqual([{ level: 1, text: 'Kept', id: 'kept' }])
  })

  it('handles empty/missing input', () => {
    expect(extractHeadings('')).toEqual([])
    expect(extractHeadings(undefined)).toEqual([])
  })
})

describe('injectHeadingIds', () => {
  it('injects ids into heading tags in document order', () => {
    const html = '<h1>Title</h1><p>text</p><h2>Usage</h2>'
    const headings = [
      { id: 'title' },
      { id: 'usage' },
    ]
    expect(injectHeadingIds(html, headings)).toBe('<h1 id="title">Title</h1><p>text</p><h2 id="usage">Usage</h2>')
  })

  it('preserves existing attributes on the heading tag', () => {
    const html = '<h2 class="x">Usage</h2>'
    expect(injectHeadingIds(html, [{ id: 'usage' }])).toBe('<h2 id="usage" class="x">Usage</h2>')
  })

  it('stops once the headings list is exhausted', () => {
    const html = '<h1>A</h1><h1>B</h1>'
    expect(injectHeadingIds(html, [{ id: 'a' }])).toBe('<h1 id="a">A</h1><h1>B</h1>')
  })

  it('returns the input unchanged when there are no headings', () => {
    expect(injectHeadingIds('<p>x</p>', [])).toBe('<p>x</p>')
    expect(injectHeadingIds('', [{ id: 'a' }])).toBe('')
  })
})
