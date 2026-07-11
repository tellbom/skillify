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
      : payload.detail
    throw new Error(detail || `${resp.status} ${resp.statusText}`)
  }
  return resp.json()
}

export function listSkills(query) {
  return query ? request('/search', { params: { q: query } }) : request('/skills')
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

export function uploadSkill(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request('/skills/upload', { method: 'POST', body: formData, auth: true })
}

export function getComments(namespace, name) {
  return request(`/skills/${namespace}/${name}/comments`)
}

export function postComment(namespace, name, body) {
  return request(`/skills/${namespace}/${name}/comments`, { method: 'POST', json: { body }, auth: true })
}

export function getLeaderboard(dimension) {
  return request('/leaderboard', { params: { dimension } })
}

export function postRating(namespace, name, score) {
  return request(`/skills/${namespace}/${name}/rating`, { method: 'POST', json: { score }, auth: true })
}
