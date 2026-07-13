<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatDateTime } from '../../lib/datetime.js'
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
    <p class="expires">{{ t('upload.workspace.expiresAt', { date: formatDateTime(expiresAt) }) }}</p>

    <section>
      <h4>{{ t('upload.workspace.manifestYamlHeading') }}</h4>
      <pre class="code-block">{{ manifestYaml }}</pre>
    </section>

    <section>
      <h4>{{ t('upload.workspace.skillMdHeading') }}</h4>
      <div class="markdown-preview" v-html="skillMdHtml"></div>
    </section>

    <section>
      <h4>{{ t('upload.workspace.treeHeading') }}</h4>
      <ul class="tree-list">
        <li v-for="item in tree" :key="item.path">
          {{ item.path }}
          <span class="tree-type">({{ item.type === 'directory' ? t('upload.workspace.treeTypeDirectory') : t('upload.workspace.treeTypeFile') }})</span>
        </li>
      </ul>
    </section>

    <section>
      <h4>{{ t('upload.workspace.issuesHeading') }}</h4>
      <ul v-if="issues.length" class="issues-list">
        <li v-for="(issue, index) in issues" :key="index" class="issue-item">{{ issue.path }}: {{ issue.message }}</li>
      </ul>
      <p v-else class="issues-none">{{ t('upload.workspace.issuesNone') }}</p>
    </section>

    <p v-if="!publishable" class="not-publishable">{{ t('upload.workspace.notPublishable') }}</p>
  </div>
</template>

<style scoped>
.build-preview-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.expires {
  margin: 0;
  font-size: 0.8rem;
  color: #888;
}
h4 {
  margin: 0 0 0.4rem;
  font-size: 0.9rem;
  color: #ccc;
}
.code-block {
  background: #1c1c1c;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 0.7rem;
  font-size: 0.8rem;
  overflow-x: auto;
  white-space: pre;
}
.markdown-preview {
  background: #1c1c1c;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 0.7rem;
  font-size: 0.85rem;
}
.tree-list {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.tree-type {
  color: #888;
  font-size: 0.75rem;
}
.issues-list {
  margin: 0;
  padding-left: 1.2rem;
  color: #e06c75;
  font-size: 0.85rem;
}
.issues-none {
  margin: 0;
  color: #888;
  font-size: 0.85rem;
}
.not-publishable {
  color: #f5b942;
  font-size: 0.85rem;
  margin: 0;
}
</style>
