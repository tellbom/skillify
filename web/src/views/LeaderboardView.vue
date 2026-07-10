<script setup>
import { ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getLeaderboard } from '../lib/api.js'
import { formatDate } from '../lib/datetime.js'

const { t } = useI18n()
const dimension = ref('installs')
const rows = ref([])
const loading = ref(true)
const error = ref(null)

const DIMENSIONS = [
  { key: 'installs', labelKey: 'leaderboard.dimensions.installs' },
  { key: 'rating', labelKey: 'leaderboard.dimensions.rating' },
  { key: 'recent', labelKey: 'leaderboard.dimensions.recent' },
]

async function load() {
  loading.value = true
  error.value = null
  try {
    rows.value = await getLeaderboard(dimension.value)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

watch(dimension, load)
onMounted(load)
</script>

<template>
  <div>
    <router-link to="/" class="back-link">{{ t('common.backToSkills') }}</router-link>
    <h2>{{ t('leaderboard.title') }}</h2>

    <nav class="tabs">
      <button v-for="d in DIMENSIONS" :key="d.key" :class="{ active: dimension === d.key }" @click="dimension = d.key">
        {{ t(d.labelKey) }}
      </button>
    </nav>

    <p v-if="loading" class="hint">{{ t('common.loading') }}</p>
    <p v-else-if="error" class="error">{{ t('errors.loadFailed', { error }) }}</p>
    <p v-else-if="rows.length === 0" class="hint">{{ t('leaderboard.nothingPublished') }}</p>

    <ol v-else class="board">
      <li v-for="row in rows" :key="`${row.namespace}/${row.name}`">
        <router-link :to="{ name: 'skill-detail', params: { namespace: row.namespace, name: row.name } }">
          {{ row.namespace }}/{{ row.name }}
        </router-link>
        <span class="description">{{ row.description }}</span>
        <span class="metric">
          <template v-if="dimension === 'installs'">{{ t('leaderboard.installsCount', { n: row.installCount }) }}</template>
          <template v-else-if="dimension === 'rating'">
            {{ row.ratingAverage !== null ? row.ratingAverage.toFixed(1) : '—' }} ★ ({{ row.ratingCount }})
          </template>
          <template v-else>{{ formatDate(row.publishedAt) }}</template>
        </span>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.back-link { display: inline-block; margin-bottom: 1rem; color: #888; text-decoration: none; }
.hint { color: #888; }
.error { color: #e06c75; }
.tabs { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; }
.tabs button {
  background: none;
  border: 1px solid #444;
  border-radius: 999px;
  color: #888;
  padding: 0.3rem 0.9rem;
  cursor: pointer;
  font-size: 0.85rem;
}
.tabs button.active {
  color: inherit;
  border-color: #80cbc4;
}
.board {
  list-style: decimal;
  padding-left: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.board li {
  display: flex;
  align-items: baseline;
  gap: 0.8rem;
}
.description {
  color: #888;
  font-size: 0.85rem;
  flex: 1;
}
.metric {
  color: #80cbc4;
  font-size: 0.85rem;
  white-space: nowrap;
}
</style>
