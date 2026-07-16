<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { dispatchEndpointTask, getEndpointTasks, getMyEndpoints } from '../lib/api.js'

const WORKFLOWS = [
  { id: 'project-onboarding', label: 'Project Onboarding', field: 'focus', fieldLabel: '关注范围（可选）', required: false },
  { id: 'evidence-bugfix', label: 'Bugfix', field: 'issueReference', fieldLabel: 'Issue 编号或链接', required: true },
  { id: 'feature-development', label: 'Feature', field: 'title', fieldLabel: '特性标题', required: true },
  { id: 'evidence-review', label: 'Review', field: 'changeReference', fieldLabel: '变更编号或分支', required: true },
  { id: 'behavior-preserving-refactor', label: 'Refactor', field: 'target', fieldLabel: '重构目标模块', required: true },
]

const endpoints = ref([])
const tasks = ref([])
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const form = reactive({ endpointId: '', workspaceAlias: '', workflowId: 'evidence-bugfix', value: '' })

const selectedEndpoint = computed(() => endpoints.value.find((item) => item.endpointId === form.endpointId))
const selectedWorkflow = computed(() => WORKFLOWS.find((item) => item.id === form.workflowId))
const canSubmit = computed(() => Boolean(
  selectedEndpoint.value?.online && form.workspaceAlias &&
  (!selectedWorkflow.value.required || form.value.trim()),
))

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
    tasks.value = taskRows
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
  try {
    const task = await dispatchEndpointTask({
      endpointId: form.endpointId,
      workspaceAlias: form.workspaceAlias,
      workflowId: form.workflowId,
      workflowVersion: '1.0.0',
      inputs,
    })
    tasks.value.unshift(task)
    form.value = ''
  } catch (err) {
    error.value = err.message
  } finally {
    submitting.value = false
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
          <label>Workflow
            <select v-model="form.workflowId" data-testid="workflow-select">
              <option v-for="workflow in WORKFLOWS" :key="workflow.id" :value="workflow.id">{{ workflow.label }}</option>
            </select>
          </label>
          <label>{{ selectedWorkflow.fieldLabel }}
            <input v-model="form.value" :required="selectedWorkflow.required" maxlength="500" data-testid="workflow-input">
          </label>
          <button type="submit" :disabled="!canSubmit || submitting">{{ submitting ? '下达中…' : '提交并等待端点确认' }}</button>
        </form>
      </section>

      <section class="task-list" aria-labelledby="task-list-title">
        <div class="section-title"><span>02</span><div><h2 id="task-list-title">任务时间线</h2><p>仅展示可验证事件、构件和失败原因</p></div></div>
        <article v-for="task in tasks" :key="task.taskId" class="task-row">
          <div class="task-summary">
            <span class="status-dot" :class="task.state" />
            <div><strong>{{ task.workflowId }}</strong><code>{{ task.taskId }}</code></div>
            <span class="state-pill">{{ task.state }}</span>
          </div>
          <ol v-if="task.events?.length" class="timeline">
            <li v-for="event in task.events" :key="`${event.eventType}-${event.occurredAt}`">
              <div><strong>{{ event.eventType }}</strong><time>{{ event.occurredAt }}</time></div>
              <p v-if="event.summary">{{ event.summary }}</p>
              <p v-if="event.failureReason" class="failure">{{ event.failureReason }}</p>
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
.task-list { margin-top: 16px; }
.section-title { display: flex; align-items: start; margin-bottom: 18px; gap: 11px; }
.section-title > span { color: #80cbc4; font: 600 10px ui-monospace, monospace; }
.section-title h2 { margin: 0 0 3px; font-size: 15px; }
.section-title p { margin: 0; color: #777; font-size: 11px; }
form { display: grid; align-items: end; grid-template-columns: repeat(4, minmax(130px, 1fr)) auto; gap: 12px; }
label { display: grid; color: #858585; font-size: 11px; gap: 6px; }
select, input { width: 100%; min-height: 36px; padding: 0 10px; border: 1px solid #333; border-radius: 6px; box-sizing: border-box; color: #ddd; background: #141414; font: inherit; }
select:focus, input:focus { border-color: #80cbc4; outline: none; }
form button { min-height: 36px; padding: 0 15px; border: 0; border-radius: 6px; color: #10201f; background: #80cbc4; font-weight: 650; cursor: pointer; }
form button:disabled { color: #777; background: #292929; cursor: not-allowed; }
.task-row { padding: 15px 0; border-top: 1px solid #292929; }
.task-summary { display: flex; align-items: center; gap: 10px; }
.task-summary > div { display: grid; flex: 1; gap: 3px; }
.task-summary strong { font-size: 13px; }
.task-summary code { color: #666; font-size: 9px; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: #f0b86e; box-shadow: 0 0 0 4px rgb(240 184 110 / 8%); }
.status-dot.succeeded { background: #80cbc4; }
.status-dot.failed, .status-dot.rejected { background: #ef8d8d; }
.state-pill { padding: 4px 7px; border: 1px solid #333; border-radius: 999px; color: #999; font: 600 9px ui-monospace, monospace; text-transform: uppercase; }
.timeline { margin: 14px 0 0 3px; padding-left: 19px; border-left: 1px solid #333; list-style: none; }
.timeline li { position: relative; padding: 0 0 13px 4px; }
.timeline li::before { position: absolute; top: 4px; left: -24px; width: 7px; height: 7px; border: 2px solid #181818; border-radius: 50%; background: #666; content: ''; }
.timeline div { display: flex; justify-content: space-between; gap: 12px; }
.timeline strong { font-size: 11px; }
.timeline time, .timeline p, .timeline code, .waiting { color: #707070; font-size: 10px; }
.timeline p { margin: 4px 0; }.timeline .failure { color: #ef8d8d; }.timeline code { margin-right: 8px; color: #9bbfbc; }
.waiting { margin: 10px 0 0 17px; }
.state-card { padding: 28px; border: 1px dashed #333; border-radius: 10px; color: #777; text-align: center; }
.error-banner { padding: 10px 12px; border: 1px solid rgb(239 141 141 / 30%); border-radius: 7px; color: #efaaaa; background: rgb(239 141 141 / 6%); font-size: 12px; }
@media (max-width: 1050px) { form { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 620px) { .task-heading { align-items: start; flex-direction: column; } form { grid-template-columns: 1fr; } }
</style>
