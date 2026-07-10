// The single static route the dynamic (backend-driven) business routes are attached under.
// Kept in its own module so both the router factory (router/index.js) and the dynamic-route
// engine (router/dynamicRoutes.js) can import it without a circular dependency.
export const LAYOUT_ROUTE_NAME = 'layout'

// Framework-level static routes that must always resolve WITHOUT a backend menu — the auth
// guard lets these through untouched (login screen + error pages). Everything else is a
// business route that only exists once /api/admin/index has been walked.
export const FRAMEWORK_ROUTE_NAMES = new Set([
  'login',
  'unauthorized', // /401
  'tokenExpired', // /403
  'notFound', // /404
])
