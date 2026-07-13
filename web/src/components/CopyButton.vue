<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({ text: { type: String, required: true }, label: { type: String, default: null } })
const { t } = useI18n()
const copied = ref(false)
const displayLabel = computed(() => props.label ?? t('comment-rating.copy'))

async function copy() {
  try {
    await navigator.clipboard.writeText(props.text)
  } catch {
    // Clipboard API can be unavailable (insecure context / permissions); fall back silently —
    // the text is still visible on the page for manual copy.
  }
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
</script>

<template>
  <button class="copy-btn" :class="{ copied }" type="button" @click="copy">
    {{ copied ? `✓ ${t('comment-rating.copied')}` : displayLabel }}
  </button>
</template>

<style scoped>
.copy-btn {
  font-size: 12.5px;
  font-weight: 600;
  padding: 5px 14px;
  border-radius: 20px;
  border: 1px solid #2c2c2c;
  background: #1c1c1c;
  color: #c9c9c9;
  cursor: pointer;
  transition: all 0.13s;
  white-space: nowrap;
}
.copy-btn:hover {
  border-color: #80cbc4;
  color: #80cbc4;
}
.copy-btn.copied {
  border-color: #5fb88e;
  color: #5fb88e;
  background: rgba(95, 184, 142, 0.1);
}
</style>
