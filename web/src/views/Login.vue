<script setup>
// Framework-level login landing (static route /login). Reached when the RBAC client hits a
// 401, or as an explicit login entry point. The auth guard normally redirects unauthenticated
// users straight to Keycloak, so this page is mostly a fallback surface + error display.
import { useI18n } from 'vue-i18n'
import { login } from '../lib/authBootstrap.js'
import { isKeycloakConfigured } from '../lib/keycloak.js'
import { useMenuStore } from '../stores/menu.js'

const { t } = useI18n()
const menu = useMenuStore()

async function handleLogin() {
  try {
    await login()
  } catch (err) {
    menu.setError(err.message)
  }
}
</script>

<template>
  <div class="login-page">
    <h1>Skillify</h1>
    <p class="tagline">{{ t('common.tagline') }}</p>
    <p v-if="menu.bootstrapError" class="error">{{ menu.bootstrapError }}</p>
    <button
      v-if="isKeycloakConfigured()"
      type="button"
      class="login-btn"
      @click="handleLogin"
    >
      {{ t('auth-pages.loginWithKeycloak') }}
    </button>
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
.login-btn {
  margin-top: 1.5rem;
  padding: 0.6rem 1.4rem;
  border: 1px solid #80cbc4;
  border-radius: 4px;
  background: none;
  color: #80cbc4;
  cursor: pointer;
  font-size: 1rem;
}
</style>
