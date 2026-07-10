import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../src/stores/auth.js'
import { rbacClient, RbacApiError, isRbacConfigured } from '../src/api/backend/rbac/index.ts'

// N4.2 hard gate: verifies the ported RBAC client reads its Bearer token from Skillify's
// useAuthStore (not flow/web's original useAdminInfo store) and preserves the
// code===0-success / RbacApiError-on-failure response contract.
describe('rbac client (N4.2 port)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('injects the Keycloak token from useAuthStore as a Bearer header', () => {
    const auth = useAuthStore()
    auth.setSession('tok123', 'alice')
    const requestHandler = rbacClient.interceptors.request.handlers[0].fulfilled
    const config = requestHandler({ headers: {} })
    expect(config.headers['Authorization']).toBe('Bearer tok123')
    expect(config.headers['X-Project']).toBe('skillify')
  })

  it('omits the Authorization header when no session token is set', () => {
    const requestHandler = rbacClient.interceptors.request.handlers[0].fulfilled
    const config = requestHandler({ headers: {} })
    expect(config.headers['Authorization']).toBeUndefined()
  })

  it('unwraps a code:0 response to just the data payload', () => {
    const responseHandler = rbacClient.interceptors.response.handlers[0].fulfilled
    const result = responseHandler({
      data: { code: 0, msg: '', data: { hello: 'world' }, time: 1 },
      config: {},
    })
    expect(result).toEqual({ hello: 'world' })
  })

  it('rejects with RbacApiError for a non-zero business code', async () => {
    const responseHandler = rbacClient.interceptors.response.handlers[0].fulfilled
    await expect(
      Promise.resolve().then(() =>
        responseHandler({ data: { code: 40100, msg: '', data: null, time: 1 }, config: {} }),
      ),
    ).rejects.toBeInstanceOf(RbacApiError)
  })

  it('isRbacConfigured() is true under the dev proxy', () => {
    expect(isRbacConfigured()).toBe(true)
  })
})
