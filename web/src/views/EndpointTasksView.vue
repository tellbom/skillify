<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  confirmTaskWorkPackages, dispatchEndpointTask, getEndpointTasks, getMyEndpoints,
  updateTaskWorkPackages,
} from '../lib/api.js'

const WORKFLOWS = [
  { id: 'project-onboarding', label: 'Project Onboarding', field: 'focus', fieldLabel: '关注范围（可选）', required: false },
  { id: 'evidence-bugfix', label: 'Bugfix', field: 'issueReference', fieldLabel: 'Issue 编号或链接', required: true },
  { id: 'feature-development', label: 'Feature', field: 'title', fieldLabel: '特性标题', required: true },
  { id: 'evidence-review', label: 'Review', field: 'changeReference', fieldLabel: '变更编号或分支', required: true },
  { id: 'behavior-preserving-refactor', label: 'Refactor', field: 'target', fieldLabel: '重构目标模块', required: true },
  { id: 'local-doc-search', label: '本地文档检索', field: 'query', fieldLabel: '检索内容', required: true, app: 'search' },
  { id: 'file-processing', label: '文本 / CSV 批处理', field: '', fieldLabel: '', required: false, app: 'processing' },
]

const endpoints = ref([])
const tasks = ref([])
const loading = ref(true)
const submitting = ref(false)
const codemapSubmitting = ref(null)
const error = ref('')
const TEAM_ENABLED = import.meta.env.VITE_SHOGUN_TEAM_ENABLED === 'true'
const form = reactive({
  endpointId: '', workspaceAlias: '', runtime: 'opencode', executionMode: 'single',
  workflowId: 'evidence-bugfix', value: '', processor: 'word-frequency',
  groupBy: '', valueColumn: '', operation: 'sum',
})

function workerLabel(workerId) {
  if (!workerId) return ''
  if (workerId === 'karo' || workerId === 'coordinator') return 'Coordinator'
  if (workerId === 'gunshi') return 'Reviewer'
  const match = /^ashigaru(\d+)$/.exec(workerId)
  return match ? `Worker ${match[1]}` : workerId
}

function editableTask(task) {
  return {
    ...task,
    workPackages: (task.workPackages || []).map((item) => ({
      ...item, pathsText: (item.allowedPaths || []).join(', '),
    })),
  }
}

const selectedEndpoint = computed(() => endpoints.value.find((item) => item.endpointId === form.endpointId))
const selectedWorkflow = computed(() => WORKFLOWS.find((item) => item.id === form.workflowId))
const canSubmit = computed(() => Boolean(
  selectedEndpoint.value?.online && form.workspaceAlias &&
  (!selectedWorkflow.value.required || form.value.trim()) &&
  (selectedWorkflow.value.app !== 'processing' || form.processor === 'word-frequency' ||
    (form.groupBy.trim() && form.valueColumn.trim())),
))
const canUseCodemap = computed(() => Boolean(selectedEndpoint.value?.online && form.workspaceAlias))

watch(selectedEndpoint, (endpoint) => {
  form.workspaceAlias = endpoint?.workspaceAliases?.[0] || ''
})
watch(() => form.workflowId, () => { form.value = '' })

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [endpointRows, taskRows] = await Promise.all([getMyEndpoints(), getEndpointTasks()])
    endpoints.value = endpointRows
    tasks.value = taskRows.map(editableTask)
    form.endpointId = endpointRows.find((item) => item.online)?.endpointId || endpointRows[0]?.endpointId || ''
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = ''
  const workflow = selectedWorkflow.value
  const inputs = form.value.trim() ? { [workflow.field]: form.value.trim() } : {}
  if (workflow.id === 'feature-development') inputs.acceptanceCriteria = [form.value.trim()]
  if (workflow.id === 'local-doc-search') Object.assign(inputs, {
    directoryAlias: form.workspaceAlias, mode: 'fulltext',
  })
  if (workflow.id === 'file-processing') {
    Object.assign(inputs, { inputAlias: form.workspaceAlias, processor: form.processor })
    if (form.processor === 'csv-summary') Object.assign(inputs, {
      groupBy: form.groupBy.trim(), valueColumn: form.valueColumn.trim(), operation: form.operation,
    })
  }
  try {
    const task = await dispatchEndpointTask({
      endpointId: form.endpointId,
      workspaceAlias: form.workspaceAlias,
      runtime: form.runtime,
      executionMode: form.executionMode,
      preferredCli: form.executionMode === 'team' ? form.runtime : null,
      teamPolicy: form.executionMode === 'team' ? {
        min_workers: 2,
        max_active_workers: 3,
        max_parallel_model_calls: 2,
        max_team_duration_minutes: 120,
        require_independent_review: true,
      } : {},
      workflowId: form.workflowId,
      workflowVersion: '1.0.0',
      inputs,
    })
    tasks.value.unshift(editableTask(task))
    form.value = ''
  } catch (err) {
    error.value = err.message
  } finally {
    submitting.value = false
  }
}

async function runCodemapAction(action) {
  if (!canUseCodemap.value || codemapSubmitting.value) return
  codemapSubmitting.value = action
  error.value = ''
  try {
    const task = await dispatchEndpointTask({
      endpointId: form.endpointId,
      workspaceAlias: form.workspaceAlias,
      runtime: 'codemap',
      workflowId: `codemap.visualization.${action}`,
      workflowVersion: '1.0.0',
      inputs: {},
    })
    tasks.value.unshift(editableTask(task))
  } catch (err) {
    error.value = err.message
  } finally {
    codemapSubmitting.value = null
  }
}

async function savePackages(task) {
  error.value = ''
  try {
    const packages = task.workPackages.map(({ pathsText, ...item }) => ({
      ...item,
      allowedPaths: pathsText.split(',').map((value) => value.trim()).filter(Boolean),
      confirmed: false,
    }))
    const result = await updateTaskWorkPackages(task.taskId, packages)
    task.workPackages = editableTask({ workPackages: result.packages }).workPackages
  } catch (err) {
    error.value = err.message
  }
}

async function confirmPackages(task) {
  error.value = ''
  try {
    const result = await confirmTaskWorkPackages(task.taskId)
    task.workPackages = editableTask({ workPackages: result.packages }).workPackages
  } catch (err) {
    error.value = err.message
  }
}

onMounted(load)
</script>

<template>
  <main class="task-page">
    <header class="task-heading">
      <div><p class="eyebrow">GOVERNED ENDPOINT WORK</p><h1>本地 Agent 任务</h1></div>
      <p>选择固定 Workflow，任务需在你的在线端点确认后执行。</p>
    </header>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <div v-if="loading" class="state-card">正在载入端点…</div>
    <template v-else>
      <section class="codemap-card" aria-labelledby="codemap-title">
        <div class="codemap-intro">
          <p class="eyebrow">LOCAL CODE ATLAS</p>
          <h2 id="codemap-title">在代码所在机器打开关系图</h2>
          <p>GitNexus 只扫描本机快照。图谱和源码不会传回 Skillify。</p>
        </div>
        <div class="codemap-context">
          <span>{{ selectedEndpoint?.label || '未选择端点' }}</span>
          <strong>{{ form.workspaceAlias || '未选择工作区' }}</strong>
          <small>GitNexus 1.6.9 · 仅限个人非商业使用</small>
        </div>
        <div class="codemap-actions" aria-label="Code Map actions">
          <button type="button" :disabled="!canUseCodemap || codemapSubmitting" data-testid="codemap-start" @click="runCodemapAction('start')">
            {{ codemapSubmitting === 'start' ? '建立索引中…' : '启动地图' }}
          </button>
          <button type="button" :disabled="!canUseCodemap || codemapSubmitting" @click="runCodemapAction('open')">在端点打开</button>
          <button type="button" :disabled="!canUseCodemap || codemapSubmitting" @click="runCodemapAction('status')">刷新状态</button>
          <button type="button" class="quiet" :disabled="!canUseCodemap || codemapSubmitting" @click="runCodemapAction('stop')">停止</button>
        </div>
      </section>

      <section class="dispatch-card" aria-labelledby="dispatch-title">
        <div class="section-title"><span>01</span><div><h2 id="dispatch-title">创建受控任务</h2><p>不支持任意 Prompt 或 Shell 命令</p></div></div>
        <form @submit.prevent="submit">
          <label>执行端点
            <select v-model="form.endpointId" data-testid="endpoint-select">
              <option v-for="endpoint in endpoints" :key="endpoint.endpointId" :value="endpoint.endpointId" :disabled="!endpoint.online">
                {{ endpoint.label }} · {{ endpoint.online ? '在线' : '离线' }}
              </option>
            </select>
          </label>
          <label>工作区
            <select v-model="form.workspaceAlias" data-testid="workspace-select">
              <option v-for="alias in selectedEndpoint?.workspaceAliases || []" :key="alias" :value="alias">{{ alias }}</option>
            </select>
          </label>
          <label>执行器
            <select v-model="form.runtime" data-testid="runtime-select">
              <option value="opencode">OpenCode</option>
              <option value="claude-code">Claude Code</option>
            </select>
          </label>
          <label>执行模式
            <select v-model="form.executionMode" data-testid="execution-mode-select">
              <option value="single">Single</option>
              <option value="delegated">Delegated</option>
              <option value="team" :disabled="!TEAM_ENABLED">Team {{ TEAM_ENABLED ? '' : '（待测试环境验收）' }}</option>
            </select>
          </label>
          <label>Workflow
            <select v-model="form.workflowId" data-testid="workflow-select">
              <option v-for="workflow in WORKFLOWS" :key="workflow.id" :value="workflow.id">{{ workflow.label }}</option>
            </select>
          </label>
          <label v-if="selectedWorkflow.app !== 'processing'">{{ selectedWorkflow.fieldLabel }}
            <input v-model="form.value" :required="selectedWorkflow.required" maxlength="500" data-testid="workflow-input">
          </label>
          <template v-else>
            <label>处理方式
              <select v-model="form.processor" data-testid="app-processor">
                <option value="word-frequency">文本词频</option><option value="csv-summary">CSV 汇总</option>
              </select>
            </label>
            <template v-if="form.processor === 'csv-summary'">
              <label>分组列<input v-model="form.groupBy" maxlength="128" required></label>
              <label>数值列<input v-model="form.valueColumn" maxlength="128" required></label>
              <label>操作<select v-model="form.operation"><option value="sum">求和</option><option value="count">计数</option><option value="average">平均值</option></select></label>
            </template>
          </template>
          <button type="submit" :disabled="!canSubmit || submitting">{{ submitting ? '下达中…' : '提交并等待端点确认' }}</button>
        </form>
      </section>

      <section class="task-list" aria-labelledby="task-list-title">
        <div class="section-title"><span>02</span><div><h2 id="task-list-title">任务时间线</h2><p>仅展示可验证事件、构件和失败原因</p></div></div>
        <article v-for="task in tasks" :key="task.taskId" class="task-row">
          <div class="task-summary">
            <span class="status-dot" :class="task.state" />
            <div><strong>{{ task.workflowId }}</strong><small>{{ task.executionMode || 'single' }} · {{ task.preferredCli || task.runtime }}</small><code>{{ task.taskId }}</code></div>
            <span class="state-pill">{{ task.state }}</span>
          </div>
          <section v-if="!task.workflowId.startsWith('codemap.') && !['local-doc-search', 'file-processing'].includes(task.workflowId) && task.workPackages?.length" class="work-packages">
            <header><strong>协作工作包</strong><span>确认后由所选执行器管理 Agent</span></header>
            <div v-for="item in task.workPackages" :key="item.packageId" class="work-package">
              <label>目标<input v-model="item.objective" data-testid="package-objective"></label>
              <label>允许路径<input v-model="item.pathsText" data-testid="package-paths"></label>
              <label>权限
                <select v-model="item.access"><option value="read">只读</option><option value="write">读写</option></select>
              </label>
              <label class="parallel"><input v-model="item.parallelizable" type="checkbox">可并行</label>
              <label class="parallel"><input v-model="item.readOnly" type="checkbox">只读</label>
            </div>
            <div class="package-actions">
              <button type="button" @click="savePackages(task)">保存工作包</button>
              <button v-if="task.workPackages.some((item) => !item.confirmed)" type="button" data-testid="confirm-packages" @click="confirmPackages(task)">确认委派</button>
              <span v-else>已确认</span>
            </div>
          </section>
          <ol v-if="task.events?.length" class="timeline">
            <li v-for="event in task.events" :key="`${event.eventType}-${event.occurredAt}`">
              <div><strong>{{ event.eventType }} <em v-if="event.workerId">· {{ workerLabel(event.workerId) }}</em></strong><time>{{ event.occurredAt }}</time></div>
              <p v-if="event.summary">{{ event.summary }}</p>
              <p v-if="event.failureReason" class="failure">{{ event.failureReason }}</p>
              <p v-if="event.testSummary" class="evidence">
                Tests: {{ event.testSummary.passed || 0 }} passed · {{ event.testSummary.failed || 0 }} failed · {{ event.testSummary.skipped || 0 }} skipped
              </p>
              <p v-if="event.diffStats" class="evidence">
                Diff: {{ event.diffStats.filesChanged || 0 }} files · +{{ event.diffStats.insertions || 0 }} / -{{ event.diffStats.deletions || 0 }}
              </p>
              <code v-for="artifact in event.artifacts || []" :key="artifact.artifactId">{{ artifact.kind }}:{{ artifact.artifactId }}</code>
            </li>
          </ol>
          <p v-else class="waiting">等待端点确认并上报首个事件。</p>
        </article>
        <div v-if="!tasks.length" class="state-card">尚无端点任务。</div>
      </section>
    </template>
  </main>
</template>

<style scoped>
.task-page { color: #e8e8e8; animation: page-in .25s ease both; }
.task-heading { display: flex; align-items: end; justify-content: space-between; margin-bottom: 20px; gap: 24px; }
.task-heading h1 { margin: 0; font-size: 26px; letter-spacing: -.4px; }
.task-heading > p { margin: 0; color: #858585; font-size: 12px; }
.eyebrow { margin: 0 0 7px; color: #80cbc4; font: 650 10px ui-monospace, monospace; letter-spacing: 1.4px; }
.dispatch-card, .task-list { padding: 20px; border: 1px solid #2c2c2c; border-radius: 12px; background: #181818; }
.codemap-card { display: grid; grid-template-columns: minmax(260px, 1.4fr) minmax(190px, .8fr) auto; align-items: center; margin-bottom: 16px; padding: 22px; overflow: hidden; border: 1px solid #30504c; border-radius: 12px; background: linear-gradient(112deg, #17201f 0%, #181818 58%); gap: 24px; }
.codemap-intro h2 { margin: 0 0 7px; color: #f0f5f4; font-size: 19px; letter-spacing: -.25px; }
.codemap-intro > p:last-child { margin: 0; color: #82918f; font-size: 11px; }
.codemap-context { display: grid; padding-left: 18px; border-left: 1px solid #2b403d; gap: 4px; }
.codemap-context span, .codemap-context small { color: #70817f; font-size: 10px; }
.codemap-context strong { color: #9fd8d1; font: 600 13px ui-monospace, monospace; }
.codemap-actions { display: grid; grid-template-columns: repeat(2, minmax(94px, 1fr)); gap: 7px; }
.codemap-actions button { min-height: 34px; padding: 0 11px; border: 1px solid #3b625d; border-radius: 6px; color: #c3e4e0; background: #203632; font-size: 11px; cursor: pointer; }
.codemap-actions button:first-child { border-color: #80cbc4; color: #10201f; background: #80cbc4; font-weight: 650; }
.codemap-actions button.quiet { color: #9a8585; border-color: #493535; background: #251c1c; }
.codemap-actions button:disabled { opacity: .45; cursor: not-allowed; }
.task-list { margin-top: 16px; }
.section-title { display: flex; align-items: start; margin-bottom: 18px; gap: 11px; }
.section-title > span { color: #80cbc4; font: 600 10px ui-monospace, monospace; }
.section-title h2 { margin: 0 0 3px; font-size: 15px; }
.section-title p { margin: 0; color: #777; font-size: 11px; }
form { display: grid; align-items: end; grid-template-columns: repeat(5, minmax(120px, 1fr)) auto; gap: 12px; }
label { display: grid; color: #858585; font-size: 11px; gap: 6px; }
select, input { width: 100%; min-height: 36px; padding: 0 10px; border: 1px solid #333; border-radius: 6px; box-sizing: border-box; color: #ddd; background: #141414; font: inherit; }
select:focus, input:focus { border-color: #80cbc4; outline: none; }
form button { min-height: 36px; padding: 0 15px; border: 0; border-radius: 6px; color: #10201f; background: #80cbc4; font-weight: 650; cursor: pointer; }
form button:disabled { color: #777; background: #292929; cursor: not-allowed; }
.task-row { padding: 15px 0; border-top: 1px solid #292929; }
.task-summary { display: flex; align-items: center; gap: 10px; }
.task-summary > div { display: grid; flex: 1; gap: 3px; }
.task-summary strong { font-size: 13px; }
.task-summary small { color: #80cbc4; font: 9px ui-monospace, monospace; }
.task-summary code { color: #666; font-size: 9px; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: #f0b86e; box-shadow: 0 0 0 4px rgb(240 184 110 / 8%); }
.status-dot.succeeded { background: #80cbc4; }
.status-dot.failed, .status-dot.rejected { background: #ef8d8d; }
.state-pill { padding: 4px 7px; border: 1px solid #333; border-radius: 999px; color: #999; font: 600 9px ui-monospace, monospace; text-transform: uppercase; }
.work-packages { margin: 14px 0 0 17px; padding: 12px; border: 1px solid #2d3d3b; border-radius: 8px; background: #151b1a; }
.work-packages header { display: flex; justify-content: space-between; margin-bottom: 10px; color: #80cbc4; font-size: 11px; }
.work-packages header span { color: #777; }
.work-package { display: grid; grid-template-columns: 2fr 2fr 1fr auto; align-items: end; gap: 8px; }
.parallel { display: flex; align-items: center; min-height: 36px; }.parallel input { width: auto; min-height: 0; }
.package-actions { display: flex; justify-content: end; margin-top: 9px; gap: 8px; }
.package-actions button { padding: 6px 10px; border: 1px solid #3a4d4a; border-radius: 5px; color: #b9d9d6; background: #1b2927; cursor: pointer; }
.package-actions span { color: #80cbc4; font-size: 10px; }
.timeline { margin: 14px 0 0 3px; padding-left: 19px; border-left: 1px solid #333; list-style: none; }
.timeline li { position: relative; padding: 0 0 13px 4px; }
.timeline li::before { position: absolute; top: 4px; left: -24px; width: 7px; height: 7px; border: 2px solid #181818; border-radius: 50%; background: #666; content: ''; }
.timeline div { display: flex; justify-content: space-between; gap: 12px; }
.timeline strong { font-size: 11px; }
.timeline time, .timeline p, .timeline code, .waiting { color: #707070; font-size: 10px; }
.timeline p { margin: 4px 0; }.timeline .failure { color: #ef8d8d; }.timeline code { margin-right: 8px; color: #9bbfbc; }
.timeline .evidence { color: #a9a9a9; font-family: ui-monospace, monospace; }
.waiting { margin: 10px 0 0 17px; }
.state-card { padding: 28px; border: 1px dashed #333; border-radius: 10px; color: #777; text-align: center; }
.error-banner { padding: 10px 12px; border: 1px solid rgb(239 141 141 / 30%); border-radius: 7px; color: #efaaaa; background: rgb(239 141 141 / 6%); font-size: 12px; }
@media (max-width: 1050px) { form { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 900px) { .codemap-card { grid-template-columns: 1fr 1fr; }.codemap-actions { grid-column: 1 / -1; } }
@media (max-width: 620px) { .task-heading { align-items: start; flex-direction: column; } .codemap-card { grid-template-columns: 1fr; }.codemap-context { padding: 0; border: 0; }.codemap-actions { grid-column: auto; } form { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .task-page { animation: none; } }
</style>
