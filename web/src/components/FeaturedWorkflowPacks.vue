<script setup>
const packs = [
  { name: 'Project Onboarding', flow: '分析 → 架构 → 风险与测试' },
  { name: 'Evidence Bugfix', flow: '复现 → 根因 → 实现 → 测试 → Review' },
  { name: 'Feature Development', flow: '澄清 → 定位 → 审批 → TDD' },
]
</script>

<template>
  <section class="featured-packs" data-testid="featured-packs">
    <header><span>TEAM CURATED</span><strong>团队精选 Workflow Packs</strong></header>
    <div><article v-for="pack in packs" :key="pack.name"><strong>{{ pack.name }}</strong><small>{{ pack.flow }}</small></article></div>
  </section>
</template>

<style scoped>
.featured-packs { margin-bottom: 18px; padding: 14px 16px; border: 1px solid rgb(128 203 196 / 18%); border-radius: 10px; background: rgb(128 203 196 / 4%); }
header { display: flex; align-items: center; margin-bottom: 10px; gap: 9px; } header span { color: #80cbc4; font: 650 9px ui-monospace, monospace; letter-spacing: 1px; } header strong { font-size: 12px; }
.featured-packs > div { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; } article { display: grid; padding: 9px; border-radius: 6px; background: #191b1b; gap: 3px; } article strong { font-size: 11px; } article small { color: #777; font-size: 9px; }
@media (max-width: 700px) { .featured-packs > div { grid-template-columns: 1fr; } }
</style>
