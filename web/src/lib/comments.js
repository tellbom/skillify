// Pure helpers for the C-5 community comment tree (CommentSection.vue). Kept separate from the
// component so the grouping logic is unit-testable without mounting Vue (see web/src/lib/versions.js
// for the pattern this follows).
//
// Backend behavior (Task 6, confirmed): reply nesting is NOT limited to one level — a reply can
// itself be replied to, indefinitely (parentId chains arbitrarily deep). This UI intentionally
// flattens that into a two-tier view (top-level comments + a single indented list of all their
// descendants, ordered by createdAt) rather than rendering a full recursive tree — simpler to
// build/test and still lets every comment be read and replied to.

/**
 * Group a flat CommentOut[] (from GET /skills/{ns}/{name}/comments) into a two-tier structure:
 * top-level comments (parentId == null) each carrying a `replies` array of every comment in
 * their subtree (any depth), flattened and sorted oldest-first. Comments whose parentId points
 * at a missing/unknown id (shouldn't happen, but defensive) are treated as top-level so nothing
 * silently disappears from the UI.
 * @param {Array<{id: number, parentId: number|null, author: string, createdAt: string, body: string, deleted: boolean}>} comments
 * @returns {Array<{id: number, parentId: number|null, author: string, createdAt: string, body: string, deleted: boolean, replies: Array}>}
 */
export function buildCommentTree(comments) {
  const list = comments || []
  const byId = new Map(list.map((c) => [c.id, c]))

  // Resolve each comment's top-level ancestor by walking parentId chains. A comment whose
  // ancestor chain is broken (dangling parentId) or that has no parent is its own root.
  function rootIdFor(comment) {
    let current = comment
    const seen = new Set()
    while (current.parentId != null && byId.has(current.parentId) && !seen.has(current.id)) {
      seen.add(current.id)
      current = byId.get(current.parentId)
    }
    return current.id
  }

  const roots = []
  const rootsById = new Map()
  for (const c of list) {
    if (c.parentId == null || !byId.has(c.parentId)) {
      const node = { ...c, replies: [] }
      roots.push(node)
      rootsById.set(c.id, node)
    }
  }

  for (const c of list) {
    if (c.parentId == null || !byId.has(c.parentId)) continue
    const rootId = rootIdFor(c)
    const rootNode = rootsById.get(rootId)
    if (rootNode) rootNode.replies.push({ ...c })
  }

  for (const root of roots) {
    root.replies.sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt))
  }

  return roots
}

// Fixed palette lifted from the prototype's avatar-gradient circles, cycled by a deterministic
// hash of the username so the same author always renders the same color across reloads.
const AVATAR_PALETTE = ['#80CBC4', '#E0A458', '#5FB88E', '#E5807A', '#9575CD', '#4FC3F7']

/**
 * Deterministic avatar color for a comment author's initials circle: a simple string hash picks
 * a fixed palette entry, so re-renders (and other users viewing the same thread) always agree.
 * @param {string} name
 */
export function avatarColorFor(name) {
  const str = name || ''
  let hash = 0
  for (let i = 0; i < str.length; i += 1) {
    hash = (hash * 31 + str.charCodeAt(i)) | 0
  }
  const index = Math.abs(hash) % AVATAR_PALETTE.length
  return AVATAR_PALETTE[index]
}

/**
 * True when the current user is allowed to see a delete button for a comment: the comment's
 * author matches the logged-in username (per task-7 brief — namespace-owner deletes are also
 * permitted server-side, but the frontend only has the data to check authorship). Actual
 * authorization is enforced server-side (backend returns 403 otherwise) — this only controls
 * button visibility.
 * @param {{author: string, deleted: boolean}} comment
 * @param {string|null} currentUsername
 */
export function canDeleteComment(comment, currentUsername) {
  if (!currentUsername || comment.deleted) return false
  return comment.author === currentUsername
}
