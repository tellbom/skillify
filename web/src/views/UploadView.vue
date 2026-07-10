<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { uploadSkill } from '../lib/api.js'

const { t } = useI18n()
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
    <router-link to="/" class="back-link">{{ t('common.backToSkills') }}</router-link>
    <h2>{{ t('upload.title') }}</h2>
    <p class="hint" v-html="t('upload.description')" />

    <input type="file" accept=".zip" @change="onFileChange" />
    <button type="button" :disabled="!file || uploading" @click="submit">
      {{ uploading ? t('upload.uploading') : t('upload.upload') }}
    </button>

    <div v-if="error" class="result error">
      <strong>{{ t('upload.rejected') }}</strong>
      <pre>{{ error }}</pre>
    </div>

    <div v-if="result" class="result success">
      <strong>{{ t('upload.published') }}</strong> {{ result.namespace }}/{{ result.name }}@{{ result.version }}
      <p><a :href="result.releaseUrl" target="_blank" rel="noopener">{{ t('upload.viewRelease') }}</a></p>
      <p v-if="result.indexError" class="hint">
        {{ t('upload.indexFailedNote', { error: result.indexError }) }}
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
