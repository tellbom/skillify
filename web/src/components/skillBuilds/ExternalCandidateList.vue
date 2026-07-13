<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  candidates: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['confirm'])

const { t } = useI18n()

const selected = ref(new Set())
const localError = ref('')

function toggle(candidateId) {
  if (selected.value.has(candidateId)) {
    selected.value.delete(candidateId)
  } else {
    selected.value.add(candidateId)
  }
  // Force reactivity — Set mutation alone doesn't trigger template updates.
  selected.value = new Set(selected.value)
}

function submit() {
  if (selected.value.size === 0) {
    localError.value = t('upload.external.noneSelected')
    return
  }
  localError.value = ''
  emit('confirm', Array.from(selected.value))
}
</script>

<template>
  <div class="external-candidate-list">
    <p class="heading">{{ t('upload.external.candidatesHeading', { n: candidates.length }) }}</p>

    <div v-for="candidate in candidates" :key="candidate.candidateId" class="candidate-card">
      <label class="candidate-select">
        <input type="checkbox" :checked="selected.has(candidate.candidateId)" @change="toggle(candidate.candidateId)" />
        <span class="candidate-name">{{ candidate.frontmatter?.name || candidate.rootPath }}</span>
      </label>
      <p class="candidate-root">{{ candidate.rootPath }}</p>
      <p class="candidate-description">
        {{ candidate.frontmatter?.description || t('upload.external.candidateNoDescription') }}
      </p>

      <div v-if="candidate.detectedPaths?.length" class="candidate-section">
        <span class="candidate-section-label">{{ t('upload.external.candidateDetectedPaths') }}</span>
        <span class="chip-list">
          <span v-for="path in candidate.detectedPaths" :key="path" class="chip">{{ path }}</span>
        </span>
      </div>

      <div v-if="candidate.pythonRequirements?.length" class="candidate-section">
        <span class="candidate-section-label">{{ t('upload.external.candidatePythonRequirements') }}</span>
        <span class="chip-list">
          <span v-for="req in candidate.pythonRequirements" :key="req" class="chip">{{ req }}</span>
        </span>
      </div>

      <div v-if="candidate.issues?.length" class="candidate-section">
        <span class="candidate-section-label">{{ t('upload.external.candidateIssues') }}</span>
        <ul class="issues-list">
          <li v-for="(issue, index) in candidate.issues" :key="index">{{ issue.path }}: {{ issue.message }}</li>
        </ul>
      </div>
    </div>

    <p v-if="localError" class="error">{{ localError }}</p>
    <button type="button" class="primary-button" :disabled="busy" @click="submit">
      {{ busy ? t('upload.external.converting') : t('upload.external.convert') }}
    </button>
  </div>
</template>

<style scoped>
.external-candidate-list {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
}
.heading {
  margin: 0;
  font-size: 0.9rem;
  color: #ccc;
}
.candidate-card {
  background: #1c1c1c;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 0.8rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.candidate-select {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
}
.candidate-root,
.candidate-description {
  margin: 0;
  font-size: 0.85rem;
  color: #ccc;
}
.candidate-section {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.8rem;
}
.candidate-section-label {
  color: #888;
}
.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}
.chip {
  background: #26343a;
  color: #80cbc4;
  border-radius: 999px;
  padding: 0.1rem 0.6rem;
  font-size: 0.75rem;
}
.issues-list {
  margin: 0;
  padding-left: 1.2rem;
  color: #e06c75;
}
.error {
  color: #e06c75;
  font-size: 0.85rem;
  margin: 0;
}
.primary-button {
  align-self: flex-start;
  background: #26343a;
  color: #80cbc4;
  border: 1px solid #444;
  border-radius: 6px;
  padding: 0.5rem 1rem;
  cursor: pointer;
}
.primary-button:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
