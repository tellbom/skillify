<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { isReservedBuildPath, isSafeRelativePath } from '../../lib/skillBuilds.js'

const props = defineProps({
  tree: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['add', 'remove'])

const { t } = useI18n()

const newPath = ref('')
const newFile = ref(null)
const localError = ref('')

function onFileChange(event) {
  newFile.value = event.target.files[0] || null
}

function submitAdd() {
  localError.value = ''
  const path = newPath.value.trim()
  if (isReservedBuildPath(path)) {
    localError.value = t('upload.workspace.addFileReservedPath')
    return
  }
  if (!isSafeRelativePath(path)) {
    localError.value = t('upload.workspace.addFileInvalidPath')
    return
  }
  if (!newFile.value) return
  emit('add', { path, file: newFile.value })
  newPath.value = ''
  newFile.value = null
}

function requestRemove(path) {
  if (isReservedBuildPath(path)) {
    localError.value = t('upload.workspace.removeFileReserved')
    return
  }
  emit('remove', path)
}
</script>

<template>
  <div class="build-file-tree">
    <p class="reserved-hint">{{ t('upload.workspace.fileReservedHint') }}</p>

    <ul v-if="tree.length" class="tree-list">
      <li v-for="item in tree" :key="item.path" class="tree-item">
        <span class="tree-path">{{ item.path }}</span>
        <span class="tree-type">{{ item.type === 'directory' ? t('upload.workspace.treeTypeDirectory') : t('upload.workspace.treeTypeFile') }}</span>
        <button
          v-if="item.type !== 'directory' && !isReservedBuildPath(item.path)"
          type="button"
          class="link-button danger"
          :disabled="busy"
          @click="requestRemove(item.path)"
        >
          {{ busy ? t('upload.workspace.removingFile') : t('upload.workspace.removeFile') }}
        </button>
      </li>
    </ul>
    <p v-else class="empty-hint">{{ t('upload.workspace.filesEmpty') }}</p>

    <div class="add-file-form">
      <input v-model="newPath" type="text" :placeholder="t('upload.workspace.addFilePath')" />
      <input type="file" @change="onFileChange" />
      <button type="button" class="primary-button" :disabled="busy || !newPath.trim() || !newFile" @click="submitAdd">
        {{ busy ? t('upload.workspace.addFileUploading') : t('upload.workspace.addFileAction') }}
      </button>
    </div>
    <p v-if="localError" class="error">{{ localError }}</p>
  </div>
</template>

<style scoped>
.build-file-tree {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.reserved-hint {
  margin: 0;
  font-size: 0.8rem;
  color: #888;
}
.tree-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.tree-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  background: #1c1c1c;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 0.4rem 0.6rem;
  font-size: 0.85rem;
}
.tree-path {
  flex: 1;
  word-break: break-all;
}
.tree-type {
  color: #888;
  font-size: 0.75rem;
}
.empty-hint {
  color: #888;
  font-size: 0.85rem;
}
.add-file-form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}
.add-file-form input[type='text'] {
  flex: 1;
  min-width: 200px;
  background: #1c1c1c;
  color: inherit;
  border: 1px solid #444;
  border-radius: 6px;
  padding: 0.5rem;
}
.primary-button {
  background: #26343a;
  color: #80cbc4;
  border: 1px solid #444;
  border-radius: 6px;
  padding: 0.5rem 1rem;
  cursor: pointer;
}
.primary-button:disabled {
  opacity: 0.5;
  cursor: default;
}
.link-button {
  background: none;
  border: none;
  color: #80cbc4;
  cursor: pointer;
  padding: 0;
  font-size: 0.8rem;
}
.link-button.danger {
  color: #e06c75;
}
.link-button:disabled {
  opacity: 0.5;
  cursor: default;
}
.error {
  color: #e06c75;
  font-size: 0.85rem;
  margin: 0;
}
</style>
