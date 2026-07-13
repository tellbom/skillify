<script setup>
// Root layout shell for all Skillify business pages. Navigation is rendered from the
// backend-driven menu tree (menuStore.navTree), NOT hardcoded — a page only appears here if
// Rbac.Api returned it for the current user (see router/dynamicRoutes.js). The dynamic
// business routes render into this component's <router-view>.
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { logout } from '../lib/authBootstrap.js'
import { useAuthStore } from '../stores/auth.js'
import { useMenuStore } from '../stores/menu.js'

const { t } = useI18n()
const auth = useAuthStore()
const menu = useMenuStore()
const router = useRouter()

function handleLogout() {
  logout(router)
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <router-link to="/" class="brand">Skillify</router-link>
      <span class="tagline">{{ t('common.tagline') }}</span>
      <nav class="nav-links">
        <template v-for="item in menu.navTree" :key="item.name">
          <div v-if="item.children.length" class="nav-group">
            <span class="nav-group-title">{{ item.title }}</span>
            <div class="nav-group-menu">
              <router-link v-for="child in item.children" :key="child.name" :to="child.path">
                {{ child.title }}
              </router-link>
            </div>
          </div>
          <router-link v-else :to="item.path">{{ item.title }}</router-link>
        </template>
      </nav>
      <div class="auth-area">
        <template v-if="auth.isAuthenticated">
          <span class="username">{{ auth.username }}</span>
          <button type="button" class="link-btn" @click="handleLogout">{{ t('auth-pages.logOut') }}</button>
        </template>
      </div>
    </header>
    <p v-if="menu.bootstrapError" class="bootstrap-error">{{ menu.bootstrapError }}</p>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 1.5rem;
}
.app-header {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 1.5rem 0;
  border-bottom: 1px solid #333;
}
.brand {
  font-size: 1.4rem;
  font-weight: 700;
  color: inherit;
  text-decoration: none;
}
.tagline {
  color: #888;
  font-size: 0.9rem;
}
.nav-links {
  margin-left: 1rem;
  display: flex;
  gap: 0.75rem;
}
.nav-links a {
  color: #80cbc4;
  text-decoration: none;
  font-size: 0.9rem;
}
.nav-group {
  position: relative;
}
.nav-group-title {
  color: #80cbc4;
  cursor: default;
  font-size: 0.9rem;
}
.nav-group-menu {
  display: none;
  position: absolute;
  z-index: 20;
  top: 100%;
  left: 0;
  min-width: 9rem;
  padding: 0.5rem;
  border: 1px solid #444;
  border-radius: 6px;
  background: #1c1c1c;
  box-shadow: 0 8px 24px rgb(0 0 0 / 30%);
}
.nav-group:hover .nav-group-menu,
.nav-group:focus-within .nav-group-menu {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.auth-area {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.85rem;
}
.username {
  color: #ccc;
}
.link-btn {
  background: none;
  border: 1px solid #444;
  border-radius: 4px;
  color: inherit;
  padding: 0.25rem 0.6rem;
  cursor: pointer;
  font-size: 0.85rem;
  white-space: nowrap;
}
.bootstrap-error {
  margin: 1rem 0 0;
  padding: 0.75rem 1rem;
  border: 1px solid #a33;
  border-radius: 4px;
  color: #ffb4b4;
  background: #2a1414;
  font-size: 0.9rem;
}
.app-main {
  padding: 1.5rem 0 3rem;
}

@media (max-width: 640px) {
  .app-header {
    align-items: center;
    flex-wrap: wrap;
  }
  .tagline {
    flex: 1 1 auto;
    min-width: 0;
  }
  .nav-links {
    order: 1;
    width: 100%;
    margin-left: 0;
    flex-wrap: wrap;
  }
  .auth-area {
    margin-left: 0;
    flex-shrink: 0;
  }
}
</style>
