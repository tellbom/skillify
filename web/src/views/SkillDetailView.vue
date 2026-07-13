<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getSkillDetail, getVersions, getVersionDiff, yankVersion, unyankVersion, starSkill, unstarSkill, subscribeSkill, unsubscribeSkill } from '../lib/api.js'
import { useAuthStore } from '../stores/auth.js'
import { renderMarkdown } from '../lib/markdown.js'
import { formatDateTime } from '../lib/datetime.js'
import { formatCount } from '../lib/format.js'
import { extractHeadings, injectHeadingIds } from '../lib/toc.js'
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

// Which version (if any) is showing its inline "confirm recall?" prompt.
const confirmingVersion = ref(null)

const latestVersion = computed(() => versions.value[0]?.version)
const viewingVersion = computed(() => viewedVersion.value || latestVersion.value)
const viewingVersionEntry = computed(() => versions.value.find((v) => v.version === viewingVersion.value) || null)
const viewingLatest = computed(() => viewingVersion.value === latestVersion.value)
const viewingRecalled = computed(() => Boolean(viewingVersionEntry.value?.yanked))

const tocSource = computed(() => (activeTab.value === 'readme' ? detail.value?.readme : detail.value?.skillMd))
const tocHeadings = computed(() => extractHeadings(tocSource.value))
const showToc = computed(() => tocHeadings.value.length > 1)
const docEmpty = computed(() => !(activeTab.value === 'readme' ? detail.value?.readme : detail.value?.skillMd))
const docHtml = computed(() => injectHeadingIds(activeTab.value === 'readme' ? readmeHtml.value : skillMdHtml.value, tocHeadings.value))

const compareState = computed(() => {
  if (diffLoading.value) return 'loading'
  if (diffError.value) return 'error'
  if (!diffResult.value) return 'idle'
  if (isDiffEmpty(diffResult.value)) return 'noChange'
  return 'done'
})
const compareGroups = computed(() => {
  if (!diffResult.value) return []
  return [
    { key: 'added', label: t('versions.added'), color: '#5FB88E', sign: '+', files: diffResult.value.added },
    { key: 'removed', label: t('versions.removed'), color: '#E5807A', sign: '−', files: diffResult.value.removed },
    { key: 'modified', label: t('versions.modified'), color: '#E0A458', sign: '~', files: diffResult.value.modified },
  ].filter((g) => g.files.length > 0)
})

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

function askRecall(version) {
  confirmingVersion.value = version
}

function cancelRecall() {
  confirmingVersion.value = null
}

async function confirmRecall(v) {
  confirmingVersion.value = null
  await toggleYank(v)
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
  <div class="detail-page">
    <router-link to="/" class="back-link">{{ t('common.backToSkills') }}</router-link>

    <div v-if="loading" class="state-hint">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="state-box state-error">
      <div class="state-title">{{ t('errors.loadFailed', { error }) }}</div>
      <button type="button" class="state-action" @click="loadAll">{{ t('common.retry') }}</button>
    </div>

    <template v-else-if="detail">
      <div v-if="viewingRecalled" class="recalled-banner">
        <span class="banner-icon">⚠</span>
        <div class="banner-text">
          您正在查看的版本 <strong>v{{ viewingVersion }}</strong> 已被撤回，不建议在生产环境中安装。
        </div>
      </div>

      <div class="detail-header">
        <div class="header-top">
          <h1 class="skill-name">{{ detail.namespace }}/{{ detail.name }}</h1>
          <span class="version-badge">v{{ viewingVersion }}</span>
          <span v-if="viewingLatest" class="tag-badge tag-badge-teal">{{ t('versions.latestBadge') }}</span>
          <span v-else class="tag-badge tag-badge-gold">{{ t('versions.viewingHistorical', { version: latestVersion }) }}</span>
        </div>
        <p class="skill-desc">{{ detail.description }}</p>
        <div class="header-meta">
          <span>{{ t('skills.publishedBy', { author: detail.author, date: formatDateTime(detail.publishedAt) }) }}</span>
          <span class="meta-dot">·</span>
          <span class="meta-rating">
            ★ {{ detail.ratingAverage !== null ? detail.ratingAverage.toFixed(1) : t('comment-rating.unrated') }}
            <span class="meta-muted">({{ detail.ratingCount }} 人评分)</span>
          </span>
          <span class="meta-dot">·</span>
          <span>↓ {{ formatCount(detail.installCount) }} 安装</span>
        </div>
        <div class="header-tags">
          <span v-for="tag in detail.tags" :key="tag" class="skill-tag">{{ tag }}</span>
        </div>
      </div>

      <div class="detail-cols">
        <div class="main-col">
          <!-- Install panel -->
          <section class="install-panel">
            <div class="panel-head">
              <span class="panel-dot"></span>
              <h3>安装</h3>
            </div>
            <div class="field-label">skillctl 安装命令</div>
            <div class="code-row">
              <div class="code-box"><code>{{ detail.installCommand }}</code></div>
              <CopyButton :text="detail.installCommand" :label="t('skills.copyInstallCommand')" />
            </div>
            <div class="field-label">Agent 提示词</div>
            <div class="code-box code-box-wrap">
              <code>{{ detail.agentPrompt }}</code>
            </div>
            <div class="install-actions">
              <CopyButton :text="detail.agentPrompt" :label="t('skills.copyAgentPrompt')" />
              <a v-if="detail.tarballUrl" :href="detail.tarballUrl" class="link-action">↓ {{ t('skills.downloadTarball') }}</a>
              <span v-if="detail.tarballUrl && detail.checksumUrl" class="divider-inline">|</span>
              <a v-if="detail.checksumUrl" :href="detail.checksumUrl" class="link-action muted">{{ t('skills.checksum') }}</a>
            </div>
          </section>

          <!-- Docs tabs -->
          <section class="docs-section">
            <div class="docs-tabs">
              <button type="button" class="tab-btn" :class="{ active: activeTab === 'readme' }" :disabled="!detail.readme" @click="activeTab = 'readme'">README</button>
              <button type="button" class="tab-btn" :class="{ active: activeTab === 'skillMd' }" :disabled="!detail.skillMd" @click="activeTab = 'skillMd'">SKILL.md</button>
              <span class="docs-format">Markdown</span>
            </div>
            <div class="docs-body">
              <div class="docs-main">
                <div v-if="!docEmpty" class="md-body" v-html="docHtml"></div>
                <div v-else class="doc-empty">{{ activeTab === 'readme' ? t('skills.noReadme') : t('skills.noSkillMd') }}</div>
              </div>
              <aside v-if="showToc" class="toc-sidebar">
                <div class="toc-label">目录</div>
                <nav class="toc-list">
                  <a v-for="h in tocHeadings" :key="h.id" :href="`#${h.id}`" class="toc-link" :class="`toc-level-${h.level}`">{{ h.text }}</a>
                </nav>
              </aside>
            </div>
          </section>

          <!-- Version history -->
          <section class="version-section">
            <h2 class="section-title">{{ t('versions.title') }}</h2>
            <div v-if="versionsLoading" class="state-hint">{{ t('versions.loading') }}</div>
            <div v-else-if="versionsError" class="state-hint state-error-text">{{ t('errors.loadFailed', { error: versionsError }) }}</div>
            <ul v-else class="version-list">
              <li v-for="(v, idx) in versions" :key="v.version" class="version-row">
                <div class="version-rail">
                  <span class="version-dot" :class="v.yanked ? 'dot-recalled' : idx === 0 ? 'dot-latest' : 'dot-plain'"></span>
                  <span v-if="idx < versions.length - 1" class="version-line"></span>
                </div>
                <div class="version-card" :class="{ 'is-viewing': viewingVersion === v.version }">
                  <div class="version-card-head">
                    <span class="version-num">v{{ v.version }}</span>
                    <span class="version-date">{{ formatDateTime(v.publishedAt) }}</span>
                    <span v-if="viewingVersion === v.version" class="pill pill-teal">{{ t('versions.currentlyViewing') }}</span>
                    <span v-if="idx === 0" class="pill pill-outline">{{ t('versions.latestBadge') }}</span>
                    <span v-if="v.yanked" class="pill pill-danger">{{ t('versions.yanked') }}</span>
                  </div>
                  <p class="version-notes">{{ v.releaseNotes || t('versions.noReleaseNotes') }}</p>
                  <div class="version-actions">
                    <button v-if="viewingVersion !== v.version" type="button" class="btn-ghost" @click="viewVersion(v.version)">{{ t('versions.viewThisVersion') }}</button>
                    <template v-if="menuStore.can('skillify:yank')">
                      <button
                        v-if="!v.yanked && confirmingVersion !== v.version"
                        type="button"
                        class="btn-danger-outline"
                        @click="askRecall(v.version)"
                      >
                        {{ t('versions.yank') }}
                      </button>
                      <button
                        v-if="v.yanked"
                        type="button"
                        class="btn-teal-outline"
                        :disabled="yankBusy === v.version"
                        @click="toggleYank(v)"
                      >
                        {{ yankBusy === v.version ? t('versions.yanking') : t('versions.unyank') }}
                      </button>
                      <template v-if="confirmingVersion === v.version">
                        <span class="confirm-text">{{ t('versions.confirmRecallPrompt') }}</span>
                        <button type="button" class="btn-danger-solid" :disabled="yankBusy === v.version" @click="confirmRecall(v)">
                          {{ yankBusy === v.version ? t('versions.yanking') : t('versions.confirmYes') }}
                        </button>
                        <button type="button" class="btn-ghost" @click="cancelRecall">{{ t('versions.confirmNo') }}</button>
                      </template>
                    </template>
                  </div>
                </div>
              </li>
            </ul>
            <p v-if="yankError" class="state-error-text">{{ t('versions.yankFailed', { error: yankError }) }}</p>
          </section>

          <!-- Version compare -->
          <section class="compare-section">
            <h2 class="section-title">{{ t('versions.compare') }}</h2>
            <div class="compare-controls">
              <div class="compare-field">
                <div class="compare-label">{{ t('versions.compareFrom') }}</div>
                <select v-model="diffFrom" class="cmp-select">
                  <option value="" disabled>—</option>
                  <option v-for="v in versions" :key="v.version" :value="v.version">v{{ v.version }}</option>
                </select>
              </div>
              <div class="compare-arrow">→</div>
              <div class="compare-field">
                <div class="compare-label">{{ t('versions.compareTo') }}</div>
                <select v-model="diffTo" class="cmp-select">
                  <option value="" disabled>—</option>
                  <option v-for="v in versions" :key="v.version" :value="v.version">v{{ v.version }}</option>
                </select>
              </div>
              <button type="button" class="compare-btn" :disabled="!diffFrom || !diffTo || diffLoading" @click="runDiff">
                {{ t('versions.runDiff') }}
              </button>
            </div>

            <div v-if="compareState === 'idle'" class="state-hint">{{ t('versions.noDiffYet') }}</div>
            <div v-else-if="compareState === 'loading'" class="state-hint state-hint-row">
              <span class="spinner"></span>{{ t('versions.diffLoading') }}
            </div>
            <div v-else-if="compareState === 'error'" class="compare-error">
              <span>{{ t('versions.diffFailed', { error: diffError }) }}</span>
              <button type="button" class="state-action state-action-outline" @click="runDiff">{{ t('common.retry') }}</button>
            </div>
            <div v-else-if="compareState === 'noChange'" class="state-box state-dashed">{{ t('versions.noChanges') }}</div>
            <div v-else class="compare-groups">
              <div v-for="g in compareGroups" :key="g.key" class="compare-group">
                <div class="compare-group-head">
                  <span class="compare-group-dot" :style="{ background: g.color }"></span>
                  <span class="compare-group-label">{{ g.label }}</span>
                  <span class="compare-group-count">{{ g.files.length }} 个文件</span>
                </div>
                <div class="compare-group-files">
                  <div v-for="f in g.files" :key="f" class="compare-file">
                    <span class="compare-file-sign" :style="{ color: g.color }">{{ g.sign }}</span>{{ f }}
                  </div>
                </div>
              </div>
            </div>
          </section>

          <CommentSection :namespace="detail.namespace" :name="detail.name" />
        </div>

        <aside class="sidebar">
          <div class="sidebar-sticky">
            <div class="side-card">
              <button
                type="button"
                class="solid-btn"
                :class="{ active: detail.starred }"
                :disabled="!auth.isAuthenticated || starBusy"
                :title="auth.isAuthenticated ? '' : t('community.loginToUse')"
                @click="toggleStar"
              >
                {{ starBusy ? t('community.starring') : (detail.starred ? t('community.starred') : t('community.star')) }} ({{ detail.starCount }})
              </button>
              <button
                type="button"
                class="solid-btn"
                :class="{ active: detail.subscribed }"
                :disabled="!auth.isAuthenticated || subscribeBusy"
                :title="auth.isAuthenticated ? '' : t('community.loginToUse')"
                @click="toggleSubscribe"
              >
                {{ subscribeBusy ? t('community.subscribing') : (detail.subscribed ? t('community.subscribed') : t('community.subscribe')) }}
              </button>
              <p v-if="starError" class="state-error-text">{{ starError }}</p>
              <p v-if="subscribeError" class="state-error-text">{{ subscribeError }}</p>

              <div class="side-divider"></div>

              <div class="side-label">我的评分</div>
              <RatingWidget
                :namespace="detail.namespace"
                :name="detail.name"
                :rating-average="detail.ratingAverage"
                :rating-count="detail.ratingCount"
                @rated="onRated"
              />
            </div>

            <div class="side-card">
              <div class="side-label">统计</div>
              <div class="stat-row">
                <span class="stat-key">安装量</span>
                <span class="stat-value">{{ formatCount(detail.installCount) }}</span>
              </div>
              <div class="stat-row">
                <span class="stat-key">平均评分</span>
                <span class="stat-value stat-value-gold">
                  ★ {{ detail.ratingAverage !== null ? detail.ratingAverage.toFixed(1) : t('comment-rating.unrated') }}
                  <span class="meta-muted">({{ detail.ratingCount }})</span>
                </span>
              </div>
              <div class="stat-row">
                <span class="stat-key">收藏量</span>
                <span class="stat-value">{{ formatCount(detail.starCount) }}</span>
              </div>
            </div>

            <div class="side-card">
              <div class="side-label">信息</div>
              <div class="meta-row"><span class="meta-key">命名空间</span><span class="meta-value-mono">{{ detail.namespace }}</span></div>
              <div class="meta-row"><span class="meta-key">当前查看</span><span class="meta-value-mono meta-value-teal">{{ viewingVersion }}</span></div>
              <div class="meta-row"><span class="meta-key">最新版本</span><span class="meta-value-mono">{{ latestVersion }}</span></div>
              <div class="meta-row"><span class="meta-key">全部版本</span><span class="meta-value">{{ versions.length }} 个</span></div>
              <div class="meta-row"><span class="meta-key">作者</span><span class="meta-value">{{ detail.author }}</span></div>
            </div>
          </div>
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.detail-page {
  padding: 4px 0 60px;
}
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #9f9f9f;
  text-decoration: none;
  margin-bottom: 20px;
}
.back-link:hover {
  color: #80cbc4;
}

.state-hint {
  color: #9f9f9f;
  font-size: 13.5px;
  padding: 8px 0;
}
.state-hint-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.state-error-text {
  color: #e5807a;
  font-size: 13px;
}
.state-box {
  border-radius: 12px;
  padding: 40px 24px;
  text-align: center;
}
.state-box.state-error {
  border: 1px solid #3a2a2a;
  background: rgba(229, 128, 122, 0.05);
}
.state-box.state-dashed {
  border: 1px dashed #2c2c2c;
  padding: 24px;
  color: #9f9f9f;
  font-size: 13px;
  text-align: center;
}
.state-title {
  font-size: 14px;
  color: #edb4b0;
  margin-bottom: 16px;
}
.state-action {
  padding: 8px 20px;
  background: #80cbc4;
  color: #0f1615;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}
.state-action.state-action-outline {
  background: #232323;
  color: #e5e5e5;
  border: 1px solid #2c2c2c;
  font-weight: normal;
}

/* Recalled banner */
.recalled-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: rgba(229, 128, 122, 0.08);
  border: 1px solid rgba(229, 128, 122, 0.32);
  border-radius: 10px;
  margin-bottom: 18px;
}
.banner-icon {
  font-size: 16px;
}
.banner-text {
  font-size: 13px;
  color: #edb4b0;
}

/* Header */
.detail-header {
  margin-bottom: 14px;
}
.header-top {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.skill-name {
  font-size: 26px;
  font-weight: 700;
  margin: 0;
  letter-spacing: -0.4px;
  color: #f2f2f2;
}
.version-badge {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 13px;
  color: #80cbc4;
  background: rgba(128, 203, 196, 0.1);
  border: 1px solid rgba(128, 203, 196, 0.28);
  padding: 2px 9px;
  border-radius: 6px;
}
.tag-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
}
.tag-badge-teal {
  color: #8fb8b3;
  background: rgba(128, 203, 196, 0.06);
  border: 1px solid rgba(128, 203, 196, 0.2);
}
.tag-badge-gold {
  color: #e0a458;
  background: rgba(224, 164, 88, 0.08);
  border: 1px solid rgba(224, 164, 88, 0.28);
}
.skill-desc {
  font-size: 15px;
  color: #c4c4c4;
  margin: 0 0 10px;
  line-height: 1.55;
}
.header-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: #9f9f9f;
}
.meta-dot {
  color: #3a3a3a;
}
.meta-rating {
  color: #e0a458;
}
.meta-muted {
  color: #6e6e6e;
}
.header-tags {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.skill-tag {
  font-size: 11.5px;
  color: #8fb8b3;
  background: rgba(128, 203, 196, 0.08);
  border: 1px solid rgba(128, 203, 196, 0.18);
  padding: 3px 10px;
  border-radius: 20px;
}

/* Two-column layout */
.detail-cols {
  display: flex;
  gap: 32px;
  align-items: flex-start;
}
.main-col {
  min-width: 0;
  flex: 1;
}
.sidebar {
  width: 312px;
  flex: none;
}
.sidebar-sticky {
  position: sticky;
  top: 76px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* Install panel */
.install-panel {
  border: 1px solid #2c2c2c;
  background: linear-gradient(180deg, #1d1f1e, #1a1a1a);
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 22px;
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.panel-head h3 {
  font-size: 14px;
  font-weight: 650;
  margin: 0;
  color: #ededed;
}
.panel-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #80cbc4;
}
.field-label {
  font-size: 12px;
  color: #9f9f9f;
  margin-bottom: 6px;
}
.code-row {
  display: flex;
  gap: 8px;
  align-items: stretch;
  margin-bottom: 16px;
}
.code-box {
  flex: 1;
  min-width: 0;
  background: #141414;
  border: 1px solid #2c2c2c;
  border-radius: 8px;
  padding: 11px 14px;
  overflow-x: auto;
}
.code-box code {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 13px;
  color: #cfe9e5;
  white-space: pre;
}
.code-box-wrap {
  margin-bottom: 10px;
  max-height: 132px;
  overflow-y: auto;
}
.code-box-wrap code {
  font-size: 12px;
  color: #b4b4b4;
  white-space: pre-wrap;
  line-height: 1.6;
}
.install-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.link-action {
  font-size: 12.5px;
  color: #80cbc4;
  text-decoration: none;
  white-space: nowrap;
}
.link-action:hover {
  color: #a7dbd5;
}
.link-action.muted {
  color: #9f9f9f;
}
.link-action.muted:hover {
  color: #c9c9c9;
}
.divider-inline {
  color: #2c2c2c;
}

/* Docs tabs */
.docs-section {
  margin-bottom: 28px;
}
.docs-tabs {
  display: flex;
  align-items: center;
  gap: 2px;
  border-bottom: 1px solid #2c2c2c;
  margin-bottom: 4px;
}
.tab-btn {
  padding: 9px 16px;
  font-size: 13.5px;
  font-weight: 600;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: #9f9f9f;
  cursor: pointer;
  margin-bottom: -1px;
}
.tab-btn.active {
  color: #f0f0f0;
  border-bottom-color: #80cbc4;
}
.tab-btn:disabled {
  opacity: 0.4;
  cursor: default;
}
.docs-format {
  margin-left: auto;
  font-size: 11.5px;
  color: #6e6e6e;
  padding-right: 2px;
}
.docs-body {
  display: flex;
  gap: 28px;
  align-items: flex-start;
  padding-top: 20px;
}
.docs-main {
  flex: 1;
  min-width: 0;
}
.doc-empty {
  border: 1px dashed #2c2c2c;
  border-radius: 10px;
  padding: 48px 20px;
  text-align: center;
  color: #6e6e6e;
  font-size: 13.5px;
}
.toc-sidebar {
  width: 180px;
  flex: none;
  position: sticky;
  top: 76px;
  align-self: flex-start;
}
.toc-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: #6e6e6e;
  margin-bottom: 10px;
}
.toc-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-left: 1px solid #2c2c2c;
}
.toc-link {
  font-size: 12px;
  color: #9f9f9f;
  padding: 3px 0 3px 12px;
  text-decoration: none;
  line-height: 1.4;
}
.toc-link.toc-level-3 {
  padding-left: 24px;
}
.toc-link:hover {
  color: #80cbc4;
}

/* md-body markdown rendering */
.md-body {
  color: #d7d7d7;
  font-size: 14.5px;
  line-height: 1.72;
}
.md-body :deep(> *:first-child) {
  margin-top: 0;
}
.md-body :deep(h1) {
  font-size: 24px;
  margin: 30px 0 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid #2c2c2c;
  color: #f0f0f0;
  font-weight: 650;
  scroll-margin-top: 76px;
}
.md-body :deep(h2) {
  font-size: 19px;
  margin: 28px 0 12px;
  padding-bottom: 7px;
  border-bottom: 1px solid #242424;
  color: #ededed;
  font-weight: 650;
  scroll-margin-top: 76px;
}
.md-body :deep(h3) {
  font-size: 16px;
  margin: 22px 0 8px;
  color: #eaeaea;
  font-weight: 640;
  scroll-margin-top: 76px;
}
.md-body :deep(p) {
  margin: 12px 0;
}
.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 12px 0;
  padding-left: 24px;
}
.md-body :deep(li) {
  margin: 5px 0;
}
.md-body :deep(li::marker) {
  color: #80cbc4;
}
.md-body :deep(a) {
  color: #80cbc4;
  text-decoration: underline;
  text-underline-offset: 2px;
  text-decoration-color: rgba(128, 203, 196, 0.4);
}
.md-body :deep(code) {
  font-family: ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.8px;
  background: #202020;
  border: 1px solid #2c2c2c;
  border-radius: 4px;
  padding: 1.5px 5px;
  color: #e0b58a;
}
.md-body :deep(pre) {
  background: #171717;
  border: 1px solid #2c2c2c;
  border-radius: 8px;
  padding: 14px 16px;
  overflow-x: auto;
  margin: 14px 0;
}
.md-body :deep(pre code) {
  background: none;
  border: none;
  padding: 0;
  color: #cfcfcf;
  font-size: 13px;
  line-height: 1.6;
}
.md-body :deep(blockquote) {
  margin: 14px 0;
  padding: 4px 16px;
  border-left: 3px solid #80cbc4;
  background: rgba(128, 203, 196, 0.06);
  color: #b9b9b9;
  border-radius: 0 6px 6px 0;
}
.md-body :deep(blockquote p) {
  margin: 8px 0;
}
.md-body :deep(table) {
  border-collapse: collapse;
  margin: 16px 0;
  width: 100%;
  font-size: 13.5px;
}
.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid #2c2c2c;
  padding: 8px 12px;
  text-align: left;
}
.md-body :deep(th) {
  background: #1c1c1c;
  color: #ededed;
  font-weight: 600;
}
.md-body :deep(tr:nth-child(even) td) {
  background: rgba(255, 255, 255, 0.015);
}
.md-body :deep(hr) {
  border: none;
  border-top: 1px solid #2c2c2c;
  margin: 24px 0;
}

/* Section titles */
.section-title {
  font-size: 16px;
  font-weight: 650;
  margin: 0 0 16px;
  color: #ededed;
}
.version-section,
.compare-section {
  margin-bottom: 28px;
}

/* Version history */
.version-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
}
.version-row {
  display: flex;
  gap: 16px;
}
.version-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: none;
  width: 14px;
}
.version-dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  border: 2px solid #121212;
  margin-top: 5px;
}
.version-dot.dot-latest {
  background: #80cbc4;
}
.version-dot.dot-plain {
  background: #3a3a3a;
}
.version-dot.dot-recalled {
  background: #e5807a;
}
.version-line {
  width: 1px;
  flex: 1;
  background: #2c2c2c;
  margin: 3px 0;
}
.version-card {
  flex: 1;
  min-width: 0;
  border: 1px solid #2c2c2c;
  background: #1a1a1a;
  border-radius: 10px;
  padding: 13px 16px;
  margin-bottom: 12px;
}
.version-card.is-viewing {
  border-color: rgba(128, 203, 196, 0.35);
  background: rgba(128, 203, 196, 0.04);
}
.version-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.version-num {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 14px;
  font-weight: 650;
  color: #e5e5e5;
}
.version-date {
  font-size: 12px;
  color: #6e6e6e;
}
.pill {
  font-size: 10.5px;
  padding: 1px 7px;
  border-radius: 5px;
}
.pill-teal {
  color: #80cbc4;
  background: rgba(128, 203, 196, 0.1);
  border: 1px solid rgba(128, 203, 196, 0.28);
}
.pill-outline {
  color: #8fb8b3;
  border: 1px solid rgba(128, 203, 196, 0.18);
}
.pill-danger {
  color: #e5807a;
  background: rgba(229, 128, 122, 0.1);
  border: 1px solid rgba(229, 128, 122, 0.3);
}
.version-notes {
  font-size: 13px;
  color: #a9a9a9;
  line-height: 1.55;
  margin: 0 0 12px;
}
.version-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.btn-ghost {
  font-size: 12px;
  color: #c9c9c9;
  background: #232323;
  border: 1px solid #2c2c2c;
  padding: 5px 11px;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
}
.btn-ghost:hover {
  border-color: #80cbc4;
  color: #80cbc4;
}
.btn-danger-outline {
  font-size: 12px;
  color: #e5807a;
  background: transparent;
  border: 1px solid rgba(229, 128, 122, 0.3);
  padding: 5px 11px;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
}
.btn-danger-outline:hover {
  background: rgba(229, 128, 122, 0.1);
}
.btn-teal-outline {
  font-size: 12px;
  color: #80cbc4;
  background: transparent;
  border: 1px solid rgba(128, 203, 196, 0.3);
  padding: 5px 11px;
  border-radius: 6px;
  cursor: pointer;
}
.btn-teal-outline:hover {
  background: rgba(128, 203, 196, 0.1);
}
.btn-teal-outline:disabled,
.btn-danger-solid:disabled {
  opacity: 0.5;
  cursor: default;
}
.confirm-text {
  font-size: 12px;
  color: #e5807a;
}
.btn-danger-solid {
  font-size: 12px;
  color: #0f1615;
  background: #e5807a;
  border: none;
  padding: 5px 11px;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
}

/* Version compare */
.compare-controls {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.compare-label {
  font-size: 11.5px;
  color: #9f9f9f;
  margin-bottom: 5px;
}
.compare-arrow {
  align-self: flex-end;
  padding-bottom: 9px;
  color: #6e6e6e;
}
.cmp-select {
  height: 38px;
  background: #1c1c1c;
  border: 1px solid #2c2c2c;
  border-radius: 8px;
  padding: 0 30px 0 12px;
  color: #e5e5e5;
  font-size: 13px;
  outline: none;
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%239F9F9F' stroke-width='1.5' fill='none'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 11px center;
}
.compare-btn {
  height: 38px;
  padding: 0 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid rgba(128, 203, 196, 0.4);
  background: rgba(128, 203, 196, 0.12);
  color: #80cbc4;
  cursor: pointer;
}
.compare-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.spinner {
  width: 15px;
  height: 15px;
  border: 2px solid #333;
  border-top-color: #80cbc4;
  border-radius: 50%;
  display: inline-block;
  animation: spin 0.7s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.compare-error {
  border: 1px solid rgba(229, 128, 122, 0.3);
  background: rgba(229, 128, 122, 0.05);
  border-radius: 10px;
  padding: 18px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  color: #edb4b0;
  font-size: 13px;
}
.compare-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.compare-group {
  border: 1px solid #2c2c2c;
  border-radius: 10px;
  overflow: hidden;
}
.compare-group-head {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 14px;
  background: #1c1c1c;
  border-bottom: 1px solid #232323;
}
.compare-group-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}
.compare-group-label {
  font-size: 13px;
  font-weight: 600;
  color: #e5e5e5;
}
.compare-group-count {
  font-size: 12px;
  color: #6e6e6e;
}
.compare-group-files {
  padding: 4px 0;
}
.compare-file {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12.5px;
  color: #b4b4b4;
  padding: 5px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.compare-file-sign {
  width: 12px;
}

/* Sidebar */
.side-card {
  border: 1px solid #2c2c2c;
  background: #1a1a1a;
  border-radius: 12px;
  padding: 16px;
}
.solid-btn {
  width: 100%;
  height: 40px;
  border-radius: 8px;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid #2c2c2c;
  background: #232323;
  color: #e5e5e5;
  transition: all 0.13s;
  margin-bottom: 8px;
}
.solid-btn.active {
  background: rgba(128, 203, 196, 0.12);
  border-color: rgba(128, 203, 196, 0.4);
  color: #80cbc4;
}
.solid-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.side-divider {
  height: 1px;
  background: #2c2c2c;
  margin: 16px 0;
}
.side-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: #6e6e6e;
  margin-bottom: 12px;
}
.stat-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 11px;
}
.stat-row:last-child {
  margin-bottom: 0;
}
.stat-key {
  font-size: 12.5px;
  color: #9f9f9f;
}
.stat-value {
  font-size: 14px;
  font-weight: 650;
  color: #e5e5e5;
}
.stat-value-gold {
  color: #e0a458;
}
.meta-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  font-size: 12.5px;
  margin-bottom: 11px;
}
.meta-row:last-child {
  margin-bottom: 0;
}
.meta-key {
  color: #9f9f9f;
}
.meta-value {
  color: #c9c9c9;
}
.meta-value-mono {
  color: #c9c9c9;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
  text-align: right;
  word-break: break-all;
}
.meta-value-teal {
  color: #80cbc4;
}

@media (max-width: 1080px) {
  .detail-cols {
    flex-direction: column;
  }
  .sidebar {
    width: 100%;
    order: -1;
  }
  .docs-body {
    flex-direction: column;
  }
  .toc-sidebar {
    display: none;
  }
}
</style>
