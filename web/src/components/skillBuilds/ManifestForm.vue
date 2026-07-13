<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RUNTIME_OPTIONS, TARGET_OPTIONS, dedupeList } from '../../lib/skillBuilds.js'

const props = defineProps({
  manifest: { type: Object, required: true },
  missingFields: { type: Array, default: () => [] },
  unconfirmedFields: { type: Array, default: () => [] },
  detectedFacts: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['change'])

const { t } = useI18n()

// Chip-list draft inputs (dependencies.python/system/skills, permissions, tags) — one text
// field per list, cleared after each add. Kept local since they're transient typing state, not
// part of the manifest draft itself.
const listDrafts = ref({
  'dependencies.python': '',
  'dependencies.system': '',
  'dependencies.skills': '',
  permissions: '',
  tags: '',
})

function isMissing(field) {
  return props.missingFields.includes(field)
}
function isUnconfirmed(field) {
  return props.unconfirmedFields.includes(field)
}
function detectedFactFor(field) {
  return props.detectedFacts ? props.detectedFacts[field] : undefined
}

function setField(field, value) {
  emit('change', { ...props.manifest, [field]: value })
}

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
    ? props.manifest.targets.filter((existing) => existing !== target)
    : [...props.manifest.targets, target]
  setField('targets', targets)
}

// `listKey` is either a top-level field ("permissions", "tags") or "dependencies.<name>".
function currentList(listKey) {
  return listKey.startsWith('dependencies.')
    ? props.manifest.dependencies[listKey.split('.')[1]]
    : props.manifest[listKey]
}

function addListItem(listKey) {
  const value = listDrafts.value[listKey].trim()
  if (!value) return
  const next = dedupeList([...currentList(listKey), value])
  if (listKey.startsWith('dependencies.')) {
    setDependencyField(listKey.split('.')[1], next)
  } else {
    setField(listKey, next)
  }
  listDrafts.value[listKey] = ''
}

function removeListItem(listKey, item) {
  const next = currentList(listKey).filter((existing) => existing !== item)
  if (listKey.startsWith('dependencies.')) {
    setDependencyField(listKey.split('.')[1], next)
  } else {
    setField(listKey, next)
  }
}
</script>

<template>
  <div class="manifest-form">
    <div class="field">
      <label>
        {{ t('upload.workspace.namespace') }}
        <span v-if="isMissing('namespace')" class="badge badge-missing">{{ t('upload.workspace.missingBadge') }}</span>
        <span v-else-if="isUnconfirmed('namespace')" class="badge badge-unconfirmed">{{ t('upload.workspace.unconfirmedBadge') }}</span>
      </label>
      <input type="text" :value="manifest.namespace" @input="setField('namespace', $event.target.value)" />
    </div>

    <div class="field">
      <label>
        {{ t('upload.workspace.name') }}
        <span v-if="isMissing('name')" class="badge badge-missing">{{ t('upload.workspace.missingBadge') }}</span>
        <span v-else-if="isUnconfirmed('name')" class="badge badge-unconfirmed">{{ t('upload.workspace.unconfirmedBadge') }}</span>
      </label>
      <input type="text" :value="manifest.name" @input="setField('name', $event.target.value)" />
      <p v-if="detectedFactFor('name')" class="detected-fact">{{ t('upload.workspace.detectedFactPrefix') }}{{ detectedFactFor('name') }}</p>
    </div>

    <div class="field">
      <label>
        {{ t('upload.workspace.version') }}
        <span v-if="isMissing('version')" class="badge badge-missing">{{ t('upload.workspace.missingBadge') }}</span>
        <span v-else-if="isUnconfirmed('version')" class="badge badge-unconfirmed">{{ t('upload.workspace.unconfirmedBadge') }}</span>
      </label>
      <input type="text" :value="manifest.version" @input="setField('version', $event.target.value)" />
    </div>

    <div class="field">
      <label>
        {{ t('upload.workspace.description') }}
        <span v-if="isMissing('description')" class="badge badge-missing">{{ t('upload.workspace.missingBadge') }}</span>
        <span v-else-if="isUnconfirmed('description')" class="badge badge-unconfirmed">{{ t('upload.workspace.unconfirmedBadge') }}</span>
      </label>
      <textarea rows="2" :value="manifest.description" @input="setField('description', $event.target.value)" />
      <p v-if="detectedFactFor('description')" class="detected-fact">{{ t('upload.workspace.detectedFactPrefix') }}{{ detectedFactFor('description') }}</p>
    </div>

    <div class="field">
      <label>
        {{ t('upload.workspace.author') }}
        <span v-if="isMissing('author')" class="badge badge-missing">{{ t('upload.workspace.missingBadge') }}</span>
        <span v-else-if="isUnconfirmed('author')" class="badge badge-unconfirmed">{{ t('upload.workspace.unconfirmedBadge') }}</span>
      </label>
      <input type="text" :value="authorDisplay()" @input="setField('author', $event.target.value)" />
    </div>

    <div class="field">
      <label>
        {{ t('upload.workspace.license') }}
        <span v-if="isMissing('license')" class="badge badge-missing">{{ t('upload.workspace.missingBadge') }}</span>
        <span v-else-if="isUnconfirmed('license')" class="badge badge-unconfirmed">{{ t('upload.workspace.unconfirmedBadge') }}</span>
      </label>
      <input type="text" :value="manifest.license" @input="setField('license', $event.target.value)" />
    </div>

    <div class="field">
      <label>
        {{ t('upload.workspace.runtime') }}
        <span v-if="isMissing('runtime')" class="badge badge-missing">{{ t('upload.workspace.missingBadge') }}</span>
        <span v-else-if="isUnconfirmed('runtime')" class="badge badge-unconfirmed">{{ t('upload.workspace.unconfirmedBadge') }}</span>
      </label>
      <select :value="manifest.runtime" @change="setField('runtime', $event.target.value)">
        <option value="">{{ t('upload.workspace.runtimePlaceholder') }}</option>
        <option v-for="option in RUNTIME_OPTIONS" :key="option" :value="option">{{ option }}</option>
      </select>
    </div>

    <div class="field">
      <label>
        {{ t('upload.workspace.targets') }}
        <span v-if="isMissing('targets')" class="badge badge-missing">{{ t('upload.workspace.missingBadge') }}</span>
        <span v-else-if="isUnconfirmed('targets')" class="badge badge-unconfirmed">{{ t('upload.workspace.unconfirmedBadge') }}</span>
      </label>
      <div class="checkbox-group">
        <label v-for="option in TARGET_OPTIONS" :key="option" class="checkbox-option">
          <input type="checkbox" :checked="manifest.targets.includes(option)" @change="toggleTarget(option)" />
          {{ option }}
        </label>
      </div>
    </div>

    <div v-for="entry in [
      { key: 'dependencies.python', label: t('upload.workspace.dependenciesPython') },
      { key: 'dependencies.system', label: t('upload.workspace.dependenciesSystem') },
      { key: 'dependencies.skills', label: t('upload.workspace.dependenciesSkills') },
      { key: 'permissions', label: t('upload.workspace.permissions') },
      { key: 'tags', label: t('upload.workspace.tags') },
    ]" :key="entry.key" class="field">
      <label>
        {{ entry.label }}
        <span v-if="isMissing(entry.key)" class="badge badge-missing">{{ t('upload.workspace.missingBadge') }}</span>
        <span v-else-if="isUnconfirmed(entry.key)" class="badge badge-unconfirmed">{{ t('upload.workspace.unconfirmedBadge') }}</span>
      </label>
      <div class="chip-list">
        <span v-for="item in currentList(entry.key)" :key="item" class="chip">
          {{ item }}
          <button type="button" class="chip-remove" :title="t('upload.workspace.listRemove')" @click="removeListItem(entry.key, item)">×</button>
        </span>
      </div>
      <input
        type="text"
        v-model="listDrafts[entry.key]"
        :placeholder="t('upload.workspace.listInputPlaceholder')"
        @keydown.enter.prevent="addListItem(entry.key)"
      />
      <p v-if="detectedFactFor(entry.key)" class="detected-fact">{{ t('upload.workspace.detectedFactPrefix') }}{{ detectedFactFor(entry.key) }}</p>
    </div>
  </div>
</template>

<style scoped>
.manifest-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.field label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.3rem;
  font-size: 0.85rem;
  color: #ccc;
}
input[type='text'],
select,
textarea {
  width: 100%;
  box-sizing: border-box;
  background: #1c1c1c;
  color: inherit;
  border: 1px solid #444;
  border-radius: 6px;
  padding: 0.5rem;
  font-family: inherit;
}
textarea {
  resize: vertical;
}
.checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 0.8rem;
}
.checkbox-option {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.85rem;
  color: #ccc;
}
.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 0.4rem;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: #26343a;
  color: #80cbc4;
  border-radius: 999px;
  padding: 0.15rem 0.7rem;
  font-size: 0.8rem;
}
.chip-remove {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 0.9rem;
  line-height: 1;
  padding: 0;
}
.badge {
  border-radius: 999px;
  padding: 0.05rem 0.55rem;
  font-size: 0.7rem;
  font-weight: 400;
}
.badge-missing {
  background: #4a1f1f;
  color: #e06c75;
}
.badge-unconfirmed {
  background: #4a3a1f;
  color: #f5b942;
}
.detected-fact {
  margin: 0.3rem 0 0;
  font-size: 0.8rem;
  color: #888;
}
</style>
