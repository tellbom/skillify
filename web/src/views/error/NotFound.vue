<script setup>
// 404 — no route matched (catch-all redirects here). Also the target when authenticated but
// the requested business route isn't registered for this user.
</script>

<template>
  <div class="error-page">
    <h1>404</h1>
    <p>This page doesn’t exist.</p>
    <router-link to="/" class="home-link">Back to Skillify</router-link>
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
