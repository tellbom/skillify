<script setup>
import { computed } from 'vue'

const props = defineProps({
  navItems: { type: Array, default: () => [] },
  username: { type: String, default: '' },
  isAuthenticated: { type: Boolean, default: false },
  currentPath: { type: String, default: '' },
})

defineEmits(['logout'])

const avatarText = computed(() => props.username.trim().slice(0, 2).toUpperCase() || '?')

function hasChildren(item) {
  return Array.isArray(item.children) && item.children.length > 0
}

function isActivePath(path) {
  return Boolean(path) && props.currentPath === path
}

function isGroupActive(item) {
  return hasChildren(item) && item.children.some((child) => isActivePath(child.path))
}
</script>

<template>
  <header class="app-header">
    <div class="header-inner">
      <div class="brand-lockup">
        <router-link to="/" class="brand" aria-label="Skillify 首页">
          Skill<span class="brand-accent">ify</span>
        </router-link>
        <span class="tagline">内部技能目录</span>
      </div>

      <nav class="nav-links" aria-label="主导航">
        <template v-for="item in navItems" :key="item.name">
          <div v-if="hasChildren(item)" class="nav-group">
            <button
              type="button"
              class="nav-item nav-group-title"
              :class="{ active: isGroupActive(item) }"
              :aria-current="isGroupActive(item) ? 'page' : undefined"
              aria-haspopup="true"
            >
              {{ item.title }}
              <span class="nav-chevron" aria-hidden="true">⌄</span>
            </button>
            <div class="nav-group-menu">
              <router-link
                v-for="child in item.children"
                :key="child.name"
                :to="child.path"
                class="nav-menu-link"
                :class="{ active: isActivePath(child.path) }"
                :aria-current="isActivePath(child.path) ? 'page' : undefined"
              >
                {{ child.title }}
              </router-link>
            </div>
          </div>
          <router-link
            v-else
            :to="item.path"
            class="nav-item"
            :class="{ active: isActivePath(item.path) }"
            :aria-current="isActivePath(item.path) ? 'page' : undefined"
          >
            {{ item.title }}
          </router-link>
        </template>
      </nav>

      <div v-if="isAuthenticated" class="auth-area">
        <div class="user-identity">
          <span class="user-avatar" aria-hidden="true">{{ avatarText }}</span>
          <span class="username">{{ username }}</span>
        </div>
        <button type="button" class="logout-button" @click="$emit('logout')">退出登录</button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: sticky;
  z-index: 50;
  top: 0;
  width: 100%;
  border-bottom: 1px solid #2c2c2c;
  background: rgb(18 18 18 / 86%);
  backdrop-filter: blur(10px);
}

.header-inner {
  box-sizing: border-box;
  display: flex;
  align-items: center;
  width: 100%;
  max-width: 1320px;
  height: 60px;
  margin: 0 auto;
  padding: 0 28px;
  gap: 28px;
}

.brand-lockup {
  display: flex;
  flex: none;
  align-items: baseline;
  gap: 10px;
}

.brand {
  color: #f2f2f2;
  font-size: 20px;
  font-weight: 750;
  letter-spacing: -0.3px;
  line-height: 1;
  text-decoration: none;
}

.brand-accent {
  color: #80cbc4;
}

.tagline {
  color: #6e6e6e;
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap;
}

.nav-links {
  display: flex;
  align-items: center;
  min-width: 0;
  margin-left: -20px;
  gap: 4px;
}

.nav-item {
  display: inline-flex;
  align-items: center;
  border: 0;
  border-radius: 7px;
  padding: 7px 12px;
  color: #9f9f9f;
  background: transparent;
  font: inherit;
  font-size: 13.5px;
  line-height: 1.2;
  text-decoration: none;
  white-space: nowrap;
  cursor: pointer;
  transition: color 0.15s ease, background-color 0.15s ease;
}

.nav-item:hover,
.nav-item:focus-visible,
.nav-item.active {
  color: #80cbc4;
  background: rgb(128 203 196 / 8%);
  outline: none;
}

.nav-group {
  position: relative;
}

.nav-chevron {
  margin-left: 5px;
  color: #666;
  font-size: 11px;
}

.nav-group-menu {
  position: absolute;
  z-index: 60;
  top: calc(100% + 8px);
  left: 0;
  display: flex;
  min-width: 160px;
  padding: 6px;
  border: 1px solid #353535;
  border-radius: 9px;
  visibility: hidden;
  background: #1b1b1b;
  box-shadow: 0 12px 32px rgb(0 0 0 / 35%);
  opacity: 0;
  transform: translateY(-4px);
  flex-direction: column;
  transition: opacity 0.15s ease, transform 0.15s ease, visibility 0.15s ease;
}

.nav-group:hover .nav-group-menu,
.nav-group:focus-within .nav-group-menu {
  visibility: visible;
  opacity: 1;
  transform: translateY(0);
}

.nav-menu-link {
  border-radius: 6px;
  padding: 8px 10px;
  color: #aaa;
  font-size: 13px;
  text-decoration: none;
  white-space: nowrap;
}

.nav-menu-link:hover,
.nav-menu-link:focus-visible,
.nav-menu-link.active {
  color: #80cbc4;
  background: rgb(128 203 196 / 8%);
  outline: none;
}

.auth-area {
  display: flex;
  flex: none;
  align-items: center;
  margin-left: auto;
  gap: 16px;
}

.user-identity {
  display: flex;
  align-items: center;
  gap: 9px;
}

.user-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  color: #0f1615;
  background: linear-gradient(135deg, #2f4f4c, #80cbc4);
  font-size: 12px;
  font-weight: 700;
}

.username {
  max-width: 150px;
  overflow: hidden;
  color: #c9c9c9;
  font-size: 13px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logout-button {
  border: 1px solid #2c2c2c;
  border-radius: 7px;
  padding: 6px 13px;
  color: #9f9f9f;
  background: transparent;
  font: inherit;
  font-size: 13px;
  line-height: 1.2;
  white-space: nowrap;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background-color 0.15s ease;
}

.logout-button:hover,
.logout-button:focus-visible {
  border-color: #444;
  color: #e5e5e5;
  background: #1a1a1a;
  outline: none;
}

@media (max-width: 900px) {
  .header-inner {
    height: auto;
    min-height: 60px;
    padding: 12px 20px;
    gap: 12px 18px;
    flex-wrap: wrap;
  }

  .nav-links {
    order: 1;
    width: 100%;
    margin-left: 0;
    overflow-x: auto;
  }

  .auth-area {
    margin-left: auto;
  }
}

@media (max-width: 560px) {
  .tagline,
  .username {
    display: none;
  }
}
</style>
