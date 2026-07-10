<script setup>
import { ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getSkillDetail } from '../lib/api.js'
import { renderMarkdown } from '../lib/markdown.js'
import { formatDateTime } from '../lib/datetime.js'
import CopyButton from '../components/CopyButton.vue'
import CommentSection from '../components/CommentSection.vue'
import RatingWidget from '../components/RatingWidget.vue'

const route = useRoute()
const { t } = useI18n()

const detail = ref(null)
const loading = ref(true)
const error = ref(null)
const readmeHtml = ref('')
const skillMdHtml = ref('')
const activeTab = ref('readme')

async function load() {
  loading.value = true
  error.value = null
  detail.value = null
  try {
    const data = await getSkillDetail(route.params.namespace, route.params.name)
    detail.value = data
    readmeHtml.value = await renderMarkdown(data.readme)
    skillMdHtml.value = await renderMarkdown(data.skillMd)
    activeTab.value = data.readme ? 'readme' : 'skillMd'
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

watch(() => [route.params.namespace, route.params.name], load)
onMounted(load)

function onRated(result) {
  if (detail.value) {
    detail.value.ratingAverage = result.ratingAverage
    detail.value.ratingCount = result.ratingCount
  }
}
</script>

<template>
  <div>
    <router-link to="/" class="back-link">{{ t('common.backToSkills') }}</router-link>

    <p v-if="loading" class="hint">{{ t('common.loading') }}</p>
    <p v-else-if="error" class="error">{{ t('errors.loadFailed', { error }) }}</p>

    <template v-else-if="detail">
      <h2>{{ detail.namespace }}/{{ detail.name }} <span class="version">v{{ detail.version }}</span></h2>
      <p class="description">{{ detail.description }}</p>
      <p class="author">{{ t('skills.publishedBy', { author: detail.author, date: formatDateTime(detail.publishedAt) }) }}</p>

      <div class="tags">
        <span v-for="tag in detail.tags" :key="tag" class="tag">{{ tag }}</span>
      </div>

      <RatingWidget
        :namespace="detail.namespace"
        :name="detail.name"
        :rating-average="detail.ratingAverage"
        :rating-count="detail.ratingCount"
        @rated="onRated"
      />
      <p class="install-count">{{ t('skills.installsReported', { n: detail.installCount }) }}</p>

      <section class="install-box">
        <div class="install-row">
          <code>{{ detail.installCommand }}</code>
          <CopyButton :text="detail.installCommand" :label="t('skills.copyInstallCommand')" />
        </div>
        <div class="install-row">
          <code class="prompt">{{ detail.agentPrompt }}</code>
          <CopyButton :text="detail.agentPrompt" :label="t('skills.copyAgentPrompt')" />
        </div>
        <div class="install-row" v-if="detail.tarballUrl">
          <a :href="detail.tarballUrl">{{ t('skills.downloadTarball') }}</a>
          <a v-if="detail.checksumUrl" :href="detail.checksumUrl">{{ t('skills.checksum') }}</a>
        </div>
      </section>

      <p class="versions">
        {{ t('skills.allVersions') }}
        <span v-for="(v, i) in detail.versions" :key="v">{{ v }}<template v-if="i < detail.versions.length - 1">, </template></span>
      </p>

      <nav class="tabs">
        <button :class="{ active: activeTab === 'readme' }" :disabled="!detail.readme" @click="activeTab = 'readme'">README</button>
        <button :class="{ active: activeTab === 'skillMd' }" :disabled="!detail.skillMd" @click="activeTab = 'skillMd'">SKILL.md</button>
      </nav>

      <article v-if="activeTab === 'readme'" class="markdown-body" v-html="readmeHtml || `<p class='hint'>${t('skills.noReadme')}</p>`" />
      <article v-else class="markdown-body" v-html="skillMdHtml || `<p class='hint'>${t('skills.noSkillMd')}</p>`" />

      <CommentSection :namespace="detail.namespace" :name="detail.name" />
    </template>
  </div>
</template>

<style scoped>
.back-link {
  display: inline-block;
  margin-bottom: 1rem;
  color: #888;
  text-decoration: none;
}
.hint { color: #888; }
.error { color: #e06c75; }
.version { color: #888; font-weight: 400; font-size: 0.9rem; }
.description { color: #ccc; }
.author { color: #888; font-size: 0.85rem; }
.tags { display: flex; gap: 0.4rem; flex-wrap: wrap; margin: 0.5rem 0 1rem; }
.tag { background: #263238; color: #80cbc4; border-radius: 999px; padding: 0.1rem 0.6rem; font-size: 0.75rem; }
.install-count { color: #888; font-size: 0.8rem; margin: 0.3rem 0 1rem; }
.install-box {
  border: 1px solid #333;
  border-radius: 8px;
  padding: 0.8rem 1rem;
  margin-bottom: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.install-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.install-row code {
  background: #1c1c1c;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.85rem;
}
.install-row code.prompt {
  white-space: normal;
}
.versions { color: #888; font-size: 0.85rem; }
.tabs {
  display: flex;
  gap: 0.5rem;
  border-bottom: 1px solid #333;
  margin-bottom: 1rem;
}
.tabs button {
  background: none;
  border: none;
  color: #888;
  padding: 0.5rem 0.2rem;
  cursor: pointer;
  border-bottom: 2px solid transparent;
}
.tabs button.active {
  color: inherit;
  border-bottom-color: #80cbc4;
}
.tabs button:disabled {
  opacity: 0.4;
  cursor: default;
}
.markdown-body :deep(pre) {
  padding: 0.8rem;
  border-radius: 6px;
  overflow-x: auto;
}
</style>
