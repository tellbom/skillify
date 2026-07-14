<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RUNTIME_OPTIONS, TARGET_OPTIONS, dedupeList } from '../../lib/skillBuilds.js'

const props = defineProps({
  manifest: { type: Object, required: true },
  section: { type: String, default: 'basic' },
  missingFields: { type: Array, default: () => [] },
  unconfirmedFields: { type: Array, default: () => [] },
  detectedFacts: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['change'])
const { t } = useI18n()

const LICENSE_OPTIONS = ['MIT', 'Apache-2.0', 'BSD-3-Clause', 'Proprietary']
const listDrafts = ref({
  'dependencies.python': '',
  'dependencies.system': '',
  'dependencies.skills': '',
  permissions: '',
  tags: '',
})

function isMissing(field) { return props.missingFields.includes(field) }
function isUnconfirmed(field) { return props.unconfirmedFields.includes(field) }
function detectedFactFor(field) { return props.detectedFacts ? props.detectedFacts[field] : undefined }
function setField(field, value) { emit('change', { ...props.manifest, [field]: value }) }
function setDependencyField(field, value) {
  emit('change', { ...props.manifest, dependencies: { ...props.manifest.dependencies, [field]: value } })
}
function authorDisplay() {
  const author = props.manifest.author
  if (typeof author === 'string') return author
  if (author && typeof author === 'object') return author.name || ''
  return ''
}
function toggleTarget(target) {
  const targets = props.manifest.targets.includes(target)
    ? props.manifest.targets.filter((item) => item !== target)
    : [...props.manifest.targets, target]
  setField('targets', targets)
}
function currentList(listKey) {
  return listKey.startsWith('dependencies.')
    ? props.manifest.dependencies[listKey.split('.')[1]]
    : props.manifest[listKey]
}
function addListItem(listKey) {
  const value = listDrafts.value[listKey].trim()
  if (!value) return
  const next = dedupeList([...currentList(listKey), value])
  if (listKey.startsWith('dependencies.')) setDependencyField(listKey.split('.')[1], next)
  else setField(listKey, next)
  listDrafts.value[listKey] = ''
}
function removeListItem(listKey, item) {
  const next = currentList(listKey).filter((value) => value !== item)
  if (listKey.startsWith('dependencies.')) setDependencyField(listKey.split('.')[1], next)
  else setField(listKey, next)
}
</script>

<template>
  <div class="manifest-form">
    <template v-if="section === 'runtime'">
      <div class="section-intro">
        <h3>技能类型与运行目标</h3>
        <p>技能类型（runtime）决定它在何种 Agent Skill 规范下运行；目标平台（targets）表示计划使用它的 Agent 环境。</p>
      </div>
      <div class="form-stack narrow">
        <div class="field">
          <label>{{ t('upload.workspace.runtime') }}<span v-if="isMissing('runtime')" class="badge missing">{{ t('upload.workspace.missingBadge') }}</span><span v-else-if="isUnconfirmed('runtime')" class="badge pending">{{ t('upload.workspace.unconfirmedBadge') }}</span></label>
          <select :value="manifest.runtime" @change="setField('runtime', $event.target.value)">
            <option value="">{{ t('upload.workspace.runtimePlaceholder') }}</option>
            <option v-for="option in RUNTIME_OPTIONS" :key="option" :value="option">{{ option }}</option>
          </select>
        </div>
        <div class="field">
          <label>{{ t('upload.workspace.targets') }}<span v-if="isMissing('targets')" class="badge missing">{{ t('upload.workspace.missingBadge') }}</span><span v-else-if="isUnconfirmed('targets')" class="badge pending">{{ t('upload.workspace.unconfirmedBadge') }}</span></label>
          <div class="target-grid">
            <label v-for="option in TARGET_OPTIONS" :key="option" class="target-option" :class="{ selected: manifest.targets.includes(option) }">
              <input type="checkbox" :checked="manifest.targets.includes(option)" @change="toggleTarget(option)" />
              <span class="check-box">✓</span>{{ option }}
            </label>
          </div>
        </div>
      </div>
    </template>

    <template v-else-if="section === 'basic'">
      <div class="section-intro"><h3>基础信息</h3></div>
      <div class="form-stack basic-fields">
        <div class="field">
          <label>{{ t('upload.workspace.namespace') }}<span v-if="isMissing('namespace')" class="badge missing">{{ t('upload.workspace.missingBadge') }}</span><span v-else-if="isUnconfirmed('namespace')" class="badge pending">{{ t('upload.workspace.unconfirmedBadge') }}</span></label>
          <input type="text" :value="manifest.namespace" placeholder="例如 data-tools" @input="setField('namespace', $event.target.value)" />
          <small>发布归属空间，首次成功发布后将绑定到发布者。</small>
        </div>
        <div class="field">
          <label>{{ t('upload.workspace.name') }}<span v-if="isMissing('name')" class="badge missing">{{ t('upload.workspace.missingBadge') }}</span><span v-else-if="isUnconfirmed('name')" class="badge pending">{{ t('upload.workspace.unconfirmedBadge') }}</span></label>
          <input type="text" :value="manifest.name" placeholder="例如 csv-cleaner" @input="setField('name', $event.target.value)" />
          <small v-if="detectedFactFor('name')" class="detected">{{ t('upload.workspace.detectedFactPrefix') }}{{ detectedFactFor('name') }}</small>
          <small v-else>稳定的机器标识，不应作为可随意更改的展示标题。</small>
        </div>
        <div class="field">
          <label>{{ t('upload.workspace.version') }}<span v-if="isMissing('version')" class="badge missing">{{ t('upload.workspace.missingBadge') }}</span><span v-else-if="isUnconfirmed('version')" class="badge pending">{{ t('upload.workspace.unconfirmedBadge') }}</span></label>
          <input type="text" :value="manifest.version" placeholder="例如 1.0.0" @input="setField('version', $event.target.value)" />
          <small>语义化版本：主版本、次版本、修订号。</small>
        </div>
        <div class="field">
          <label>{{ t('upload.workspace.description') }}<span v-if="isMissing('description')" class="badge missing">{{ t('upload.workspace.missingBadge') }}</span><span v-else-if="isUnconfirmed('description')" class="badge pending">{{ t('upload.workspace.unconfirmedBadge') }}</span></label>
          <textarea rows="3" :value="manifest.description" placeholder="用一句话说明这个技能解决什么问题" @input="setField('description', $event.target.value)" />
          <small v-if="detectedFactFor('description')" class="detected">{{ t('upload.workspace.detectedFactPrefix') }}{{ detectedFactFor('description') }}</small>
        </div>
        <div class="field">
          <label>{{ t('upload.workspace.author') }}<span v-if="isMissing('author')" class="badge missing">{{ t('upload.workspace.missingBadge') }}</span><span v-else-if="isUnconfirmed('author')" class="badge pending">{{ t('upload.workspace.unconfirmedBadge') }}</span></label>
          <input type="text" :value="authorDisplay()" placeholder="填写作者用户名" @input="setField('author', $event.target.value)" />
          <small>该字段决定“个人空间”中的归属显示，请确认无误后填写。</small>
        </div>
        <div class="field">
          <label>{{ t('upload.workspace.license') }}<span v-if="isMissing('license')" class="badge missing">{{ t('upload.workspace.missingBadge') }}</span><span v-else-if="isUnconfirmed('license')" class="badge pending">{{ t('upload.workspace.unconfirmedBadge') }}</span></label>
          <select :value="manifest.license" @change="setField('license', $event.target.value)">
            <option value="">请选择许可证</option>
            <option v-for="option in LICENSE_OPTIONS" :key="option" :value="option">{{ option }}</option>
          </select>
          <small>内部工具通常使用 MIT 或 Apache-2.0；平台不会替你默认填写。</small>
        </div>
        <div class="field">
          <label>{{ t('upload.workspace.tags') }}<span v-if="isMissing('tags')" class="badge missing">{{ t('upload.workspace.missingBadge') }}</span><span v-else-if="isUnconfirmed('tags')" class="badge pending">{{ t('upload.workspace.unconfirmedBadge') }}</span></label>
          <div class="list-entry"><input v-model="listDrafts.tags" type="text" placeholder="输入后回车添加" @keydown.enter.prevent="addListItem('tags')" /><button type="button" @click="addListItem('tags')">添加</button></div>
          <div class="chip-list"><span v-for="item in currentList('tags')" :key="item" class="chip">{{ item }}<button type="button" @click="removeListItem('tags', item)">×</button></span></div>
        </div>
      </div>
    </template>

    <template v-else-if="section === 'requirements'">
      <div class="section-intro">
        <h3>依赖、权限与标签确认</h3>
        <p>允许显式提交为空。平台不会因为你可能不了解就替你推断或填写权限。</p>
      </div>
      <div class="form-stack narrow">
        <div v-for="entry in [
          { key: 'dependencies.python', label: t('upload.workspace.dependenciesPython'), hint: '执行脚本所需的 Python 包。' },
          { key: 'dependencies.system', label: t('upload.workspace.dependenciesSystem'), hint: '运行所需的操作系统级命令或软件。' },
          { key: 'dependencies.skills', label: t('upload.workspace.dependenciesSkills'), hint: '必须先安装的其他平台技能。' },
          { key: 'permissions', label: t('upload.workspace.permissions'), hint: '技能运行时需要的能力或访问边界。' },
        ]" :key="entry.key" class="field requirement-field">
          <label>{{ entry.label }}<span v-if="isMissing(entry.key)" class="badge missing">{{ t('upload.workspace.missingBadge') }}</span><span v-else-if="isUnconfirmed(entry.key)" class="badge pending">{{ t('upload.workspace.unconfirmedBadge') }}</span></label>
          <small>{{ entry.hint }}</small>
          <div class="list-entry"><input v-model="listDrafts[entry.key]" type="text" :placeholder="t('upload.workspace.listInputPlaceholder')" @keydown.enter.prevent="addListItem(entry.key)" /><button type="button" @click="addListItem(entry.key)">添加</button></div>
          <div class="chip-list"><span v-for="item in currentList(entry.key)" :key="item" class="chip">{{ item }}<button type="button" @click="removeListItem(entry.key, item)">×</button></span></div>
          <small v-if="detectedFactFor(entry.key)" class="detected">{{ t('upload.workspace.detectedFactPrefix') }}{{ detectedFactFor(entry.key) }}</small>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.manifest-form { color: #c9c9c9; }
.section-intro { margin-bottom: 20px; }
.section-intro h3 { margin: 0 0 4px; color: #ededed; font-size: 15px; font-weight: 650; }
.section-intro p { margin: 0; color: #9f9f9f; font-size: 12.5px; line-height: 1.6; }
.form-stack { display: flex; gap: 18px; flex-direction: column; }
.form-stack.narrow { max-width: 620px; }
.field label { display: flex; align-items: center; margin-bottom: 7px; color: #c9c9c9; font-size: 13px; gap: 9px; }
.field > small { display: block; margin-top: 5px; color: #6e6e6e; font-size: 11.5px; line-height: 1.45; }
.field > small.detected { color: #8fb8b3; }
input[type='text'], select, textarea { box-sizing: border-box; width: 100%; border: 1px solid #2c2c2c; border-radius: 8px; padding: 10px 12px; color: #e5e5e5; background: #1c1c1c; font: inherit; font-size: 13px; outline: none; transition: border-color 0.15s ease, box-shadow 0.15s ease; }
input[type='text'], select { height: 42px; }
textarea { min-height: 86px; resize: vertical; }
input:focus, select:focus, textarea:focus { border-color: rgb(128 203 196 / 48%); box-shadow: 0 0 0 2px rgb(128 203 196 / 7%); }
.badge { display: inline-flex; align-items: center; min-height: 20px; padding: 1px 8px; border: 1px solid; border-radius: 6px; font-size: 11px; line-height: 1.35; white-space: nowrap; }
.badge.missing { border-color: rgb(229 128 122 / 35%); color: #e5807a; background: rgb(229 128 122 / 8%); }
.badge.pending { border-color: rgb(224 164 88 / 35%); color: #e0a458; background: rgb(224 164 88 / 8%); }
.target-grid { display: flex; gap: 10px; flex-wrap: wrap; }
.target-option { display: inline-flex !important; align-items: center; margin: 0 !important; padding: 8px 14px; border: 1px solid #2c2c2c; border-radius: 8px; color: #c9c9c9; background: #1c1c1c; cursor: pointer; gap: 8px !important; }
.target-option input { position: absolute; opacity: 0; }
.check-box { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; border: 1px solid #353535; border-radius: 4px; color: transparent; font-size: 10px; }
.target-option.selected { border-color: rgb(128 203 196 / 30%); color: #cfe9e5; background: rgb(128 203 196 / 6%); }
.target-option.selected .check-box { border-color: #80cbc4; color: #10201e; background: #80cbc4; }
.list-entry { display: flex; gap: 8px; }
.list-entry input { flex: 1; }
.list-entry button { flex: none; padding: 0 16px; border: 1px solid #363636; border-radius: 8px; color: #e5e5e5; background: #232323; font: inherit; font-size: 12.5px; cursor: pointer; }
.chip-list { display: flex; margin-top: 10px; gap: 7px; flex-wrap: wrap; }
.chip { display: inline-flex; align-items: center; padding: 3px 8px 3px 10px; border: 1px solid rgb(128 203 196 / 22%); border-radius: 6px; color: #cfe9e5; background: rgb(128 203 196 / 7%); font: 11.5px ui-monospace, Menlo, monospace; gap: 6px; }
.chip button { padding: 0; border: 0; color: #729b97; background: none; font-size: 14px; cursor: pointer; }
.requirement-field { padding-bottom: 20px; border-bottom: 1px solid #272727; }
.requirement-field:last-child { padding-bottom: 0; border-bottom: 0; }
@media (max-width: 640px) { .target-option { flex: 1 1 120px; } }
</style>
