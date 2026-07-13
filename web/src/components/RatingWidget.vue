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
const hoverValue = ref(0)

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
      <span class="score">{{ ratingAverage !== null ? ratingAverage.toFixed(1) : t('comment-rating.unrated') }}</span>
      <span class="star-icon">★</span>
      <span class="count">({{ ratingCount }})</span>
    </span>
    <span v-if="auth.isAuthenticated" class="stars" @mouseleave="hoverValue = 0">
      <button
        v-for="n in 5"
        :key="n"
        type="button"
        class="star-btn"
        :class="{ filled: (hoverValue || 0) >= n }"
        :disabled="submitting"
        :title="t('comment-rating.rateThisSkill')"
        @mouseenter="hoverValue = n"
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
  gap: 10px;
  font-size: 13.5px;
}
.summary {
  color: #c9c9c9;
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}
.star-icon {
  color: #e0a458;
}
.count {
  color: #6e6e6e;
  font-size: 12px;
}
.hint {
  color: #6e6e6e;
  font-size: 12.5px;
}
.error {
  color: #e5807a;
  font-size: 12px;
}
.stars {
  display: inline-flex;
  gap: 2px;
}
.star-btn {
  background: none;
  border: none;
  color: #3a3a3a;
  cursor: pointer;
  font-size: 17px;
  line-height: 1;
  padding: 0 1px;
  transition: color 0.1s;
}
.star-btn.filled {
  color: #e0a458;
}
.star-btn:disabled {
  cursor: default;
}
</style>
