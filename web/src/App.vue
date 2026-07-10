<script setup>
// The app shell (header, nav, auth area) now lives in the routed layout component
// (layouts/AppLayout.vue), which is the component for the "/" layout route. Framework routes
// (login, error pages) render standalone. App.vue is just the top-level outlet.
</script>

<template>
  <router-view />
</template>
