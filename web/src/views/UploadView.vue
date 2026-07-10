<script setup>
import { ref } from 'vue'
import { uploadSkill } from '../lib/api.js'

const file = ref(null)
const uploading = ref(false)
const result = ref(null)
const error = ref(null)

function onFileChange(event) {
  file.value = event.target.files[0] || null
  result.value = null
  error.value = null
}

async function submit() {
  if (!file.value) return
  uploading.value = true
  error.value = null
  result.value = null
  try {
    result.value = await uploadSkill(file.value)
  } catch (err) {
    error.value = err.message
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div>
    <router-link to="/" class="back-link">&larr; back to all skills</router-link>
    <h2>Upload a skill</h2>
    <p class="hint">
      Upload a <code>.zip</code> of your skill directory (must contain <code>SKILL.md</code> and
      <code>skill.yaml</code> at its root, or in a single top-level folder). It's validated against the
      standard format and published as a Forgejo Release — same result as <code>skillctl publish</code>.
    </p>

    <input type="file" accept=".zip" @change="onFileChange" />
    <button type="button" :disabled="!file || uploading" @click="submit">
      {{ uploading ? 'Uploading…' : 'Upload' }}
    </button>

    <div v-if="error" class="result error">
      <strong>Rejected:</strong>
      <pre>{{ error }}</pre>
    </div>

    <div v-if="result" class="result success">
      <strong>Published</strong> {{ result.namespace }}/{{ result.name }}@{{ result.version }}
      <p><a :href="result.releaseUrl" target="_blank" rel="noopener">view release</a></p>
      <p v-if="result.indexError" class="hint">
        Note: search index update failed ({{ result.indexError }}) — the release itself succeeded.
      </p>
    </div>
  </div>
</template>

<style scoped>
.back-link {
  display: inline-block;
  margin-bottom: 1rem;
  color: #888;
  text-decoration: none;
}
.hint {
  color: #888;
  font-size: 0.9rem;
}
input[type='file'] {
  display: block;
  margin: 1rem 0;
}
button {
  padding: 0.5rem 1.2rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  cursor: pointer;
}
button:disabled {
  opacity: 0.5;
  cursor: default;
}
.result {
  margin-top: 1.5rem;
  padding: 1rem;
  border-radius: 8px;
  border: 1px solid #333;
}
.result.error {
  border-color: #a94442;
}
.result pre {
  white-space: pre-wrap;
  color: #e06c75;
}
</style>
