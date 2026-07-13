<script setup>
// Framework-level login landing (static route /login). Reached when the RBAC client hits a
// 401, or as an explicit login entry point. The auth guard normally redirects unauthenticated
// users straight to Keycloak, so this page is mostly a fallback surface + error display.
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { login } from '../lib/authBootstrap.js'
import { isKeycloakConfigured } from '../lib/keycloak.js'
import { useMenuStore } from '../stores/menu.js'

const { t } = useI18n()
const menu = useMenuStore()
const route = useRoute()
const router = useRouter()
const LOGIN_REDIRECT_KEY = 'skillify.login.redirect'

async function handleLogin() {
  try {
    if (typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/')) {
      sessionStorage.setItem(LOGIN_REDIRECT_KEY, route.query.redirect)
    }
    await login()
    const redirect = sessionStorage.getItem(LOGIN_REDIRECT_KEY) || '/'
    sessionStorage.removeItem(LOGIN_REDIRECT_KEY)
    await router.replace(redirect)
  } catch (err) {
    menu.setError(err.message)
  }
}

onMounted(handleLogin)
</script>

<template>
  <div class="login-page">
    <h1>Skillify</h1>
    <p class="tagline">{{ t('common.tagline') }}</p>
    <p v-if="menu.bootstrapError" class="error">{{ menu.bootstrapError }}</p>
    <p v-if="isKeycloakConfigured() && !menu.bootstrapError" class="tagline">正在跳转到统一认证平台…</p>
    <p v-else class="error">
      {{ t('errors.keycloakNotConfigured') }}
    </p>
  </div>
</template>

<style scoped>
.login-page {
  max-width: 420px;
  margin: 6rem auto 0;
  text-align: center;
}
.tagline {
  color: #888;
  margin-top: -0.5rem;
}
.error {
  color: #ffb4b4;
  border: 1px solid #a33;
  background: #2a1414;
  border-radius: 4px;
  padding: 0.75rem 1rem;
  font-size: 0.9rem;
}
</style>
