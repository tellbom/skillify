import { useAuthStore } from '../stores/auth.js'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

async function request(path, { params, method = 'GET', body, json, auth = false } = {}) {
  const url = new URL(API_BASE + path, window.location.origin)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, value)
    }
  }

  const headers = {}
  // M-A (docs/review-m2-m6.md): every Skillify API call requires a Keycloak session now
  // (reads included), so this always attaches the token when one exists — `auth` used to
  // gate this per-call back when only writes were protected, but there's no longer a public
  // endpoint left in this client to opt out for. Left as a no-op parameter (default false,
  // still accepted by callers) rather than ripped out, so a future genuinely-public endpoint
  // doesn't have to touch every call site again.
  const token = useAuthStore().token
  if (token) headers.Authorization = `Bearer ${token}`
  let requestBody = body
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    requestBody = JSON.stringify(json)
  }

  const resp = await fetch(url, { method, headers, body: requestBody })
  if (!resp.ok) {
    const payload = await resp.json().catch(() => ({}))
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((d) => `${d.path}: ${d.message}`).join('; ')
      : typeof payload.detail === 'object' && payload.detail !== null
        ? payload.detail.message || JSON.stringify(payload.detail)
        : payload.detail
    const err = new Error(detail || `${resp.status} ${resp.statusText}`)
    // Skill-build flows (preview/confirm) need the raw structured detail — 409 revision
    // conflicts carry `currentRevision`, 422 publish-not-ready carries `missingFields` /
    // `unconfirmedFields` / `issues`. Attached alongside `message` so every existing caller
    // that only reads `err.message` keeps working unchanged.
    err.status = resp.status
    err.detail = payload.detail
    throw err
  }
  if (resp.status === 204) return null
  return resp.json()
}

// C-4 search/filter/sort/pagination (Task 9 endpoints). Both /skills and /search now share the
// same query-param contract and both return the SearchResult wrapper
// ({items, total, page, pageSize}) instead of a bare array — this is a breaking change from the
// pre-Task-9 shape, so every call site consuming listSkills() must read `.items`, not treat the
// result itself as the array. `/search` is used whenever a text query is present (existing
// behavior); `/skills` otherwise — filters/sort/pagination apply identically either way per the
// Task 9 brief. `params` here (namespace/author/tags/sort/page/pageSize) are optional and passed
// straight through to request(), which already drops undefined/null/'' entries.
export function listSkills(query, params = {}) {
  const q = query ? query.trim() : ''
  const allParams = { ...params, q: q || undefined }
  return q ? request('/search', { params: allParams }) : request('/skills', { params: allParams })
}

export function getSkillDetail(namespace, name, version) {
  return request(`/skills/${namespace}/${name}`, { params: { version } })
}

export function getVersions(namespace, name) {
  return request(`/skills/${namespace}/${name}/versions`)
}

export function getVersionDiff(namespace, name, from, to) {
  return request(`/skills/${namespace}/${name}/diff`, { params: { from, to } })
}

export function yankVersion(namespace, name, version) {
  return request(`/skills/${namespace}/${name}/versions/${version}/yank`, { method: 'POST', auth: true })
}

export function unyankVersion(namespace, name, version) {
  return request(`/skills/${namespace}/${name}/versions/${version}/unyank`, { method: 'POST', auth: true })
}

export function getInstallInfo(namespace, name) {
  return request(`/skills/${namespace}/${name}/install`)
}

// Compatibility note: this used to return the *published* result directly. The backend now
// stages the zip into a temporary BuildPreview instead (namespace/Release/index are NOT
// touched yet) — callers must show the preview and call publishSkillBuild() after explicit
// user confirmation, never treat this response as "published".
export function uploadSkill(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request('/skills/upload', { method: 'POST', body: formData, auth: true })
}

export function createGuidedBuild(manifest, skillMd) {
  return request('/skill-builds/guided', { method: 'POST', json: { manifest, skillMd }, auth: true })
}

export function getSkillBuild(buildId) {
  return request(`/skill-builds/${buildId}`, { auth: true })
}

export function patchSkillBuild(buildId, { expectedRevision, manifest, skillMd }) {
  const payload = { expectedRevision }
  if (manifest !== undefined) payload.manifest = manifest
  if (skillMd !== undefined) payload.skillMd = skillMd
  return request(`/skill-builds/${buildId}`, { method: 'PATCH', json: payload, auth: true })
}

export function addSkillBuildFile(buildId, { path, expectedRevision, file }) {
  const formData = new FormData()
  formData.append('path', path)
  formData.append('expectedRevision', String(expectedRevision))
  formData.append('file', file)
  return request(`/skill-builds/${buildId}/files`, { method: 'POST', body: formData, auth: true })
}

export function deleteSkillBuildFile(buildId, { path, expectedRevision }) {
  return request(`/skill-builds/${buildId}/files`, {
    method: 'DELETE',
    params: { path, expectedRevision },
    auth: true,
  })
}

export function publishSkillBuild(buildId, { expectedRevision, confirmed }) {
  return request(`/skill-builds/${buildId}/publish`, {
    method: 'POST',
    json: { expectedRevision, confirmed },
    auth: true,
  })
}

export function scanExternalSkill(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request('/external-skill-scans', { method: 'POST', body: formData, auth: true })
}

export function selectExternalCandidates(scanId, candidateIds) {
  return request(`/external-skill-scans/${scanId}/selections`, {
    method: 'POST',
    json: { candidateIds },
    auth: true,
  })
}

export function getComments(namespace, name) {
  return request(`/skills/${namespace}/${name}/comments`)
}

export function postComment(namespace, name, body, parentId) {
  const payload = parentId != null ? { body, parentId } : { body }
  return request(`/skills/${namespace}/${name}/comments`, { method: 'POST', json: payload, auth: true })
}

export function deleteComment(namespace, name, commentId) {
  return request(`/skills/${namespace}/${name}/comments/${commentId}`, { method: 'DELETE', auth: true })
}

// C-5 community (Task 6 endpoints): star / subscribe are idempotent both directions — no need
// to check current state before calling, just toggle the button and call the matching verb.
export function starSkill(namespace, name) {
  return request(`/skills/${namespace}/${name}/star`, { method: 'POST', auth: true })
}

export function unstarSkill(namespace, name) {
  return request(`/skills/${namespace}/${name}/star`, { method: 'DELETE', auth: true })
}

export function subscribeSkill(namespace, name) {
  return request(`/skills/${namespace}/${name}/subscription`, { method: 'POST', auth: true })
}

export function unsubscribeSkill(namespace, name) {
  return request(`/skills/${namespace}/${name}/subscription`, { method: 'DELETE', auth: true })
}

export function getMySubscriptions() {
  return request('/my/subscriptions', { auth: true })
}

export function getLeaderboard(dimension, window) {
  return request('/leaderboard', { params: { dimension, window } })
}

export function postRating(namespace, name, score) {
  return request(`/skills/${namespace}/${name}/rating`, { method: 'POST', json: { score }, auth: true })
}

export function reportSkillSignal(namespace, name, version, eventType, success) {
  return request(`/skills/${namespace}/${name}/events`, {
    method: 'POST', json: { version, eventType, success }, auth: true,
  })
}

// C-2 "我的 Skill" workspace (Task 4 endpoints). All four require auth like every other call
// here now (see the request() comment above) — `auth: true` kept for readability at the call
// site even though it's currently a no-op flag.
export function getMySkills() {
  return request('/my/skills', { auth: true })
}

export function getMyNamespaces() {
  return request('/my/namespaces', { auth: true })
}

export function getMyPublishJobs(status) {
  return request('/my/publish-jobs', { params: { status }, auth: true })
}

export function getMyUsage() {
  return request('/my/usage', { auth: true })
}

export function getMyEndpoints() {
  return request('/my/endpoints', { auth: true })
}

export function getEndpointTasks() {
  return request('/endpoint-tasks', { auth: true })
}

export function dispatchEndpointTask(payload) {
  return request('/endpoint-tasks', { method: 'POST', json: payload, auth: true })
}

export function cancelEndpointTask(taskId) {
  return request(`/endpoint-tasks/${taskId}/cancel`, { method: 'POST', auth: true })
}

export function updateTaskWorkPackages(taskId, packages) {
  return request(`/endpoint-tasks/${taskId}/work-packages`, {
    method: 'PUT', json: { packages }, auth: true,
  })
}

export function confirmTaskWorkPackages(taskId) {
  return request(`/endpoint-tasks/${taskId}/work-packages/confirm`, { method: 'POST', auth: true })
}
