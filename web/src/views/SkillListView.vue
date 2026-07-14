<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { listSkills } from '../lib/api.js'
import {
  buildSearchParams,
  paginationState,
  resolveFilterChange,
  activeFilterChips,
  splitTagsInput,
  SORT_OPTIONS,
} from '../lib/search.js'
import { formatCount, formatRating, formatRelativeDays } from '../lib/format.js'

const { t } = useI18n()
const skills = ref([])
const query = ref('')
const namespace = ref('')
const author = ref('')
const tagsInput = ref('')
const sort = ref('updated')
const page = ref(1)
const pagination = ref(paginationState())
const loading = ref(true)
const error = ref(null)
const hasLoadedOnce = ref(false)

const CHIP_TYPE_LABELS = { query: '搜索', namespace: '命名空间', author: '作者', tag: '标签' }

const hasAnyFilter = computed(() => Boolean(query.value.trim() || namespace.value.trim() || author.value.trim() || tagsInput.value.trim()))
const chips = computed(() => activeFilterChips({
  query: query.value,
  namespace: namespace.value,
  author: author.value,
  tagsInput: tagsInput.value,
}))
const listState = computed(() => {
  if (loading.value && !hasLoadedOnce.value) return 'skeleton'
  if (error.value) return 'error'
  if (skills.value.length === 0) return hasAnyFilter.value ? 'noResults' : 'empty'
  return 'ready'
})
const showLoadingOverlay = computed(() => loading.value && hasLoadedOnce.value && listState.value === 'ready')

async function load() {
  loading.value = true
  error.value = null
  try {
    const params = buildSearchParams({
      namespace: namespace.value,
      author: author.value,
      tagsInput: tagsInput.value,
      sort: sort.value,
      page: page.value,
    })
    const result = await listSkills(query.value.trim(), params)
    skills.value = result.items
    pagination.value = paginationState(result)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
    hasLoadedOnce.value = true
  }
}

function clearFilters() {
  query.value = ''
  namespace.value = ''
  author.value = ''
  tagsInput.value = ''
  sort.value = 'updated'
  page.value = 1
}

function removeChip(chip) {
  if (chip.type === 'query') query.value = ''
  else if (chip.type === 'namespace') namespace.value = ''
  else if (chip.type === 'author') author.value = ''
  else if (chip.type === 'tag') tagsInput.value = splitTagsInput(tagsInput.value).filter((tag) => tag !== chip.value).join(', ')
}

function prevPage() {
  if (pagination.value.hasPrev) page.value -= 1
}

function nextPage() {
  if (pagination.value.hasNext) page.value += 1
}

// Single watcher over every source that should trigger a reload, instead of one watch() per
// source. Vue's default `flush: 'pre'` only collapses multiple *synchronous mutations to the
// same watched source* into one job — it does NOT collapse separate watch() registrations that
// each depend on different sources, even when those sources all change in the same tick (e.g.
// clearFilters() touches namespace/author/tagsInput/sort/page together). With independent
// watchers that used to mean 2-3 redundant load() calls per clearFilters() click. Watching the
// whole tuple together makes it one Vue reactivity job, so `flush: 'post'` fires the callback
// exactly once per tick no matter how many of the six refs changed.
let debounceHandle
watch(
  [query, namespace, author, tagsInput, sort, page],
  (next, prev) => {
    const { action } = resolveFilterChange(prev, next)
    clearTimeout(debounceHandle)
    if (action === 'none') return
    if (action === 'load') {
      load()
    } else if (action === 'resetImmediate') {
      if (page.value === 1) load()
      else page.value = 1
    } else if (action === 'resetDebounced') {
      debounceHandle = setTimeout(() => {
        if (page.value === 1) load()
        else page.value = 1
      }, 250)
    }
  },
  { flush: 'post' },
)

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">{{ t('skills.title') }}</h1>
        <p class="page-subtitle">{{ t('skills.subtitle') }}</p>
      </div>
      <div class="result-count">
        共 <strong>{{ pagination.total }}</strong> 个技能
      </div>
    </div>

    <div class="search-box">
      <span class="search-icon">⌕</span>
      <input v-model="query" class="search-input" type="search" spellcheck="false" :placeholder="t('skills.searchPlaceholder')" />
      <div class="search-actions">
        <span v-if="loading" class="spinner"></span>
        <button v-if="query" type="button" class="icon-btn" @click="query = ''">✕</button>
      </div>
    </div>

    <div class="filter-bar">
      <input v-model="namespace" class="filter-input" type="text" :placeholder="t('skills.filters.namespacePlaceholder')" />
      <input v-model="author" class="filter-input" type="text" :placeholder="t('skills.filters.authorPlaceholder')" />
      <input v-model="tagsInput" class="filter-input tags-input" type="text" :placeholder="t('skills.filters.tagsPlaceholder')" />
      <div class="divider"></div>
      <span class="sort-label">{{ t('skills.filters.sortLabel') }}</span>
      <select v-model="sort" class="select">
        <option v-for="opt in SORT_OPTIONS" :key="opt" :value="opt">{{ t(`skills.sort.${opt}`) }}</option>
      </select>
      <button v-if="hasAnyFilter" type="button" class="clear-filters-btn" @click="clearFilters">{{ t('skills.filters.clear') }}</button>
    </div>

    <div v-if="chips.length" class="chip-row">
      <span v-for="(chip, idx) in chips" :key="`${chip.type}-${chip.value}-${idx}`" class="chip">
        <span class="chip-label">{{ CHIP_TYPE_LABELS[chip.type] }}</span>{{ chip.value }}
        <button type="button" class="chip-remove" @click="removeChip(chip)">✕</button>
      </span>
    </div>

    <div class="list-area">
      <!-- Skeleton -->
      <div v-if="listState === 'skeleton'" class="skeleton-list">
        <div v-for="i in 6" :key="i" class="skeleton-row">
          <div class="skeleton-main">
            <div class="sk-shim sk-shim-title"></div>
            <div class="sk-shim sk-shim-desc"></div>
            <div class="sk-shim-tags">
              <div class="sk-shim sk-shim-tag"></div>
              <div class="sk-shim sk-shim-tag wide"></div>
            </div>
          </div>
          <div class="sk-shim sk-shim-side"></div>
        </div>
      </div>

      <!-- Error -->
      <div v-else-if="listState === 'error'" class="state-box state-error">
        <div class="state-icon">⚠</div>
        <div class="state-title">{{ t('skills.errorTitle') }}</div>
        <div class="state-body">{{ t('errors.loadFailed', { error }) }}</div>
        <button type="button" class="state-action" @click="load">{{ t('common.retry') }}</button>
      </div>

      <!-- Empty (no data at all) -->
      <div v-else-if="listState === 'empty'" class="state-box state-dashed">
        <div class="state-icon dim">📦</div>
        <div class="state-title">{{ t('skills.emptyTitle') }}</div>
        <div class="state-body">{{ t('skills.emptyBody') }}</div>
      </div>

      <!-- No results -->
      <div v-else-if="listState === 'noResults'" class="state-box state-dashed">
        <div class="state-icon dim">🔍</div>
        <div class="state-title">{{ t('skills.noResultsTitle') }}</div>
        <div class="state-body">{{ t('skills.noResultsBody') }}</div>
        <button type="button" class="state-action state-action-outline" @click="clearFilters">{{ t('skills.clearAllFilters') }}</button>
      </div>

      <!-- Ready list -->
      <template v-else>
        <div class="skill-rows" :class="{ 'is-loading': showLoadingOverlay }">
          <div v-if="showLoadingOverlay" class="loading-overlay">
            <span class="spinner spinner-lg"></span>
          </div>
          <router-link
            v-for="skill in skills"
            :key="`${skill.namespace}/${skill.name}`"
            :to="{ name: 'skill-detail', params: { namespace: skill.namespace, name: skill.name } }"
            class="skill-row"
          >
            <div class="row-main">
              <div class="row-head">
                <span class="row-name">{{ skill.namespace }}/{{ skill.name }}</span>
                <span class="row-version">v{{ skill.version }}</span>
              </div>
              <div class="row-desc">{{ skill.description }}</div>
              <div class="row-meta">
                <span v-for="tag in skill.tags.slice(0, 3)" :key="tag" class="tag">{{ tag }}</span>
                <span v-if="skill.tags.length > 3" class="more-tags">+{{ skill.tags.length - 3 }}</span>
                <span class="author">{{ t('skills.byAuthor', { author: skill.author }) }}</span>
              </div>
            </div>
            <div class="row-side">
              <div class="row-stats">
                <span title="平台累计安装次数">↓ {{ formatCount(skill.installCount) }}</span>
                <span
                  class="rating"
                  :title="skill.ratingAverage == null ? '暂无评分' : `${formatCount(skill.ratingCount)} 人评分`"
                >
                  ★ {{ formatRating(skill.ratingAverage) }}
                  <small v-if="skill.ratingAverage != null" class="rating-count">({{ formatCount(skill.ratingCount) }})</small>
                </span>
                <span title="收藏人数">☆ {{ formatCount(skill.starCount) }}</span>
              </div>
              <span class="row-updated">{{ t('skills.updatedRelative', { days: formatRelativeDays(skill.publishedAt) }) }}</span>
            </div>
          </router-link>
        </div>

        <nav class="pagination">
          <span class="page-info-total">{{ t('skills.pagination.totalResults', { total: pagination.total }) }} · 每页 {{ pagination.pageSize }} 个</span>
          <div class="page-controls">
            <button type="button" class="page-btn" :disabled="!pagination.hasPrev" @click="prevPage">← {{ t('skills.pagination.prev') }}</button>
            <span class="page-info">{{ t('skills.pagination.pageOf', { page: pagination.page, totalPages: pagination.totalPages }) }}</span>
            <button type="button" class="page-btn" :disabled="!pagination.hasNext" @click="nextPage">{{ t('skills.pagination.next') }} →</button>
          </div>
        </nav>
      </template>
    </div>
  </div>
</template>

<style scoped>
.page {
  padding: 4px 0 40px;
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.page-title {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 5px;
  letter-spacing: -0.4px;
  color: #f2f2f2;
}
.page-subtitle {
  margin: 0;
  font-size: 13.5px;
  color: #9f9f9f;
}
.result-count {
  font-size: 13px;
  color: #9f9f9f;
  padding-bottom: 2px;
}
.result-count strong {
  color: #e5e5e5;
  font-weight: 650;
}

/* Search */
.search-box {
  position: relative;
  margin-bottom: 12px;
}
.search-icon {
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
  color: #6e6e6e;
  font-size: 16px;
  pointer-events: none;
}
.search-input {
  width: 100%;
  height: 48px;
  background: #1c1c1c;
  border: 1px solid #2c2c2c;
  border-radius: 10px;
  padding: 0 92px 0 42px;
  color: #e5e5e5;
  font-size: 15px;
  outline: none;
  transition: border-color 0.15s;
}
.search-input:focus {
  border-color: #80cbc4;
}
.search-actions {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
}
.icon-btn {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #2c2c2c;
  border: none;
  color: #b9b9b9;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}
.icon-btn:hover {
  background: #3a3a3a;
  color: #fff;
}

/* Filter bar */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 2px 0;
}
.filter-input {
  height: 38px;
  background: #1c1c1c;
  border: 1px solid #2c2c2c;
  border-radius: 8px;
  padding: 0 12px;
  color: #e5e5e5;
  font-size: 13px;
  outline: none;
  min-width: 160px;
  flex: 1 1 160px;
}
.filter-input.tags-input {
  min-width: 200px;
  max-width: 280px;
}
.filter-input:focus {
  border-color: #80cbc4;
}
.divider {
  width: 1px;
  height: 22px;
  background: #2c2c2c;
  margin: 0 2px;
}
.sort-label {
  font-size: 12.5px;
  color: #9f9f9f;
}
.select {
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
.clear-filters-btn {
  height: 38px;
  padding: 0 14px;
  background: transparent;
  border: 1px solid #2c2c2c;
  border-radius: 8px;
  color: #9f9f9f;
  font-size: 13px;
  cursor: pointer;
  margin-left: auto;
}
.clear-filters-btn:hover {
  border-color: #e5807a;
  color: #e5807a;
}

/* Chips */
.chip-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 28px;
  padding: 0 6px 0 11px;
  background: rgba(128, 203, 196, 0.1);
  border: 1px solid rgba(128, 203, 196, 0.28);
  border-radius: 20px;
  font-size: 12px;
  color: #a7dbd5;
}
.chip-label {
  color: #6b8f8b;
  font-size: 11px;
}
.chip-remove {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: rgba(128, 203, 196, 0.18);
  border: none;
  color: #a7dbd5;
  font-size: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.list-area {
  margin-top: 20px;
}

/* Skeleton */
@keyframes shimmer {
  0% { background-position: -400px 0; }
  100% { background-position: 400px 0; }
}
.sk-shim {
  background: linear-gradient(90deg, #1c1c1c 0%, #242424 40%, #1c1c1c 80%);
  background-size: 800px 100%;
  animation: shimmer 1.4s infinite linear;
  border-radius: 5px;
}
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  border: 1px solid #2c2c2c;
  border-radius: 12px;
  overflow: hidden;
}
.skeleton-row {
  padding: 18px 22px;
  background: #181818;
  display: flex;
  justify-content: space-between;
  gap: 24px;
}
.skeleton-main {
  flex: 1;
}
.sk-shim-title {
  height: 16px;
  width: 38%;
  margin-bottom: 12px;
}
.sk-shim-desc {
  height: 12px;
  width: 62%;
  margin-bottom: 12px;
}
.sk-shim-tags {
  display: flex;
  gap: 8px;
}
.sk-shim-tag {
  height: 18px;
  width: 52px;
}
.sk-shim-tag.wide {
  width: 64px;
}
.sk-shim-side {
  height: 14px;
  width: 120px;
  align-self: center;
}

/* State boxes */
.state-box {
  border-radius: 12px;
  padding: 56px 24px;
  text-align: center;
}
.state-box.state-error {
  border: 1px solid #3a2a2a;
  background: rgba(229, 128, 122, 0.05);
}
.state-box.state-dashed {
  border: 1px dashed #2c2c2c;
  padding: 64px 24px;
}
.state-icon {
  font-size: 30px;
  margin-bottom: 14px;
}
.state-icon.dim {
  opacity: 0.5;
}
.state-title {
  font-size: 16px;
  color: #e5e5e5;
  font-weight: 600;
  margin-bottom: 6px;
}
.state-body {
  font-size: 13.5px;
  color: #9f9f9f;
  margin-bottom: 22px;
}
.state-action {
  padding: 9px 22px;
  background: #80cbc4;
  color: #0f1615;
  border: none;
  border-radius: 8px;
  font-size: 13.5px;
  font-weight: 650;
  cursor: pointer;
}
.state-action:hover {
  background: #98d6cf;
}
.state-action.state-action-outline {
  padding: 9px 20px;
  background: transparent;
  border: 1px solid #2c2c2c;
  color: #e5e5e5;
  font-weight: normal;
}
.state-action.state-action-outline:hover {
  border-color: #80cbc4;
  color: #80cbc4;
}

/* Ready list */
.skill-rows {
  position: relative;
  border: 1px solid #2c2c2c;
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: opacity 0.18s;
}
.skill-rows.is-loading {
  opacity: 0.55;
}
.loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 5;
  background: rgba(18, 18, 18, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
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
.spinner.spinner-lg {
  width: 22px;
  height: 22px;
  border-width: 2.5px;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.skill-row {
  padding: 17px 22px;
  background: #181818;
  border-bottom: 1px solid #212121;
  cursor: pointer;
  display: flex;
  gap: 24px;
  align-items: flex-start;
  transition: background 0.13s;
  text-decoration: none;
  color: inherit;
}
.skill-row:last-child {
  border-bottom: none;
}
.skill-row:hover {
  background: #1e1e1e;
}
.row-main {
  flex: 1;
  min-width: 0;
}
.row-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.row-name {
  font-size: 15px;
  font-weight: 650;
  color: #80cbc4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.row-version {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 11px;
  color: #9f9f9f;
  background: #232323;
  border: 1px solid #2c2c2c;
  padding: 1px 7px;
  border-radius: 5px;
}
.row-desc {
  font-size: 13.5px;
  color: #b4b4b4;
  line-height: 1.5;
  margin-bottom: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}
.row-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.row-meta .tag {
  font-size: 11px;
  color: #8fb8b3;
  background: rgba(128, 203, 196, 0.08);
  border: 1px solid rgba(128, 203, 196, 0.18);
  padding: 2px 8px;
  border-radius: 20px;
}
.more-tags {
  font-size: 11px;
  color: #6e6e6e;
}
.row-meta .author {
  font-size: 12px;
  color: #6e6e6e;
  margin-left: 4px;
}
.row-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 7px;
  white-space: nowrap;
  padding-top: 2px;
  flex: none;
}
.row-stats {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12.5px;
  color: #9f9f9f;
}
.row-stats .rating {
  color: #e0a458;
}
.rating-count {
  color: #777;
  font-size: 10.5px;
}
.row-updated {
  font-size: 11.5px;
  color: #6e6e6e;
}

/* Pagination */
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 18px;
  gap: 16px;
  flex-wrap: wrap;
}
.page-info-total {
  font-size: 12.5px;
  color: #6e6e6e;
}
.page-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}
.page-btn {
  height: 36px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  border: 1px solid #2c2c2c;
  background: #1c1c1c;
  color: #c9c9c9;
  cursor: pointer;
  transition: all 0.13s;
}
.page-btn:disabled {
  color: #4a4a4a;
  cursor: not-allowed;
  opacity: 0.6;
}
.page-info {
  font-size: 13px;
  color: #c9c9c9;
  padding: 0 8px;
}

@media (max-width: 640px) {
  .page-head {
    align-items: flex-start;
  }
  .filter-input.tags-input {
    max-width: none;
  }
  .clear-filters-btn {
    margin-left: 0;
  }
}
</style>
