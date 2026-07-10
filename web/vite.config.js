import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [vue()],
    server: {
      proxy: {
        // Dev convenience: `skillctl` community backend (T3.1, skillify-web) defaults to
        // :8089. Frontend calls relative `/api/...` (see src/lib/api.js); this proxies that
        // through in dev so no CORS config is needed (backend also sets permissive CORS).
        '/api': {
          target: 'http://127.0.0.1:8089',
          changeOrigin: true,
        },
        // M4: dev-only proxy to the external Rbac.Api, avoiding CORS while VITE_RBAC_BASE_URL
        // is still a placeholder — see src/lib/rbacClient.js and web/.env.example.
        '/rbacServer': {
          target: env.VITE_RBAC_BASE_URL || 'http://127.0.0.1:5005',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/rbacServer/, ''),
        },
      },
    },
  }
})
