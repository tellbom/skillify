<script setup>
import { ref, watch, onMounted } from 'vue'
import { getLeaderboard } from '../lib/api.js'

const dimension = ref('installs')
const rows = ref([])
const loading = ref(true)
const error = ref(null)

const DIMENSIONS = [
  { key: 'installs', label: 'Most installed' },
  { key: 'rating', label: 'Top rated' },
  { key: 'recent', label: 'Recently published' },
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
    <router-link to="/" class="back-link">&larr; back to all skills</router-link>
    <h2>Leaderboard</h2>

    <nav class="tabs">
      <button v-for="d in DIMENSIONS" :key="d.key" :class="{ active: dimension === d.key }" @click="dimension = d.key">
        {{ d.label }}
      </button>
    </nav>

    <p v-if="loading" class="hint">Loading…</p>
    <p v-else-if="error" class="error">Failed to load leaderboard: {{ error }}</p>
    <p v-else-if="rows.length === 0" class="hint">Nothing published yet.</p>

    <ol v-else class="board">
      <li v-for="row in rows" :key="`${row.namespace}/${row.name}`">
        <router-link :to="{ name: 'skill-detail', params: { namespace: row.namespace, name: row.name } }">
          {{ row.namespace }}/{{ row.name }}
        </router-link>
        <span class="description">{{ row.description }}</span>
        <span class="metric">
          <template v-if="dimension === 'installs'">{{ row.installCount }} installs</template>
          <template v-else-if="dimension === 'rating'">
            {{ row.ratingAverage !== null ? row.ratingAverage.toFixed(1) : '—' }} ★ ({{ row.ratingCount }})
          </template>
          <template v-else>{{ new Date(row.publishedAt).toLocaleDateString() }}</template>
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
