<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  codeMap: {
    type: Object,
    default: () => ({ schemaVersion: 1, repositoryHash: '', nodes: [], edges: [] }),
  },
})

const activeKind = ref('all')
const selectedId = ref('')

const kinds = computed(() => {
  const counts = new Map()
  for (const node of props.codeMap.nodes || []) {
    counts.set(node.kind, (counts.get(node.kind) || 0) + 1)
  }
  return [...counts.entries()].sort(([left], [right]) => left.localeCompare(right))
})

const visibleNodes = computed(() => (props.codeMap.nodes || []).filter(
  (node) => activeKind.value === 'all' || node.kind === activeKind.value,
))

const selectedNode = computed(() => {
  const candidates = visibleNodes.value
  return candidates.find((node) => node.id === selectedId.value) || candidates[0] || null
})

const relatedEdges = computed(() => {
  if (!selectedNode.value) return []
  return (props.codeMap.edges || []).filter(
    (edge) => edge.source === selectedNode.value.id || edge.target === selectedNode.value.id,
  )
})

function selectKind(kind) {
  activeKind.value = kind
  selectedId.value = ''
}

function evidenceLabel(evidence) {
  if (!evidence) return 'No evidence position'
  const range = evidence.endLine > evidence.line ? `-${evidence.endLine}` : ''
  return `${evidence.path}:${evidence.line}${range}`
}
</script>

<template>
  <main class="code-map-page" data-testid="code-map-view">
    <header class="map-heading">
      <div>
        <p class="eyebrow">LOCAL REPOSITORY INDEX</p>
        <h1>Code Map</h1>
        <p>只读浏览代码节点、关系与可跳转的证据位置。</p>
      </div>
      <dl class="map-stats" aria-label="Code Map 摘要">
        <div><dt>Nodes</dt><dd>{{ codeMap.nodes?.length || 0 }}</dd></div>
        <div><dt>Edges</dt><dd>{{ codeMap.edges?.length || 0 }}</dd></div>
        <div class="hash-stat"><dt>Repository</dt><dd>{{ codeMap.repositoryHash || 'not built' }}</dd></div>
      </dl>
    </header>

    <div v-if="!codeMap.nodes?.length" class="empty-map">
      <strong>尚未载入 Code Map</strong>
      <span>运行 skillctl map build 后载入导出的 code-map.json。</span>
    </div>

    <div v-else class="map-workbench">
      <aside class="kind-filter" aria-label="节点类型">
        <button :class="{ active: activeKind === 'all' }" @click="selectKind('all')">
          <span>All nodes</span><b>{{ codeMap.nodes.length }}</b>
        </button>
        <button
          v-for="([kind, count]) in kinds"
          :key="kind"
          :class="{ active: activeKind === kind }"
          @click="selectKind(kind)"
        >
          <span>{{ kind.replaceAll('_', ' ') }}</span><b>{{ count }}</b>
        </button>
      </aside>

      <section class="node-list" aria-label="代码节点">
        <button
          v-for="node in visibleNodes"
          :key="node.id"
          class="node-row"
          :class="{ selected: selectedNode?.id === node.id }"
          @click="selectedId = node.id"
        >
          <span class="node-kind">{{ node.kind }}</span>
          <strong>{{ node.name }}</strong>
          <code>{{ evidenceLabel(node.evidence) }}</code>
        </button>
      </section>

      <aside class="evidence-rail" aria-label="证据位置" data-testid="evidence-rail">
        <p class="rail-label">EVIDENCE RAIL</p>
        <template v-if="selectedNode">
          <h2>{{ selectedNode.name }}</h2>
          <span class="kind-badge">{{ selectedNode.kind }}</span>
          <div class="position-card">
            <span>Source position</span>
            <code>{{ evidenceLabel(selectedNode.evidence) }}</code>
          </div>
          <div class="relations">
            <h3>Relations <span>{{ relatedEdges.length }}</span></h3>
            <article v-for="edge in relatedEdges" :key="edge.id">
              <strong>{{ edge.kind }}</strong>
              <small>{{ Math.round((edge.confidence || 0) * 100) }}% · {{ edge.sourceLabel }}</small>
              <code>{{ evidenceLabel(edge.evidence) }}</code>
            </article>
            <p v-if="!relatedEdges.length" class="muted">No related edges.</p>
          </div>
        </template>
      </aside>
    </div>
  </main>
</template>

<style scoped>
.code-map-page {
  color: #e8e8e8;
  animation: page-in 0.25s ease both;
}

.map-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  margin-bottom: 18px;
  gap: 28px;
}

.eyebrow,
.rail-label {
  margin: 0 0 7px;
  color: #80cbc4;
  font: 650 10px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: 1.5px;
}

.map-heading h1 {
  margin: 0 0 5px;
  font-size: 26px;
  letter-spacing: -0.4px;
}

.map-heading > div > p:last-child {
  margin: 0;
  color: #909090;
  font-size: 13px;
}

.map-stats {
  display: flex;
  margin: 0;
  gap: 22px;
}

.map-stats div { min-width: 48px; }
.map-stats dt { color: #717171; font-size: 10px; text-transform: uppercase; }
.map-stats dd { margin: 4px 0 0; font: 600 13px ui-monospace, SFMono-Regular, Menlo, monospace; }
.map-stats .hash-stat { max-width: 150px; }
.hash-stat dd { overflow: hidden; color: #a8a8a8; text-overflow: ellipsis; white-space: nowrap; }

.map-workbench {
  display: grid;
  overflow: hidden;
  min-height: 480px;
  border: 1px solid #2c2c2c;
  border-radius: 12px;
  background: #181818;
  grid-template-columns: 180px minmax(280px, 1fr) minmax(240px, 320px);
}

.kind-filter,
.node-list { border-right: 1px solid #292929; }

.kind-filter { padding: 10px; }
.kind-filter button {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  padding: 9px 10px;
  border: 0;
  border-radius: 6px;
  color: #929292;
  background: transparent;
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.kind-filter button:hover,
.kind-filter button.active { color: #e7e7e7; background: #242424; }
.kind-filter button b { color: #666; font: 500 11px ui-monospace, monospace; }
.kind-filter button.active b { color: #80cbc4; }

.node-list { overflow: auto; max-height: 620px; padding: 8px 0; }
.node-row {
  display: grid;
  width: 100%;
  padding: 12px 16px;
  border: 0;
  border-left: 2px solid transparent;
  color: inherit;
  background: transparent;
  gap: 4px;
  text-align: left;
  cursor: pointer;
}
.node-row:hover { background: #1e1e1e; }
.node-row.selected { border-left-color: #80cbc4; background: #222; }
.node-row strong { font-size: 13px; }
.node-kind { color: #777; font: 600 9px ui-monospace, monospace; letter-spacing: 0.8px; text-transform: uppercase; }
.node-row code { overflow: hidden; color: #777; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }

.evidence-rail { padding: 20px; background: #151515; }
.evidence-rail h2 { margin: 0 0 8px; font-size: 18px; overflow-wrap: anywhere; }
.kind-badge { color: #80cbc4; font: 600 10px ui-monospace, monospace; text-transform: uppercase; }
.position-card {
  margin-top: 22px;
  padding: 12px;
  border: 1px solid rgb(128 203 196 / 22%);
  border-radius: 8px;
  background: rgb(128 203 196 / 5%);
}
.position-card span { display: block; margin-bottom: 6px; color: #777; font-size: 10px; }
.position-card code { color: #b2dfdb; font-size: 11px; overflow-wrap: anywhere; }
.relations { margin-top: 24px; }
.relations h3 { display: flex; justify-content: space-between; margin: 0 0 10px; font-size: 12px; }
.relations h3 span { color: #666; font-family: ui-monospace, monospace; }
.relations article { display: grid; padding: 10px 0; border-top: 1px solid #272727; gap: 3px; }
.relations article strong { font-size: 11px; }
.relations article small,
.relations article code,
.muted { color: #707070; font-size: 10px; }

.empty-map {
  display: grid;
  min-height: 240px;
  place-content: center;
  border: 1px dashed #333;
  border-radius: 12px;
  color: #777;
  gap: 7px;
  text-align: center;
}
.empty-map strong { color: #c9c9c9; font-size: 14px; }
.empty-map span { font-size: 12px; }

@media (max-width: 900px) {
  .map-workbench { grid-template-columns: 150px 1fr; }
  .evidence-rail { grid-column: 1 / -1; border-top: 1px solid #292929; }
}

@media (max-width: 620px) {
  .map-heading { align-items: start; flex-direction: column; }
  .map-stats { width: 100%; }
  .map-workbench { display: block; }
  .kind-filter { display: flex; overflow-x: auto; border-right: 0; border-bottom: 1px solid #292929; }
  .kind-filter button { width: auto; min-width: max-content; gap: 10px; }
  .node-list { border-right: 0; }
}
</style>
