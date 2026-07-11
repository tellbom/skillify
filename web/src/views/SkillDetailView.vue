<script setup>
import { ref, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getSkillDetail, getVersions, getVersionDiff, yankVersion, unyankVersion, starSkill, unstarSkill, subscribeSkill, unsubscribeSkill } from '../lib/api.js'
import { useAuthStore } from '../stores/auth.js'
import { renderMarkdown } from '../lib/markdown.js'
import { formatDateTime } from '../lib/datetime.js'
import { sortVersionsDesc, groupDiff, isDiffEmpty } from '../lib/versions.js'
import { useMenuStore } from '../stores/menu.js'
import CopyButton from '../components/CopyButton.vue'
import CommentSection from '../components/CommentSection.vue'
import RatingWidget from '../components/RatingWidget.vue'

const route = useRoute()
const { t } = useI18n()
const menuStore = useMenuStore()
const auth = useAuthStore()

const detail = ref(null)
const loading = ref(true)
const error = ref(null)
const readmeHtml = ref('')
const skillMdHtml = ref('')
const activeTab = ref('readme')

// Version timeline (C-1): fetched from the yanked-aware /versions endpoint, kept separate
// from SkillDetail.versions (a plain string[] that stays unaware of yank state — see task
// brief). viewedVersion tracks which version's detail is currently displayed above; undefined
// means "server default" (newest non-yanked).
const versions = ref([])
const versionsLoading = ref(true)
const versionsError = ref(null)
const viewedVersion = ref(undefined)

// Yank/unyank in-flight + error state, keyed by version so multiple rows don't fight.
const yankBusy = ref(null)
const yankError = ref(null)

// Diff panel
const diffFrom = ref('')
const diffTo = ref('')
const diffResult = ref(null)
const diffLoading = ref(false)
const diffError = ref(null)

// Star / subscribe (C-5): initial state comes straight off the skill-detail payload
// (starred/starCount/subscribed reflect the CURRENTLY LOGGED-IN user, per Task 6) — no separate
// fetch needed. Both actions are idempotent both directions server-side, so the button just
// toggles and calls the matching verb without checking current state first.
const starBusy = ref(false)
const starError = ref(null)
const subscribeBusy = ref(false)
const subscribeError = ref(null)

async function load() {
  loading.value = true
  error.value = null
  detail.value = null
  try {
    const data = await getSkillDetail(route.params.namespace, route.params.name, viewedVersion.value)
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

async function loadVersions() {
  versionsLoading.value = true
  versionsError.value = null
  try {
    const data = await getVersions(route.params.namespace, route.params.name)
    versions.value = sortVersionsDesc(data)
  } catch (err) {
    versionsError.value = err.message
  } finally {
    versionsLoading.value = false
  }
}

function loadAll() {
  viewedVersion.value = undefined
  diffResult.value = null
  diffError.value = null
  load()
  loadVersions()
}

watch(() => [route.params.namespace, route.params.name], loadAll)
onMounted(loadAll)

function onRated(result) {
  if (detail.value) {
    detail.value.ratingAverage = result.ratingAverage
    detail.value.ratingCount = result.ratingCount
  }
}

function viewVersion(version) {
  viewedVersion.value = version
  load()
}

async function toggleYank(v) {
  yankBusy.value = v.version
  yankError.value = null
  try {
    const action = v.yanked ? unyankVersion : yankVersion
    const result = await action(route.params.namespace, route.params.name, v.version)
    v.yanked = result.yanked
  } catch (err) {
    yankError.value = err.message
  } finally {
    yankBusy.value = null
  }
}

async function runDiff() {
  if (!diffFrom.value || !diffTo.value) return
  diffLoading.value = true
  diffError.value = null
  diffResult.value = null
  try {
    const data = await getVersionDiff(route.params.namespace, route.params.name, diffFrom.value, diffTo.value)
    diffResult.value = groupDiff(data)
  } catch (err) {
    diffError.value = err.message
  } finally {
    diffLoading.value = false
  }
}

async function toggleStar() {
  if (!detail.value) return
  starBusy.value = true
  starError.value = null
  try {
    const action = detail.value.starred ? unstarSkill : starSkill
    const result = await action(route.params.namespace, route.params.name)
    detail.value.starred = result.starred
    detail.value.starCount = result.starCount
  } catch (err) {
    starError.value = err.message
  } finally {
    starBusy.value = false
  }
}

async function toggleSubscribe() {
  if (!detail.value) return
  subscribeBusy.value = true
  subscribeError.value = null
  try {
    const action = detail.value.subscribed ? unsubscribeSkill : subscribeSkill
    const result = await action(route.params.namespace, route.params.name)
    detail.value.subscribed = result.subscribed
  } catch (err) {
    subscribeError.value = err.message
  } finally {
    subscribeBusy.value = false
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

      <div class="community-actions">
        <button
          type="button"
          class="star-button"
          :class="{ active: detail.starred }"
          :disabled="!auth.isAuthenticated || starBusy"
          :title="auth.isAuthenticated ? '' : t('community.loginToUse')"
          @click="toggleStar"
        >
          {{ detail.starred ? '★' : '☆' }} {{ detail.starred ? t('community.starred') : t('community.star') }}
          <span class="star-count">({{ detail.starCount }})</span>
        </button>
        <button
          type="button"
          class="subscribe-button"
          :class="{ active: detail.subscribed }"
          :disabled="!auth.isAuthenticated || subscribeBusy"
          :title="auth.isAuthenticated ? '' : t('community.loginToUse')"
          @click="toggleSubscribe"
        >
          {{ detail.subscribed ? t('community.subscribed') : t('community.subscribe') }}
        </button>
      </div>
      <p v-if="starError" class="error">{{ starError }}</p>
      <p v-if="subscribeError" class="error">{{ subscribeError }}</p>

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

      <section class="version-timeline">
        <h3>{{ t('versions.title') }}</h3>
        <p v-if="versionsLoading" class="hint">{{ t('versions.loading') }}</p>
        <p v-else-if="versionsError" class="error">{{ t('errors.loadFailed', { error: versionsError }) }}</p>
        <ul v-else class="version-list">
          <li
            v-for="v in versions"
            :key="v.version"
            class="version-entry"
            :class="{ current: (viewedVersion || detail.version) === v.version, yanked: v.yanked }"
          >
            <div class="version-entry-header">
              <span class="version-entry-num">v{{ v.version }}</span>
              <span class="version-entry-date">{{ t('versions.publishedAt', { date: formatDateTime(v.publishedAt) }) }}</span>
              <span v-if="v.yanked" class="badge-yanked">{{ t('versions.yanked') }}</span>
            </div>
            <p class="version-entry-notes">{{ v.releaseNotes || t('versions.noReleaseNotes') }}</p>
            <div class="version-entry-actions">
              <button
                type="button"
                :disabled="(viewedVersion || detail.version) === v.version"
                @click="viewVersion(v.version)"
              >
                {{ (viewedVersion || detail.version) === v.version ? t('versions.currentlyViewing') : t('versions.viewThisVersion') }}
              </button>
              <button
                v-if="menuStore.can('skillify:yank')"
                type="button"
                class="yank-button"
                :disabled="yankBusy === v.version"
                @click="toggleYank(v)"
              >
                {{ yankBusy === v.version ? t('versions.yanking') : (v.yanked ? t('versions.unyank') : t('versions.yank')) }}
              </button>
            </div>
          </li>
        </ul>
        <p v-if="yankError" class="error">{{ t('versions.yankFailed', { error: yankError }) }}</p>
      </section>

      <section class="version-diff">
        <h3>{{ t('versions.compare') }}</h3>
        <div class="diff-controls">
          <label>
            {{ t('versions.compareFrom') }}
            <select v-model="diffFrom">
              <option value="" disabled>—</option>
              <option v-for="v in versions" :key="v.version" :value="v.version">v{{ v.version }}</option>
            </select>
          </label>
          <label>
            {{ t('versions.compareTo') }}
            <select v-model="diffTo">
              <option value="" disabled>—</option>
              <option v-for="v in versions" :key="v.version" :value="v.version">v{{ v.version }}</option>
            </select>
          </label>
          <button type="button" :disabled="!diffFrom || !diffTo || diffLoading" @click="runDiff">
            {{ t('versions.runDiff') }}
          </button>
        </div>

        <p v-if="diffLoading" class="hint">{{ t('versions.diffLoading') }}</p>
        <p v-else-if="diffError" class="error">{{ t('versions.diffFailed', { error: diffError }) }}</p>
        <p v-else-if="!diffResult" class="hint">{{ t('versions.noDiffYet') }}</p>
        <p v-else-if="isDiffEmpty(diffResult)" class="hint">{{ t('versions.noChanges') }}</p>
        <div v-else class="diff-groups">
          <div class="diff-group">
            <h4>{{ t('versions.added') }} ({{ diffResult.added.length }})</h4>
            <ul><li v-for="f in diffResult.added" :key="f">{{ f }}</li></ul>
          </div>
          <div class="diff-group">
            <h4>{{ t('versions.removed') }} ({{ diffResult.removed.length }})</h4>
            <ul><li v-for="f in diffResult.removed" :key="f">{{ f }}</li></ul>
          </div>
          <div class="diff-group">
            <h4>{{ t('versions.modified') }} ({{ diffResult.modified.length }})</h4>
            <ul><li v-for="f in diffResult.modified" :key="f">{{ f }}</li></ul>
          </div>
        </div>
      </section>

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
.community-actions {
  display: flex;
  gap: 0.6rem;
  margin-bottom: 0.8rem;
}
.star-button, .subscribe-button {
  padding: 0.35rem 0.8rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  cursor: pointer;
  font-size: 0.85rem;
}
.star-button.active {
  border-color: #ffca28;
  color: #ffca28;
}
.subscribe-button.active {
  border-color: #80cbc4;
  color: #80cbc4;
}
.star-button:disabled, .subscribe-button:disabled {
  opacity: 0.5;
  cursor: default;
}
.star-count {
  color: #888;
  font-size: 0.8rem;
}
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
.version-timeline, .version-diff {
  margin-bottom: 1.5rem;
}
.version-timeline h3, .version-diff h3 {
  margin-bottom: 0.6rem;
  font-size: 1rem;
}
.version-list {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.version-entry {
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  padding: 0.6rem 0.8rem;
}
.version-entry.current {
  border-color: #80cbc4;
}
.version-entry.yanked {
  opacity: 0.7;
}
.version-entry-header {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.version-entry-num {
  font-weight: 600;
}
.version-entry-date {
  color: #888;
  font-size: 0.8rem;
}
.badge-yanked {
  background: #4a1f1f;
  color: #e06c75;
  border-radius: 999px;
  padding: 0.1rem 0.6rem;
  font-size: 0.75rem;
}
.version-entry-notes {
  color: #ccc;
  font-size: 0.85rem;
  margin: 0.3rem 0;
}
.version-entry-actions {
  display: flex;
  gap: 0.5rem;
}
.version-entry-actions button {
  padding: 0.3rem 0.7rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  cursor: pointer;
  font-size: 0.8rem;
}
.version-entry-actions button:disabled {
  opacity: 0.5;
  cursor: default;
}
.yank-button {
  border-color: #e06c75 !important;
  color: #e06c75;
}
.diff-controls {
  display: flex;
  align-items: flex-end;
  gap: 1rem;
  flex-wrap: wrap;
  margin-bottom: 0.8rem;
}
.diff-controls label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.8rem;
  color: #888;
}
.diff-controls select {
  background: #1c1c1c;
  color: inherit;
  border: 1px solid #444;
  border-radius: 6px;
  padding: 0.3rem 0.5rem;
}
.diff-controls button {
  padding: 0.4rem 1rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  cursor: pointer;
}
.diff-controls button:disabled {
  opacity: 0.5;
  cursor: default;
}
.diff-groups {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}
.diff-group {
  flex: 1;
  min-width: 200px;
}
.diff-group h4 {
  margin: 0 0 0.4rem;
  font-size: 0.85rem;
  color: #888;
}
.diff-group ul {
  list-style: none;
  padding: 0;
  margin: 0;
  font-size: 0.8rem;
  font-family: monospace;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
</style>
