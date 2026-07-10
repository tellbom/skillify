import Keycloak from 'keycloak-js'

// Config from Vite env vars — placeholders until real Keycloak values are available
// (see web/.env.example). VITE_KEYCLOAK_REALM_URL is expected as the full realm issuer URL,
// e.g. "https://sso.example.com/realms/internal"; VITE_KEYCLOAK_REALM is a fallback if the
// URL doesn't match the standard "/realms/{realm}" shape.
function getRealmConfig() {
  const realmUrl = import.meta.env.VITE_KEYCLOAK_REALM_URL || ''
  const match = realmUrl.match(/^(https?:\/\/[^/]+(?:\/[^/]+)*?)\/realms\/([^/]+)\/?$/)
  if (match) {
    return { url: match[1], realm: match[2] }
  }
  return { url: realmUrl, realm: import.meta.env.VITE_KEYCLOAK_REALM || '' }
}

let keycloakInstance = null
// keycloak-js allows exactly one kc.init() per instance. With the backend-driven routing
// guard, a page load can do a silent check-sso (ensureKeycloakSession) AND then, if that
// finds no session, a login redirect — the latter must NOT call kc.init() again. We track
// init state so loginWithKeycloak() falls back to kc.login() once initialized.
let initialized = false

export function getKeycloak() {
  if (!keycloakInstance) {
    const { url, realm } = getRealmConfig()
    keycloakInstance = new Keycloak({
      url,
      realm,
      clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID || 'skillify-web',
    })
  }
  return keycloakInstance
}

export function isKeycloakConfigured() {
  const { url, realm } = getRealmConfig()
  return Boolean(url && realm)
}

// Full-page redirect login (Authorization Code + PKCE) — mirrors the pattern in
// E:\Web\flow\web\src\utils\keycloak.ts, minus the TS types and the crypto.subtle polyfill
// (assumed unnecessary for a modern-browser-only internal tool served over HTTPS). If the
// instance was already initialized (e.g. a prior check-sso), redirect via kc.login() instead
// of a second kc.init() (which keycloak-js forbids).
export async function loginWithKeycloak() {
  const kc = getKeycloak()
  const redirectUri = window.location.href
  if (initialized) {
    await kc.login({ redirectUri }) // full-page redirect; resolves only after return
    return kc.authenticated ? kc : null
  }
  initialized = true
  const authenticated = await kc.init({ onLoad: 'login-required', pkceMethod: 'S256', checkLoginIframe: false, redirectUri })
  return authenticated ? kc : null
}

// Silent session check on page load/reload — does not force a login redirect.
export async function ensureKeycloakSession() {
  const kc = getKeycloak()
  if (initialized) return Boolean(kc.authenticated)
  try {
    initialized = true
    return await kc.init({ onLoad: 'check-sso', pkceMethod: 'S256', checkLoginIframe: false, redirectUri: window.location.href })
  } catch {
    return false
  }
}

export function logoutWithKeycloak() {
  const kc = getKeycloak()
  return kc.logout({ redirectUri: window.location.origin })
}

let pollHandle = null

// M-E (docs/review-m2-m6.md): `updateToken` refreshes keycloak-js's own in-memory token but
// callers (api.js, the router guard) read the token out of the Pinia auth store, not this
// module — without `onRefreshed`, a successful background refresh was silently invisible to
// the rest of the app until the *next* full login, and API calls would start 401ing once the
// pre-refresh token expired. Mirrors flow/web's `syncKeycloakTokens` pattern
// (E:\Web\flow\web\src\utils\keycloak.ts), which does write the refreshed token back.
export function startTokenRefreshPoll(onRefreshed, onRefreshFailed) {
  stopTokenRefreshPoll()
  pollHandle = setInterval(async () => {
    try {
      await getKeycloak().updateToken(30)
      onRefreshed?.(getKeycloak().token)
    } catch {
      stopTokenRefreshPoll()
      onRefreshFailed?.()
    }
  }, 20000)
}

export function stopTokenRefreshPoll() {
  if (pollHandle) {
    clearInterval(pollHandle)
    pollHandle = null
  }
}
