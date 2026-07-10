<script setup>
// 401 — no access / initialization failed visibly. The specific reason (Keycloak not
// configured, no Skillify RBAC menu for this user, etc.) is surfaced from the menu store.
import { useMenuStore } from '../../stores/menu.js'
import { login } from '../../lib/authBootstrap.js'
import { isKeycloakConfigured } from '../../lib/keycloak.js'

const menu = useMenuStore()

async function retry() {
  try {
    await login()
  } catch (err) {
    menu.setError(err.message)
  }
}
</script>

<template>
  <div class="error-page">
    <h1>No access</h1>
    <p v-if="menu.bootstrapError" class="reason">{{ menu.bootstrapError }}</p>
    <p v-else>You don’t have permission to view Skillify.</p>
    <button v-if="isKeycloakConfigured()" type="button" class="retry-btn" @click="retry">
      Sign in again
    </button>
  </div>
</template>

<style scoped>
.error-page {
  max-width: 520px;
  margin: 6rem auto 0;
  text-align: center;
}
.reason {
  color: #ffb4b4;
  border: 1px solid #a33;
  background: #2a1414;
  border-radius: 4px;
  padding: 0.75rem 1rem;
  font-size: 0.9rem;
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
