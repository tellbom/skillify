<script setup>
import { ref, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { listSkills } from '../lib/api.js'
import { buildSearchParams, paginationState, resolveFilterChange, SORT_OPTIONS } from '../lib/search.js'

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
  }
}

function clearFilters() {
  namespace.value = ''
  author.value = ''
  tagsInput.value = ''
  sort.value = 'updated'
  page.value = 1
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
  <div>
    <input
      v-model="query"
      class="search-input"
      type="search"
      :placeholder="t('skills.searchPlaceholder')"
    />

    <div class="filters">
      <input
        v-model="namespace"
        class="filter-input"
        type="text"
        :placeholder="t('skills.filters.namespacePlaceholder')"
      />
      <input
        v-model="author"
        class="filter-input"
        type="text"
        :placeholder="t('skills.filters.authorPlaceholder')"
      />
      <input
        v-model="tagsInput"
        class="filter-input"
        type="text"
        :placeholder="t('skills.filters.tagsPlaceholder')"
      />
      <label class="sort-select">
        {{ t('skills.filters.sortLabel') }}
        <select v-model="sort">
          <option v-for="opt in SORT_OPTIONS" :key="opt" :value="opt">{{ t(`skills.sort.${opt}`) }}</option>
        </select>
      </label>
      <button type="button" class="clear-btn" @click="clearFilters">{{ t('skills.filters.clear') }}</button>
    </div>

    <p v-if="loading" class="hint">{{ t('common.loading') }}</p>
    <p v-else-if="error" class="error">{{ t('errors.loadFailed', { error }) }}</p>
    <p v-else-if="skills.length === 0" class="hint">{{ t('skills.noSkillsFound') }}</p>

    <ul v-else class="skill-list">
      <li v-for="skill in skills" :key="`${skill.namespace}/${skill.name}`" class="skill-card">
        <router-link :to="{ name: 'skill-detail', params: { namespace: skill.namespace, name: skill.name } }">
          <h3>{{ skill.namespace }}/{{ skill.name }} <span class="version">v{{ skill.version }}</span></h3>
        </router-link>
        <p class="description">{{ skill.description }}</p>
        <div class="tags">
          <span v-for="tag in skill.tags" :key="tag" class="tag">{{ tag }}</span>
        </div>
        <p class="author">{{ t('skills.byAuthor', { author: skill.author }) }}</p>
      </li>
    </ul>

    <nav v-if="!loading && !error && skills.length > 0" class="pagination">
      <button type="button" :disabled="!pagination.hasPrev" @click="prevPage">{{ t('skills.pagination.prev') }}</button>
      <span class="page-info">
        {{ t('skills.pagination.pageOf', { page: pagination.page, totalPages: pagination.totalPages }) }}
        · {{ t('skills.pagination.totalResults', { total: pagination.total }) }}
      </span>
      <button type="button" :disabled="!pagination.hasNext" @click="nextPage">{{ t('skills.pagination.next') }}</button>
    </nav>
  </div>
</template>

<style scoped>
.search-input {
  width: 100%;
  padding: 0.6rem 0.8rem;
  font-size: 1rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  margin-bottom: 1rem;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  align-items: center;
  margin-bottom: 1.5rem;
}
.filter-input {
  flex: 1 1 160px;
  padding: 0.45rem 0.7rem;
  font-size: 0.9rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
}
.sort-select {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  color: #888;
}
.sort-select select {
  padding: 0.4rem 0.5rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
}
.clear-btn {
  background: none;
  border: 1px solid #444;
  border-radius: 6px;
  color: #888;
  padding: 0.4rem 0.8rem;
  cursor: pointer;
  font-size: 0.85rem;
}
.hint {
  color: #888;
}
.error {
  color: #e06c75;
}
.skill-list {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.skill-card {
  border: 1px solid #333;
  border-radius: 8px;
  padding: 1rem 1.2rem;
}
.skill-card h3 {
  margin: 0 0 0.4rem;
}
.version {
  color: #888;
  font-weight: 400;
  font-size: 0.85rem;
}
.description {
  color: #ccc;
  margin: 0 0 0.5rem;
}
.tags {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  margin-bottom: 0.4rem;
}
.tag {
  background: #263238;
  color: #80cbc4;
  border-radius: 999px;
  padding: 0.1rem 0.6rem;
  font-size: 0.75rem;
}
.author {
  color: #888;
  font-size: 0.8rem;
  margin: 0;
}
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-top: 1.5rem;
}
.pagination button {
  background: none;
  border: 1px solid #444;
  border-radius: 6px;
  color: inherit;
  padding: 0.4rem 0.9rem;
  cursor: pointer;
  font-size: 0.85rem;
}
.pagination button:disabled {
  color: #555;
  cursor: not-allowed;
}
.page-info {
  color: #888;
  font-size: 0.85rem;
}
</style>
