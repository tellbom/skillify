<script setup>
import { ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getLeaderboard } from '../lib/api.js'
import { formatDate } from '../lib/datetime.js'

const { t } = useI18n()
const dimension = ref('installs')
const window_ = ref('all')
const rows = ref([])
const loading = ref(true)
const error = ref(null)

const DIMENSIONS = [
  { key: 'installs', labelKey: 'leaderboard.dimensions.installs' },
  { key: 'rating', labelKey: 'leaderboard.dimensions.rating' },
  { key: 'recent', labelKey: 'leaderboard.dimensions.recent' },
]

const WINDOWS = [
  { key: 'week', labelKey: 'leaderboard.windows.week' },
  { key: 'month', labelKey: 'leaderboard.windows.month' },
  { key: 'all', labelKey: 'leaderboard.windows.all' },
]

async function load() {
  loading.value = true
  error.value = null
  try {
    rows.value = await getLeaderboard(dimension.value, window_.value)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

watch([dimension, window_], load)
onMounted(load)
</script>

<template>
  <div class="leaderboard-page">
    <header class="page-heading">
      <h1>{{ t('leaderboard.title') }}</h1>
      <p>发现组织内高质量、热门与最新发布的 Agent Skill</p>
    </header>

    <div class="dimension-tabs" role="tablist" aria-label="排行榜维度">
      <button
        v-for="item in DIMENSIONS"
        :key="item.key"
        type="button"
        :class="{ active: dimension === item.key }"
        @click="dimension = item.key"
      >
        {{ t(item.labelKey) }}
      </button>
    </div>

    <div v-if="dimension === 'installs'" class="window-filter">
      <span>时间范围</span>
      <button
        v-for="item in WINDOWS"
        :key="item.key"
        type="button"
        :class="{ active: window_ === item.key }"
        @click="window_ = item.key"
      >
        {{ t(item.labelKey) }}
      </button>
    </div>
    <p v-else class="dimension-hint">提示：时间范围仅对“安装量最多”榜单生效，评分与最新发布榜单不随时间范围变化。</p>

    <div v-if="loading" class="state-panel"><span class="spinner" />{{ t('common.loading') }}</div>
    <div v-else-if="error" class="state-panel error">{{ t('errors.loadFailed', { error }) }}</div>
    <div v-else-if="rows.length === 0" class="state-panel">{{ t('leaderboard.nothingPublished') }}</div>

    <ol v-else class="board-list">
      <li v-for="(row, index) in rows" :key="`${row.namespace}/${row.name}`">
        <router-link
          class="board-row"
          :to="{ name: 'skill-detail', params: { namespace: row.namespace, name: row.name } }"
        >
          <span class="rank" :class="`rank-${index + 1}`">{{ index + 1 }}</span>
          <span class="skill-info">
            <strong>{{ row.namespace }}/{{ row.name }}</strong>
            <span>{{ row.description }}</span>
          </span>
          <span class="metric">
            <template v-if="dimension === 'installs'">
              <strong>{{ row.installCount }}</strong>
              <small>次安装</small>
            </template>
            <template v-else-if="dimension === 'rating'">
              <strong>{{ row.ratingAverage !== null ? row.ratingAverage.toFixed(1) : '—' }}</strong>
              <small>★ · {{ row.ratingCount }} 次评分</small>
            </template>
            <template v-else>
              <strong class="published-date">{{ formatDate(row.publishedAt) }}</strong>
              <small>发布时间</small>
            </template>
          </span>
          <span class="row-arrow" aria-hidden="true">›</span>
        </router-link>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.leaderboard-page {
  padding: 2px 0 12px;
  animation: page-in 0.25s ease both;
}

.page-heading {
  margin-bottom: 18px;
}

.page-heading h1 {
  margin: 0 0 5px;
  color: #f2f2f2;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.4px;
}

.page-heading p {
  margin: 0;
  color: #9f9f9f;
  font-size: 13.5px;
}

.dimension-tabs {
  display: flex;
  margin-bottom: 16px;
  gap: 8px;
  flex-wrap: wrap;
}

.dimension-tabs button,
.window-filter button {
  border: 1px solid #2c2c2c;
  border-radius: 7px;
  color: #9f9f9f;
  background: transparent;
  font: inherit;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background-color 0.15s ease;
}

.dimension-tabs button {
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 550;
}

.dimension-tabs button:hover,
.dimension-tabs button.active {
  border-color: rgb(128 203 196 / 35%);
  color: #80cbc4;
  background: rgb(128 203 196 / 8%);
}

.window-filter {
  display: flex;
  align-items: center;
  margin-bottom: 18px;
  gap: 8px;
}

.window-filter > span {
  margin-right: 2px;
  color: #6e6e6e;
  font-size: 12.5px;
}

.window-filter button {
  padding: 5px 11px;
  font-size: 12px;
}

.window-filter button:hover,
.window-filter button.active {
  border-color: #3d3d3d;
  color: #e5e5e5;
  background: #232323;
}

.dimension-hint {
  margin: 0 0 18px;
  color: #6e6e6e;
  font-size: 12px;
}

.board-list {
  overflow: hidden;
  margin: 0;
  padding: 0;
  border: 1px solid #2c2c2c;
  border-radius: 12px;
  list-style: none;
}

.board-list li:not(:last-child) {
  border-bottom: 1px solid #212121;
}

.board-row {
  display: flex;
  align-items: center;
  padding: 15px 20px;
  color: inherit;
  background: #181818;
  gap: 18px;
  text-decoration: none;
  transition: background-color 0.13s ease;
}

.board-row:hover,
.board-row:focus-visible {
  background: #1e1e1e;
  outline: none;
}

.rank {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  color: #777;
  background: #202020;
  font-size: 13px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.rank-1 { color: #e5bb67; background: rgb(229 187 103 / 12%); }
.rank-2 { color: #b9c1c9; background: rgb(185 193 201 / 10%); }
.rank-3 { color: #c38c68; background: rgb(195 140 104 / 11%); }

.skill-info {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}

.skill-info strong {
  overflow: hidden;
  color: #80cbc4;
  font-size: 14.5px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-info > span {
  overflow: hidden;
  color: #9f9f9f;
  font-size: 12.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric {
  display: flex;
  flex: none;
  align-items: flex-end;
  min-width: 112px;
  text-align: right;
  white-space: nowrap;
  flex-direction: column;
}

.metric strong {
  color: #80cbc4;
  font-size: 15px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.metric strong.published-date {
  color: #c9c9c9;
  font-size: 13px;
}

.metric small {
  color: #6e6e6e;
  font-size: 11px;
}

.row-arrow {
  flex: none;
  color: #4a4a4a;
  font-size: 18px;
}

.state-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  border: 1px dashed #2c2c2c;
  border-radius: 12px;
  color: #6e6e6e;
  font-size: 13px;
  gap: 10px;
}

.state-panel.error { color: #edb4b0; }

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid #333;
  border-top-color: #80cbc4;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes page-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }

@media (max-width: 640px) {
  .board-row { padding: 14px; gap: 12px; }
  .metric { min-width: auto; }
  .rank { width: 26px; height: 26px; }
}
</style>
