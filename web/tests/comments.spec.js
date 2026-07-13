import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { buildCommentTree, canDeleteComment, avatarColorFor } from '../src/lib/comments.js'
import {
  getComments,
  postComment,
  deleteComment,
  starSkill,
  unstarSkill,
  subscribeSkill,
  unsubscribeSkill,
  getMySubscriptions,
} from '../src/lib/api.js'

describe('buildCommentTree', () => {
  it('groups top-level comments with their direct replies', () => {
    const comments = [
      { id: 1, parentId: null, author: 'alice', createdAt: '2026-01-01T00:00:00Z', body: 'first', deleted: false },
      { id: 2, parentId: 1, author: 'bob', createdAt: '2026-01-02T00:00:00Z', body: 'reply', deleted: false },
      { id: 3, parentId: null, author: 'carol', createdAt: '2026-01-03T00:00:00Z', body: 'second', deleted: false },
    ]
    const tree = buildCommentTree(comments)
    expect(tree.map((c) => c.id)).toEqual([1, 3])
    expect(tree[0].replies.map((r) => r.id)).toEqual([2])
    expect(tree[1].replies).toEqual([])
  })

  it('flattens arbitrarily deep reply chains into their top-level ancestor (backend allows unlimited nesting)', () => {
    const comments = [
      { id: 1, parentId: null, author: 'alice', createdAt: '2026-01-01T00:00:00Z', body: 'root', deleted: false },
      { id: 2, parentId: 1, author: 'bob', createdAt: '2026-01-02T00:00:00Z', body: 'reply-1', deleted: false },
      { id: 3, parentId: 2, author: 'carol', createdAt: '2026-01-03T00:00:00Z', body: 'reply-2', deleted: false },
      { id: 4, parentId: 3, author: 'dave', createdAt: '2026-01-04T00:00:00Z', body: 'reply-3', deleted: false },
    ]
    const tree = buildCommentTree(comments)
    expect(tree.length).toBe(1)
    expect(tree[0].id).toBe(1)
    expect(tree[0].replies.map((r) => r.id)).toEqual([2, 3, 4])
  })

  it('sorts replies oldest-first regardless of input order', () => {
    const comments = [
      { id: 1, parentId: null, author: 'alice', createdAt: '2026-01-01T00:00:00Z', body: 'root', deleted: false },
      { id: 2, parentId: 1, author: 'bob', createdAt: '2026-01-05T00:00:00Z', body: 'later', deleted: false },
      { id: 3, parentId: 1, author: 'carol', createdAt: '2026-01-02T00:00:00Z', body: 'earlier', deleted: false },
    ]
    const tree = buildCommentTree(comments)
    expect(tree[0].replies.map((r) => r.id)).toEqual([3, 2])
  })

  it('treats a comment with a dangling/unknown parentId as its own root rather than dropping it', () => {
    const comments = [
      { id: 1, parentId: 999, author: 'alice', createdAt: '2026-01-01T00:00:00Z', body: 'orphan', deleted: false },
    ]
    const tree = buildCommentTree(comments)
    expect(tree.map((c) => c.id)).toEqual([1])
  })

  it('handles an empty/missing list', () => {
    expect(buildCommentTree([])).toEqual([])
    expect(buildCommentTree(undefined)).toEqual([])
  })

  it('preserves the deleted flag and placeholder body on tree nodes', () => {
    const comments = [
      { id: 1, parentId: null, author: 'alice', createdAt: '2026-01-01T00:00:00Z', body: '[已删除]', deleted: true },
    ]
    const tree = buildCommentTree(comments)
    expect(tree[0].deleted).toBe(true)
    expect(tree[0].body).toBe('[已删除]')
  })
})

describe('canDeleteComment', () => {
  it('is true when the comment author matches the current username', () => {
    expect(canDeleteComment({ author: 'alice', deleted: false }, 'alice')).toBe(true)
  })

  it('is false when the author does not match', () => {
    expect(canDeleteComment({ author: 'alice', deleted: false }, 'bob')).toBe(false)
  })

  it('is false when there is no logged-in user', () => {
    expect(canDeleteComment({ author: 'alice', deleted: false }, null)).toBe(false)
  })

  it('is false for already-deleted comments even if authored by the current user', () => {
    expect(canDeleteComment({ author: 'alice', deleted: true }, 'alice')).toBe(false)
  })
})

describe('avatarColorFor', () => {
  it('is deterministic for the same username', () => {
    expect(avatarColorFor('alice')).toBe(avatarColorFor('alice'))
  })

  it('returns a color even for an empty/missing name', () => {
    expect(typeof avatarColorFor('')).toBe('string')
    expect(typeof avatarColorFor(undefined)).toBe('string')
  })

  it('tends to differ across different usernames', () => {
    const colors = new Set(['alice', 'bob', 'carol', 'dave', 'erin'].map(avatarColorFor))
    expect(colors.size).toBeGreaterThan(1)
  })
})

describe('api.js community query assembly', () => {
  let fetchMock

  beforeEach(() => {
    setActivePinia(createPinia())
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    })
    vi.stubGlobal('fetch', fetchMock)
    // No jsdom in this project's vitest config (node env) — api.js's `request()` reads
    // `window.location.origin` to resolve its relative API_BASE, so stub the minimal shape.
    vi.stubGlobal('window', { location: { origin: 'http://localhost' } })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('getComments hits the comments endpoint', async () => {
    await getComments('excel', 'pivot')
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/skills/excel/pivot/comments')
  })

  it('postComment omits parentId when not given (top-level comment)', async () => {
    await postComment('excel', 'pivot', 'nice skill')
    const [, opts] = fetchMock.mock.calls[0]
    expect(JSON.parse(opts.body)).toEqual({ body: 'nice skill' })
  })

  it('postComment includes parentId when replying', async () => {
    await postComment('excel', 'pivot', 'thanks!', 42)
    const [, opts] = fetchMock.mock.calls[0]
    expect(JSON.parse(opts.body)).toEqual({ body: 'thanks!', parentId: 42 })
  })

  it('deleteComment DELETEs the comment-specific endpoint', async () => {
    await deleteComment('excel', 'pivot', 7)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skills/excel/pivot/comments/7')
    expect(opts.method).toBe('DELETE')
  })

  it('starSkill POSTs to the star endpoint', async () => {
    await starSkill('excel', 'pivot')
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skills/excel/pivot/star')
    expect(opts.method).toBe('POST')
  })

  it('unstarSkill DELETEs the star endpoint', async () => {
    await unstarSkill('excel', 'pivot')
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skills/excel/pivot/star')
    expect(opts.method).toBe('DELETE')
  })

  it('subscribeSkill POSTs to the subscription endpoint', async () => {
    await subscribeSkill('excel', 'pivot')
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skills/excel/pivot/subscription')
    expect(opts.method).toBe('POST')
  })

  it('unsubscribeSkill DELETEs the subscription endpoint', async () => {
    await unsubscribeSkill('excel', 'pivot')
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skills/excel/pivot/subscription')
    expect(opts.method).toBe('DELETE')
  })

  it('getMySubscriptions hits /my/subscriptions', async () => {
    await getMySubscriptions()
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/my/subscriptions')
  })
})
