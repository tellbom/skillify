<script setup>
// 403 — session/token expired. Reached when Keycloak token refresh fails.
import { useI18n } from 'vue-i18n'
import { login } from '../../lib/authBootstrap.js'
import { isKeycloakConfigured } from '../../lib/keycloak.js'

const { t } = useI18n()

async function signIn() {
  await login().catch(() => {})
}
</script>

<template>
  <div class="error-page">
    <h1>{{ t('auth-pages.sessionExpiredTitle') }}</h1>
    <p>{{ t('auth-pages.sessionExpiredBody') }}</p>
    <button v-if="isKeycloakConfigured()" type="button" class="retry-btn" @click="signIn">
      {{ t('auth-pages.signIn') }}
    </button>
  </div>
</template>

<style scoped>
.error-page {
  max-width: 520px;
  margin: 6rem auto 0;
  text-align: center;
}
.retry-btn {
  margin-top: 1rem;
  padding: 0.5rem 1.2rem;
  border: 1px solid #80cbc4;
  border-radius: 4px;
  background: none;
  color: #80cbc4;
  cursor: pointer;
}
</style>
