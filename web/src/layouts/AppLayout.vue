<!--
 * @Author: fzq
 * @Date: 2026-07-14 20:43:15
 * @LastEditors: fzq
 * @LastEditTime: 2026-07-14 21:31:35
 * @Description: 
 * @FilePath: \skillify\web\src\layouts\AppLayout.vue
-->
<script setup>
// Shared shell for authenticated Skillify business pages. Navigation remains fully driven by
// the backend menu tree; the visual components only render routes already granted to the user.
import { useRoute, useRouter } from 'vue-router'
import { logout } from '../lib/authBootstrap.js'
import { useAuthStore } from '../stores/auth.js'
import { useMenuStore } from '../stores/menu.js'
import AppHeader from './AppHeader.vue'
import AppFooter from './AppFooter.vue'

const auth = useAuthStore()
const menu = useMenuStore()
const route = useRoute()
const router = useRouter()

function handleLogout() {
  logout(router)
}
</script>

<template>
  <div class="app-shell">
    <AppHeader
      :nav-items="menu.navTree"
      :username="`${auth.rbacInfo.username}`"
      :is-authenticated="auth.isAuthenticated"
      :current-path="route.path"
      @logout="handleLogout"
    />

    <p v-if="menu.bootstrapError" class="bootstrap-error">{{ menu.bootstrapError }}</p>

    <main class="app-main">
      <router-view />
    </main>

    <AppFooter :nav-items="menu.navTree" />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  width: 100%;
  min-height: 100vh;
  flex-direction: column;
}

.bootstrap-error {
  box-sizing: border-box;
  width: calc(100% - 56px);
  max-width: 1264px;
  margin: 1rem auto 0;
  padding: 0.75rem 1rem;
  border: 1px solid #a33;
  border-radius: 6px;
  color: #ffb4b4;
  background: #2a1414;
  font-size: 0.9rem;
}

.app-main {
  box-sizing: border-box;
  width: 100%;
  max-width: 1320px;
  margin: 0 auto;
  padding: 26px 28px 48px;
  flex: 1;
}

@media (max-width: 900px) {
  .bootstrap-error {
    width: calc(100% - 40px);
  }

  .app-main {
    padding: 24px 20px 42px;
  }
}
</style>
