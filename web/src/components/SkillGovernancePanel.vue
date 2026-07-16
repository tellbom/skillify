<script setup>
import { ref } from 'vue'
import { reportSkillSignal } from '../lib/api.js'

const props = defineProps({ namespace: String, name: String, version: String, governance: { type: Object, required: true } })
const sent = ref('')
const error = ref('')

async function signal(eventType, success) {
  error.value = ''
  try {
    await reportSkillSignal(props.namespace, props.name, props.version, eventType, success)
    sent.value = eventType
  } catch (err) {
    error.value = err.message
  }
}
</script>

<template>
  <section class="governance-panel" data-testid="governance-panel">
    <header><div><p>VERIFIED CAPABILITY PROFILE</p><h2>兼容性与验收证据</h2></div><span class="scan" :class="governance.scanStatus">{{ governance.scanStatus }}</span></header>
    <div class="governance-grid">
      <div><h3>执行器</h3><span v-for="item in governance.compatibleExecutors" :key="item" class="chip">{{ item }}</span><em v-if="!governance.compatibleExecutors.length">未报告</em></div>
      <div><h3>所需 MCP</h3><span v-for="item in governance.requiredMcp" :key="item" class="chip">{{ item }}</span><em v-if="!governance.requiredMcp.length">无</em></div>
      <div><h3>权限摘要</h3><span v-for="item in governance.permissions" :key="item" class="chip permission">{{ item }}</span><em v-if="!governance.permissions.length">未报告</em></div>
    </div>
    <div class="acceptance">
      <template v-if="governance.sampleSize > 0">
        <div><strong>{{ Math.round(governance.successRate * 100) }}%</strong><span>成功率 · {{ governance.sampleSize }} 次</span></div>
        <div><strong>{{ Math.round(governance.testPassRate * 100) }}%</strong><span>测试通过率</span></div>
      </template>
      <p v-else>暂无真实运行样本，不展示推测百分比。</p>
      <small>任务内容默认不采集：{{ governance.taskContentCollected ? '否' : '是' }}</small>
    </div>
    <div v-if="governance.examples.length" class="examples"><h3>示例</h3><p v-for="item in governance.examples" :key="item">{{ item }}</p></div>
    <footer>
      <span>匿名结果反馈</span>
      <button type="button" @click="signal('install')">已安装</button>
      <button type="button" @click="signal('run', true)">使用成功</button>
      <button type="button" @click="signal('uninstall')">已卸载</button>
      <span v-if="sent" class="sent">已记录 {{ sent }}</span>
      <span v-if="error" class="error">{{ error }}</span>
    </footer>
  </section>
</template>

<style scoped>
.governance-panel { margin-bottom: 18px; padding: 18px; border: 1px solid #2c2c2c; border-radius: 12px; background: #181818; }
header { display: flex; align-items: start; justify-content: space-between; margin-bottom: 17px; }
header p { margin: 0 0 5px; color: #80cbc4; font: 650 9px ui-monospace, monospace; letter-spacing: 1.3px; }
h2 { margin: 0; font-size: 15px; } h3 { margin: 0 0 7px; color: #777; font-size: 10px; text-transform: uppercase; }
.scan { padding: 4px 7px; border: 1px solid #383838; border-radius: 999px; color: #999; font: 600 9px ui-monospace, monospace; }
.scan.passed { border-color: rgb(128 203 196 / 30%); color: #80cbc4; }
.governance-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.chip { display: inline-block; margin: 0 5px 5px 0; padding: 4px 6px; border-radius: 5px; color: #bbb; background: #242424; font-size: 10px; }
.chip.permission { color: #dfb87f; } em { color: #666; font-size: 10px; font-style: normal; } code { display: block; margin-bottom: 4px; color: #9bbfbc; font-size: 10px; }
.acceptance { display: flex; align-items: center; margin-top: 14px; padding-top: 13px; border-top: 1px solid #292929; gap: 22px; }
.acceptance div { display: grid; }.acceptance strong { font: 650 18px ui-monospace, monospace; }.acceptance span, .acceptance p, .acceptance small { color: #777; font-size: 10px; }.acceptance p { flex: 1; margin: 0; }.acceptance small { margin-left: auto; }
.examples { margin-top: 12px; }.examples p { margin: 3px 0; color: #999; font-size: 11px; }
footer { display: flex; align-items: center; margin-top: 14px; gap: 7px; color: #777; font-size: 10px; }
footer button { padding: 5px 8px; border: 1px solid #333; border-radius: 5px; color: #aaa; background: transparent; cursor: pointer; font: inherit; }.sent { color: #80cbc4; }.error { color: #e5807a; }
@media (max-width: 760px) { .governance-grid { grid-template-columns: repeat(2, 1fr); } footer { flex-wrap: wrap; } }
</style>
