<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { renderMarkdown } from '../../lib/markdown.js'

const props = defineProps({
  manifestYaml: { type: String, default: '' },
  skillMd: { type: String, default: '' },
  tree: { type: Array, default: () => [] },
  issues: { type: Array, default: () => [] },
  publishable: { type: Boolean, default: false },
  expiresAt: { type: String, default: '' },
})

const { t } = useI18n()

// renderMarkdown() is async (lazy-loads the shiki highlighter) — resolve into a ref rather
// than binding the Promise itself to v-html, matching SkillDetailView.vue's pattern.
const skillMdHtml = ref('')
watch(
  () => props.skillMd,
  async (value) => {
    skillMdHtml.value = await renderMarkdown(value)
  },
  { immediate: true },
)
</script>

<template>
  <div class="build-preview-panel">
    <div v-if="issues.length" class="issues-card">
      <strong>{{ t('upload.workspace.issuesHeading') }}</strong>
      <ul><li v-for="(issue, index) in issues" :key="index">{{ issue.path }}: {{ issue.message }}</li></ul>
    </div>
    <p v-else class="issues-none">✓ {{ t('upload.workspace.issuesNone') }}</p>

    <p v-if="!publishable" class="not-publishable">{{ t('upload.workspace.notPublishable') }}</p>

    <div class="preview-grid">
      <section>
        <h4>{{ t('upload.workspace.manifestYamlHeading') }}</h4>
        <pre class="code-block">{{ manifestYaml }}</pre>
      </section>
      <section>
        <h4>{{ t('upload.workspace.treeHeading') }}</h4>
        <div class="tree-panel">
          <ul class="tree-list">
            <li v-for="item in tree" :key="item.path">
              <span class="tree-glyph">{{ item.type === 'directory' ? '▿' : '□' }}</span>
              <code>{{ item.path }}</code>
              <small v-if="item.path === 'SKILL.md' || item.path === 'skill.yaml'">保留</small>
            </li>
          </ul>
        </div>
      </section>
    </div>

    <section class="markdown-section">
      <h4>{{ t('upload.workspace.skillMdHeading') }}（最终内容）</h4>
      <div class="markdown-preview" v-html="skillMdHtml"></div>
    </section>
  </div>
</template>

<style scoped>
.build-preview-panel { display: flex; gap: 18px; flex-direction: column; }
h4 { margin: 0 0 8px; color: #9f9f9f; font-size: 12px; font-weight: 550; }
.issues-card, .not-publishable { padding: 11px 14px; border: 1px solid rgb(229 128 122 / 30%); border-radius: 9px; color: #edb4b0; background: rgb(229 128 122 / 5%); font-size: 12px; }
.issues-card strong { display: block; margin-bottom: 5px; }
.issues-card ul { margin: 0; padding-left: 18px; }
.issues-none { width: max-content; margin: 0; padding: 4px 9px; border-radius: 6px; color: #79c89b; background: rgb(95 184 142 / 7%); font-size: 11.5px; }
.not-publishable { margin: 0; border-color: rgb(224 164 88 / 30%); color: #e0a458; background: rgb(224 164 88 / 5%); }
.preview-grid { display: grid; align-items: start; gap: 20px; grid-template-columns: 1fr 1fr; }
.code-block, .tree-panel, .markdown-preview { box-sizing: border-box; margin: 0; border: 1px solid #2c2c2c; border-radius: 9px; background: #141414; }
.code-block { overflow: auto; height: 310px; padding: 16px; color: #cfe9e5; font: 12px/1.6 ui-monospace, Menlo, monospace; white-space: pre; }
.tree-panel { min-height: 174px; padding: 14px 16px; }
.tree-list { display: flex; margin: 0; padding: 0; list-style: none; gap: 9px; flex-direction: column; }
.tree-list li { display: flex; align-items: center; min-width: 0; color: #9f9f9f; font-size: 12px; gap: 8px; }
.tree-list code { overflow: hidden; color: #aaa; font: 12px ui-monospace, Menlo, monospace; text-overflow: ellipsis; white-space: nowrap; }
.tree-list small { margin-left: auto; color: #555; font-size: 10px; }
.tree-glyph { color: #606060; }
.markdown-section { min-width: 0; }
.markdown-preview { overflow: auto; max-height: 420px; padding: 16px 18px; color: #c9c9c9; font-size: 12.5px; line-height: 1.65; }
.markdown-preview :deep(:first-child) { margin-top: 0; }
.markdown-preview :deep(:last-child) { margin-bottom: 0; }
@media (max-width: 760px) { .preview-grid { grid-template-columns: 1fr; } .code-block { height: 240px; } }
</style>
