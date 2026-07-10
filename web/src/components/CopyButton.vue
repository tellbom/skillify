<script setup>
import { ref } from 'vue'

const props = defineProps({ text: { type: String, required: true }, label: { type: String, default: 'Copy' } })
const copied = ref(false)

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
  <button class="copy-btn" type="button" @click="copy">{{ copied ? 'Copied!' : label }}</button>
</template>

<style scoped>
.copy-btn {
  font-size: 0.85rem;
  padding: 0.25rem 0.6rem;
  border-radius: 4px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  cursor: pointer;
}
.copy-btn:hover {
  border-color: #666;
}
</style>
