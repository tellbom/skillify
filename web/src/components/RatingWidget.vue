<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { postRating } from '../lib/api.js'
import { useAuthStore } from '../stores/auth.js'

const props = defineProps({
  namespace: { type: String, required: true },
  name: { type: String, required: true },
  ratingAverage: { type: Number, default: null },
  ratingCount: { type: Number, default: 0 },
})
const emit = defineEmits(['rated'])

const { t } = useI18n()
const auth = useAuthStore()
const submitting = ref(false)
const error = ref(null)

async function rate(score) {
  submitting.value = true
  error.value = null
  try {
    const result = await postRating(props.namespace, props.name, score)
    emit('rated', result)
  } catch (err) {
    error.value = err.message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="rating">
    <span class="summary">
      {{ ratingAverage !== null ? ratingAverage.toFixed(1) : t('comment-rating.unrated') }} ★
      <span class="count">({{ ratingCount }})</span>
    </span>
    <span v-if="auth.isAuthenticated" class="stars">
      <button
        v-for="n in 5"
        :key="n"
        type="button"
        :disabled="submitting"
        :title="t('comment-rating.rateThisSkill')"
        @click="rate(n)"
      >
        ★
      </button>
    </span>
    <span v-else class="hint">{{ t('comment-rating.loginToRate') }}</span>
    <span v-if="error" class="error">{{ error }}</span>
  </div>
</template>

<style scoped>
.rating {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.85rem;
}
.summary { color: #ccc; }
.count { color: #888; }
.hint { color: #888; }
.error { color: #e06c75; }
.stars button {
  background: none;
  border: none;
  color: #555;
  cursor: pointer;
  font-size: 1rem;
  padding: 0 0.1rem;
}
.stars button:hover {
  color: #ffca28;
}
</style>
