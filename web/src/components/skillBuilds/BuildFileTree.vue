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

    <div class="add-file-form">
      <input v-model="newPath" type="text" :placeholder="t('upload.workspace.addFilePath')" />
      <label class="file-control">
        <input type="file" @change="onFileChange" />
        <span>{{ newFile ? newFile.name : '选择文件' }}</span>
      </label>
      <button type="button" class="primary-button" :disabled="busy || !newPath.trim() || !newFile" @click="submitAdd">
        {{ busy ? t('upload.workspace.addFileUploading') : t('upload.workspace.addFileAction') }}
      </button>
    </div>

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
    <p v-if="localError" class="error">{{ localError }}</p>
  </div>
</template>

<style scoped>
.build-file-tree { display: flex; gap: 14px; flex-direction: column; }
.reserved-hint {
  margin: 0;
  padding: 8px 12px;
  border: 1px solid rgb(224 164 88 / 22%);
  border-radius: 7px;
  color: #e0a458;
  background: rgb(224 164 88 / 6%);
  font-size: 11.5px;
}
.tree-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  gap: 0;
  border: 1px solid #2c2c2c;
  border-radius: 10px;
}
.tree-item {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  background: #181818;
  font-size: 12.5px;
  gap: 12px;
}
.tree-item:not(:last-child) { border-bottom: 1px solid #212121; }
.tree-path {
  flex: 1;
  color: #cfe9e5;
  font-family: ui-monospace, Menlo, monospace;
  word-break: break-all;
}
.tree-type {
  color: #888;
  font-size: 0.75rem;
}
.empty-hint { margin: 0; padding: 22px; border: 1px dashed #2c2c2c; border-radius: 9px; color: #6e6e6e; font-size: 12px; text-align: center; }
.add-file-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.add-file-form input[type='text'] {
  flex: 1;
  min-width: 200px;
  background: #1c1c1c;
  color: #e5e5e5;
  border: 1px solid #2c2c2c;
  border-radius: 8px;
  padding: 10px 12px;
  font: inherit;
  font-size: 12.5px;
  outline: none;
}
.file-control { position: relative; display: inline-flex; align-items: center; max-width: 210px; height: 38px; padding: 0 12px; border: 1px solid #353535; border-radius: 8px; color: #9f9f9f; background: #202020; font-size: 12px; cursor: pointer; }
.file-control input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.file-control span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.primary-button {
  height: 38px;
  padding: 0 16px;
  border: 1px solid rgb(128 203 196 / 35%);
  border-radius: 8px;
  color: #80cbc4;
  background: rgb(128 203 196 / 9%);
  font: inherit;
  font-size: 12px;
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
  color: #9f9f9f;
}
.link-button.danger:hover { color: #e5807a; }
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
