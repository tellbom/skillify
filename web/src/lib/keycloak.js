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

function sha256(data) {
  const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ])
  const bytes = new Uint8Array(data)
  const padLen = bytes.length % 64 < 56 ? 56 - (bytes.length % 64) : 120 - (bytes.length % 64)
  const padded = new Uint8Array(bytes.length + padLen + 8)
  padded.set(bytes)
  padded[bytes.length] = 0x80
  const dv = new DataView(padded.buffer)
  const bitLen = bytes.length * 8
  dv.setUint32(padded.length - 4, bitLen >>> 0, false)
  dv.setUint32(padded.length - 8, Math.floor(bitLen / 2 ** 32), false)
  const rotr = (x, n) => (x >>> n) | (x << (32 - n))
  let [h0, h1, h2, h3, h4, h5, h6, h7] = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]
  for (let i = 0; i < padded.length; i += 64) {
    const w = new Uint32Array(64)
    for (let j = 0; j < 16; j++) w[j] = dv.getUint32(i + j * 4, false)
    for (let j = 16; j < 64; j++) {
      const s0 = rotr(w[j - 15], 7) ^ rotr(w[j - 15], 18) ^ (w[j - 15] >>> 3)
      const s1 = rotr(w[j - 2], 17) ^ rotr(w[j - 2], 19) ^ (w[j - 2] >>> 10)
      w[j] = (w[j - 16] + s0 + w[j - 7] + s1) >>> 0
    }
    let [a, b, c, d, e, f, g, h] = [h0, h1, h2, h3, h4, h5, h6, h7]
    for (let j = 0; j < 64; j++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
      const ch = (e & f) ^ (~e & g)
      const t1 = (h + S1 + ch + K[j] + w[j]) >>> 0
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
      const mj = (a & b) ^ (a & c) ^ (b & c)
      const t2 = (S0 + mj) >>> 0
      h = g; g = f; f = e; e = (d + t1) >>> 0
      d = c; c = b; b = a; a = (t1 + t2) >>> 0
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0
  }
  const out = new Uint8Array(32)
  const ov = new DataView(out.buffer)
  ov.setUint32(0, h0, false); ov.setUint32(4, h1, false); ov.setUint32(8, h2, false); ov.setUint32(12, h3, false)
  ov.setUint32(16, h4, false); ov.setUint32(20, h5, false); ov.setUint32(24, h6, false); ov.setUint32(28, h7, false)
  return out.buffer
}

function injectCryptoPolyfill() {
  if (typeof window === 'undefined') return
  if (!window.crypto) {
    Object.defineProperty(window, 'crypto', { value: {}, writable: true, configurable: true })
  }
  const crypto = window.crypto
  if (typeof crypto.getRandomValues !== 'function') {
    crypto.getRandomValues = (buffer) => {
      let s0 = (Date.now() ^ 0xdeadbeef) >>> 0
      let s1 = ((performance.now() * 1000) ^ 0xcafebabe) >>> 0
      const bytes = new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength)
      for (let i = 0; i < bytes.length; i++) {
        const t = s1
        s0 ^= s0 << 23; s0 ^= s0 >>> 17; s0 ^= t ^ (t >>> 26); s1 = t
        bytes[i] = (s0 + s1) & 0xff
      }
      return buffer
    }
  }
  if (typeof crypto.randomUUID !== 'function') {
    crypto.randomUUID = () => {
      const bytes = crypto.getRandomValues(new Uint8Array(16))
      bytes[6] = (bytes[6] & 0x0f) | 0x40
      bytes[8] = (bytes[8] & 0x3f) | 0x80
      const hex = Array.from(bytes).map((value) => value.toString(16).padStart(2, '0')).join('')
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
    }
  }
  if (!crypto.subtle) {
    crypto.subtle = {
      digest(algorithm, data) {
        const name = typeof algorithm === 'string' ? algorithm.toUpperCase() : (algorithm?.name || '').toUpperCase()
        if (name !== 'SHA-256') return Promise.reject(new Error(`[crypto polyfill] Unsupported algorithm: ${String(algorithm)}`))
        const buffer = ArrayBuffer.isView(data)
          ? data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength)
          : data
        return Promise.resolve(sha256(buffer))
      },
    }
  }
}

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
  injectCryptoPolyfill()
  const kc = getKeycloak()
  const redirectUri = `${window.location.origin}/login`
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
  injectCryptoPolyfill()
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
