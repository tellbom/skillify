<script setup>
// 404 — no route matched (catch-all redirects here). Also the target when authenticated but
// the requested business route isn't registered for this user.
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <div class="error-page">
    <h1>{{ t('auth-pages.notFoundTitle') }}</h1>
    <p>{{ t('auth-pages.notFoundBody') }}</p>
    <router-link to="/" class="home-link">{{ t('auth-pages.backToSkillify') }}</router-link>
  </div>
</template>

<style scoped>
.error-page {
  max-width: 480px;
  margin: 6rem auto 0;
  text-align: center;
}
.error-page h1 {
  font-size: 3rem;
  margin-bottom: 0.5rem;
}
.home-link {
  color: #80cbc4;
  text-decoration: none;
}
</style>
