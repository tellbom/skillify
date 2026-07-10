<script setup>
// The app shell (header, nav, auth area) now lives in the routed layout component
// (layouts/AppLayout.vue), which is the component for the "/" layout route. Framework routes
// (login, error pages) render standalone. App.vue is just the top-level outlet.
import { useI18n } from 'vue-i18n'
import { useLocaleStore } from './stores/locale.js'

const localeStore = useLocaleStore()
const { getLocaleMessage } = useI18n()
const lang = getLocaleMessage(localeStore.defaultLang)
</script>

<template>
  <el-config-provider :locale="lang">
    <router-view />
  </el-config-provider>
</template>
