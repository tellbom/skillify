import axios from 'axios'

// Frontend connects directly to the external .NET Rbac.Api (not proxied through Skillify's
// own Python backend) — this is an explicit design choice, mirroring how
// E:\Web\flow\web\src\api\backend\rbac\client\index.ts talks to its RBAC backend. In dev,
// requests go through Vite's `/rbacServer` proxy (see vite.config.js) to avoid CORS; in
// production this should hit Rbac.Api's real base URL directly (VITE_RBAC_BASE_URL),
// which must itself allow CORS from the frontend's origin.
const RBAC_BASE = import.meta.env.DEV ? '/rbacServer' : import.meta.env.VITE_RBAC_BASE_URL || ''
const PROJECT = import.meta.env.VITE_RBAC_PROJECT || 'skillify'

const rbacHttp = axios.create({ baseURL: RBAC_BASE })

export function isRbacConfigured() {
  return Boolean(RBAC_BASE)
}

// POST /api/auth/login — validates the Keycloak JWT is authorized for this project and
// returns { token, routePath, adminInfo }. Response envelope per Rbac.Api's convention:
// `code === 0` means success (see E:\router\router\docs\rbac\global-read-reuse.md).
export async function rbacLogin(keycloakToken) {
  const resp = await rbacHttp.post(
    '/api/auth/login',
    {},
    { headers: { Authorization: `Bearer ${keycloakToken}`, 'X-Project': PROJECT } },
  )
  if (resp.data?.code !== 0) {
    throw new Error(resp.data?.message || 'RBAC login rejected')
  }
  return resp.data.data // { token, routePath, adminInfo }
}

// GET /api/admin/index — the pre-pruned "my menus" tree for the logged-in user.
export async function getRbacMenus(keycloakToken) {
  const resp = await rbacHttp.get('/api/admin/index', {
    headers: { Authorization: `Bearer ${keycloakToken}`, 'X-Project': PROJECT },
  })
  if (resp.data?.code !== 0) {
    throw new Error(resp.data?.message || 'failed to load RBAC menus')
  }
  return resp.data.data // { adminInfo, menus, routePath }
}
