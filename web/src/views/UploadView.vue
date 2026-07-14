<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { uploadSkill, createGuidedBuild, scanExternalSkill, selectExternalCandidates } from '../lib/api.js'
import BuildWorkspace from '../components/skillBuilds/BuildWorkspace.vue'
import ExternalCandidateList from '../components/skillBuilds/ExternalCandidateList.vue'

const { t } = useI18n()
const route = useRoute()

// C-2 "retry a failed publish" deep link (MySkillsView.vue -> here): carries just the
// namespace/name/version as a hint, never the file itself — the user must still re-select the
// same zip and resubmit through the normal zip-upload entry, which now produces a preview
// instead of publishing immediately.
const retryHint = route.query.retryNamespace
  ? `${route.query.retryNamespace}/${route.query.retryName}@${route.query.retryVersion}`
  : null

// mode/activeBuildId and everything below live only in component memory — there is no local
// draft box, matching the backend's "no draft box, 24h temporary Build" model. Reloading the
// page returns to the entry picker.
const mode = ref(retryHint ? 'zip' : null)
const activeBuildId = ref(null)

const zipFile = ref(null)
const zipUploading = ref(false)
const zipError = ref('')

const guidedStarting = ref(false)
const guidedError = ref('')

const scanFile = ref(null)
const scanning = ref(false)
const scanError = ref('')
const scanResult = ref(null)

const selecting = ref(false)
const selectError = ref('')
const selectedBuilds = ref([])

function resetToEntry() {
  mode.value = null
  activeBuildId.value = null
  zipFile.value = null
  zipError.value = ''
  guidedError.value = ''
  scanFile.value = null
  scanError.value = ''
  scanResult.value = null
  selectError.value = ''
  selectedBuilds.value = []
}

function chooseMode(next) {
  mode.value = next
}

function onZipFileChange(event) {
  zipFile.value = event.target.files[0] || null
  zipError.value = ''
}

async function submitZip() {
  if (!zipFile.value) return
  zipUploading.value = true
  zipError.value = ''
  try {
    const build = await uploadSkill(zipFile.value)
    activeBuildId.value = build.buildId
  } catch (err) {
    zipError.value = err.message
  } finally {
    zipUploading.value = false
  }
}

async function startGuided() {
  mode.value = 'guided'
  guidedStarting.value = true
  guidedError.value = ''
  try {
    const build = await createGuidedBuild({}, '')
    activeBuildId.value = build.buildId
  } catch (err) {
    guidedError.value = err.message
  } finally {
    guidedStarting.value = false
  }
}

function onScanFileChange(event) {
  scanFile.value = event.target.files[0] || null
  scanError.value = ''
}

async function submitScan() {
  if (!scanFile.value) return
  scanning.value = true
  scanError.value = ''
  try {
    scanResult.value = await scanExternalSkill(scanFile.value)
  } catch (err) {
    scanError.value = err.message
  } finally {
    scanning.value = false
  }
}

async function confirmCandidates(candidateIds) {
  selecting.value = true
  selectError.value = ''
  try {
    const data = await selectExternalCandidates(scanResult.value.scanId, candidateIds)
    selectedBuilds.value = candidateIds.map((candidateId, index) => {
      const candidate = scanResult.value.candidates.find((c) => c.candidateId === candidateId)
      return {
        buildId: data.builds[index].buildId,
        rootPath: candidate ? candidate.rootPath : '',
        name: candidate && candidate.frontmatter ? candidate.frontmatter.name : '',
      }
    })
    if (selectedBuilds.value.length === 1) {
      activeBuildId.value = selectedBuilds.value[0].buildId
    }
  } catch (err) {
    selectError.value = err.message
  } finally {
    selecting.value = false
  }
}

function openExternalBuild(buildId) {
  activeBuildId.value = buildId
}

function backToExternalSwitcher() {
  activeBuildId.value = null
}

function onWorkspaceExpired() {
  resetToEntry()
}
</script>

<template>
  <div class="upload-page">
    <header class="page-heading">
      <h1>{{ t('upload.title') }}</h1>
      <p v-if="!mode">选择一种方式开始。三种入口最终都会进入同一个构建工作区：预览 → 补全 → 校验 → 确认 → 统一发布。</p>
      <p v-else>所有内容会先进入临时构建工作区，确认无误后才会正式发布。</p>
    </header>

    <p v-if="retryHint" class="retry-hint">{{ t('upload.retryHint', { target: retryHint }) }}</p>

    <button v-if="mode" type="button" class="link-button back-to-entry" @click="resetToEntry">
      {{ t('upload.workspace.backToEntry') }}
    </button>

    <section v-if="!mode" class="entry-picker">
      <div class="entry-cards">
        <article class="entry-card">
          <div class="entry-icon zip-icon">ZIP</div>
          <h2>{{ t('upload.entry.zipTitle') }}</h2>
          <p v-html="t('upload.entry.zipDescription')" />
          <button type="button" class="card-button" @click="chooseMode('zip')">{{ t('upload.entry.zipAction') }}</button>
        </article>

        <article class="entry-card recommended">
          <span class="recommend-badge">推荐</span>
          <div class="entry-icon guided-icon">＋</div>
          <h2>{{ t('upload.entry.guidedTitle') }}</h2>
          <p>{{ t('upload.entry.guidedDescription') }}</p>
          <button type="button" class="card-button accent" @click="startGuided">{{ t('upload.entry.guidedAction') }}</button>
        </article>

        <article class="entry-card">
          <div class="entry-icon external-icon">↗</div>
          <h2>{{ t('upload.entry.externalTitle') }}</h2>
          <p v-html="t('upload.entry.externalDescription')" />
          <button type="button" class="card-button" @click="chooseMode('external')">{{ t('upload.entry.externalAction') }}</button>
        </article>
      </div>

      <div class="coming-soon-note">
        <span class="note-dot" />
        <span>{{ t('upload.entry.gitComingSoon') }} · 目前仅接受 zip 上传</span>
      </div>
    </section>

    <section v-else-if="mode === 'zip' && !activeBuildId" class="mode-panel upload-panel">
      <div class="panel-heading">
        <span class="entry-icon zip-icon">ZIP</span>
        <div><h2>{{ t('upload.entry.zipTitle') }}</h2><p>选择包含 skill.yaml 与 SKILL.md 的标准压缩包，系统校验后会生成完整预览。</p></div>
      </div>
      <label class="file-picker">
        <span>{{ zipFile ? zipFile.name : t('upload.zip.chooseFile') }}</span>
        <input type="file" accept=".zip" @change="onZipFileChange" />
        <strong>选择文件</strong>
      </label>
      <button type="button" class="submit-button" :disabled="!zipFile || zipUploading" @click="submitZip">
        {{ zipUploading ? t('upload.zip.uploading') : t('upload.zip.upload') }}
      </button>
      <div v-if="zipError" class="result error"><strong>{{ t('upload.zip.rejected') }}</strong><pre>{{ zipError }}</pre></div>
    </section>

    <section v-else-if="mode === 'guided' && !activeBuildId" class="mode-panel loading-panel">
      <span v-if="guidedStarting" class="spinner" />
      <p v-if="guidedStarting">{{ t('upload.guided.starting') }}</p>
      <div v-if="guidedError" class="result error">
        <strong>{{ t('upload.guided.startFailed') }}</strong>
        <pre>{{ guidedError }}</pre>
        <button type="button" class="card-button" @click="startGuided">{{ t('upload.entry.guidedAction') }}</button>
      </div>
    </section>

    <section v-else-if="mode === 'external' && !activeBuildId" class="mode-panel">
      <template v-if="!scanResult">
        <div class="panel-heading">
          <span class="entry-icon external-icon">↗</span>
          <div><h2>{{ t('upload.entry.externalTitle') }}</h2><p>上传第三方 Agent Skill zip，扫描结果只作为参考，关键字段仍需手动确认。</p></div>
        </div>
        <label class="file-picker">
          <span>{{ scanFile ? scanFile.name : t('upload.external.chooseFile') }}</span>
          <input type="file" accept=".zip" @change="onScanFileChange" />
          <strong>选择文件</strong>
        </label>
        <button type="button" class="submit-button" :disabled="!scanFile || scanning" @click="submitScan">
          {{ scanning ? t('upload.external.scanning') : t('upload.external.scan') }}
        </button>
        <div v-if="scanError" class="result error"><strong>{{ t('upload.external.rejected') }}</strong><pre>{{ scanError }}</pre></div>
      </template>

      <template v-else-if="selectedBuilds.length === 0">
        <div class="scan-heading"><h2>扫描结果</h2><p>{{ t('upload.external.notGuessedNote') }}</p></div>
        <ExternalCandidateList :candidates="scanResult.candidates" :busy="selecting" @confirm="confirmCandidates" />
        <p v-if="selectError" class="inline-error">{{ selectError }}</p>
      </template>

      <template v-else>
        <div class="scan-heading"><h2>选择构建</h2><p>{{ t('upload.external.switcherHeading', { n: selectedBuilds.length }) }}</p></div>
        <ul class="build-switcher">
          <li v-for="item in selectedBuilds" :key="item.buildId">
            <button type="button" class="build-link" @click="openExternalBuild(item.buildId)">
              <span>{{ item.name || item.rootPath }}</span><span>进入构建 ›</span>
            </button>
          </li>
        </ul>
      </template>
    </section>

    <section v-if="activeBuildId" class="workspace-panel">
      <button v-if="mode === 'external' && selectedBuilds.length > 1" type="button" class="link-button back-to-switcher" @click="backToExternalSwitcher">
        {{ t('upload.external.switcherBack') }}
      </button>
      <BuildWorkspace :build-id="activeBuildId" @expired="onWorkspaceExpired" />
    </section>
  </div>
</template>

<style scoped>
.upload-page { padding: 2px 0 32px; animation: page-in 0.25s ease both; }
.page-heading { margin-bottom: 22px; }
.page-heading h1 { margin: 0 0 6px; color: #f2f2f2; font-size: 26px; font-weight: 700; letter-spacing: -0.4px; }
.page-heading p { margin: 0; color: #9f9f9f; font-size: 13.5px; }
.retry-hint { margin: -8px 0 20px; padding: 10px 14px; border: 1px solid rgb(128 203 196 / 25%); border-radius: 8px; color: #a9d8d4; background: rgb(128 203 196 / 6%); font-size: 12.5px; }

.entry-cards { display: grid; gap: 16px; grid-template-columns: repeat(3, 1fr); }
.entry-card { position: relative; display: flex; min-width: 0; min-height: 250px; padding: 20px; border: 1px solid #2c2c2c; border-radius: 12px; background: #1a1a1a; flex-direction: column; }
.entry-card.recommended { border-color: rgb(128 203 196 / 35%); background: linear-gradient(180deg, #1d1f1e, #1a1a1a); }
.recommend-badge { position: absolute; top: 14px; right: 14px; padding: 2px 8px; border: 1px solid rgb(128 203 196 / 30%); border-radius: 20px; color: #80cbc4; background: rgb(128 203 196 / 12%); font-size: 10.5px; }
.entry-icon { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; margin-bottom: 16px; border: 1px solid #333; border-radius: 9px; color: #9f9f9f; background: #222; font-size: 11px; font-weight: 700; }
.guided-icon { border-color: rgb(128 203 196 / 25%); color: #80cbc4; background: rgb(128 203 196 / 8%); font-size: 20px; font-weight: 400; }
.external-icon { color: #e0b58a; font-size: 18px; }
.entry-card h2 { margin: 0 0 10px; color: #ededed; font-size: 15px; font-weight: 650; }
.entry-card p { margin: 0 0 18px; color: #9f9f9f; font-size: 12.5px; line-height: 1.65; flex: 1; }
.entry-card :deep(code) { color: #e0b58a; font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; }
.card-button, .submit-button { padding: 9px 15px; border: 1px solid #363636; border-radius: 8px; color: #e2e2e2; background: #232323; font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; transition: color 0.15s ease, border-color 0.15s ease, background-color 0.15s ease; }
.card-button:hover { border-color: #4a4a4a; background: #292929; }
.card-button.accent, .submit-button { border-color: rgb(128 203 196 / 35%); color: #80cbc4; background: rgb(128 203 196 / 10%); }
.card-button.accent:hover, .submit-button:hover:not(:disabled) { background: rgb(128 203 196 / 15%); }
.coming-soon-note { display: flex; align-items: center; margin-top: 16px; padding: 14px 18px; border: 1px dashed #2c2c2c; border-radius: 10px; color: #6e6e6e; font-size: 13px; gap: 10px; }
.note-dot { width: 6px; height: 6px; border-radius: 50%; background: #555; }

.link-button { padding: 0; border: 0; color: #80cbc4; background: none; font: inherit; font-size: 13px; cursor: pointer; }
.back-to-entry { display: inline-flex; margin: 0 0 20px; }
.mode-panel { padding: 22px; border: 1px solid #2c2c2c; border-radius: 12px; background: #1a1a1a; }
.panel-heading { display: flex; align-items: flex-start; margin-bottom: 20px; gap: 14px; }
.panel-heading .entry-icon { flex: none; margin: 0; }
.panel-heading h2, .scan-heading h2 { margin: 0 0 5px; color: #ededed; font-size: 16px; font-weight: 650; }
.panel-heading p, .scan-heading p { margin: 0; color: #8c8c8c; font-size: 12.5px; line-height: 1.6; }
.file-picker { display: flex; align-items: center; min-height: 46px; margin-bottom: 14px; padding: 0 6px 0 14px; border: 1px dashed #3a3a3a; border-radius: 9px; color: #888; background: #181818; font-size: 12.5px; gap: 12px; cursor: pointer; }
.file-picker span { overflow: hidden; flex: 1; text-overflow: ellipsis; white-space: nowrap; }
.file-picker input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.file-picker strong { padding: 7px 11px; border: 1px solid #363636; border-radius: 6px; color: #c9c9c9; background: #232323; font-size: 11.5px; }
.submit-button:disabled { opacity: 0.45; cursor: not-allowed; }
.loading-panel { display: flex; align-items: center; justify-content: center; min-height: 150px; color: #9f9f9f; font-size: 13px; gap: 12px; }
.spinner { width: 18px; height: 18px; border: 2.5px solid #333; border-top-color: #80cbc4; border-radius: 50%; animation: spin 0.7s linear infinite; }
.result { margin-top: 16px; padding: 12px 14px; border: 1px solid #333; border-radius: 8px; }
.result.error { border-color: rgb(229 128 122 / 35%); color: #edb4b0; background: rgb(229 128 122 / 5%); }
.result pre { margin: 8px 0 0; color: inherit; font: 12px/1.5 ui-monospace, Menlo, monospace; white-space: pre-wrap; }
.scan-heading { margin-bottom: 18px; }
.inline-error { color: #edb4b0; font-size: 12.5px; }
.build-switcher { display: flex; margin: 0; padding: 0; list-style: none; gap: 10px; flex-direction: column; }
.build-link { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 12px 14px; border: 1px solid #2c2c2c; border-radius: 8px; color: #c9c9c9; background: #181818; font: inherit; font-size: 12.5px; cursor: pointer; }
.build-link span:last-child { color: #80cbc4; }
.workspace-panel { min-width: 0; }
.back-to-switcher { margin-bottom: 18px; }

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes page-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }
@media (max-width: 820px) { .entry-cards { grid-template-columns: 1fr; } .entry-card { min-height: auto; } }
</style>
