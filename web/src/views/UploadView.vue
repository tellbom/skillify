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
  <div>
    <router-link to="/" class="back-link">{{ t('common.backToSkills') }}</router-link>
    <h2>{{ t('upload.title') }}</h2>
    <p v-if="retryHint" class="hint retry-hint">{{ t('upload.retryHint', { target: retryHint }) }}</p>

    <button v-if="mode" type="button" class="link-button back-to-entry" @click="resetToEntry">
      {{ t('upload.workspace.backToEntry') }}
    </button>

    <section v-if="!mode" class="entry-picker">
      <h3>{{ t('upload.entry.heading') }}</h3>
      <div class="entry-cards">
        <div class="entry-card">
          <h4>{{ t('upload.entry.zipTitle') }}</h4>
          <p v-html="t('upload.entry.zipDescription')" />
          <button type="button" class="primary-button" @click="chooseMode('zip')">{{ t('upload.entry.zipAction') }}</button>
        </div>
        <div class="entry-card">
          <h4>{{ t('upload.entry.guidedTitle') }}</h4>
          <p>{{ t('upload.entry.guidedDescription') }}</p>
          <button type="button" class="primary-button" @click="startGuided">{{ t('upload.entry.guidedAction') }}</button>
        </div>
        <div class="entry-card">
          <h4>{{ t('upload.entry.externalTitle') }}</h4>
          <p v-html="t('upload.entry.externalDescription')" />
          <button type="button" class="primary-button" @click="chooseMode('external')">{{ t('upload.entry.externalAction') }}</button>
        </div>
        <div class="entry-card disabled">
          <p>{{ t('upload.entry.gitComingSoon') }}</p>
        </div>
      </div>
    </section>

    <section v-else-if="mode === 'zip' && !activeBuildId" class="mode-panel">
      <input type="file" accept=".zip" @change="onZipFileChange" />
      <button type="button" :disabled="!zipFile || zipUploading" @click="submitZip">
        {{ zipUploading ? t('upload.zip.uploading') : t('upload.zip.upload') }}
      </button>
      <div v-if="zipError" class="result error">
        <strong>{{ t('upload.zip.rejected') }}</strong>
        <pre>{{ zipError }}</pre>
      </div>
    </section>

    <section v-else-if="mode === 'guided' && !activeBuildId" class="mode-panel">
      <p v-if="guidedStarting">{{ t('upload.guided.starting') }}</p>
      <div v-if="guidedError" class="result error">
        <strong>{{ t('upload.guided.startFailed') }}</strong>
        <pre>{{ guidedError }}</pre>
        <button type="button" @click="startGuided">{{ t('upload.entry.guidedAction') }}</button>
      </div>
    </section>

    <section v-else-if="mode === 'external' && !activeBuildId" class="mode-panel">
      <template v-if="!scanResult">
        <input type="file" accept=".zip" @change="onScanFileChange" />
        <button type="button" :disabled="!scanFile || scanning" @click="submitScan">
          {{ scanning ? t('upload.external.scanning') : t('upload.external.scan') }}
        </button>
        <div v-if="scanError" class="result error">
          <strong>{{ t('upload.external.rejected') }}</strong>
          <pre>{{ scanError }}</pre>
        </div>
      </template>

      <template v-else-if="selectedBuilds.length === 0">
        <p class="hint">{{ t('upload.external.notGuessedNote') }}</p>
        <ExternalCandidateList :candidates="scanResult.candidates" :busy="selecting" @confirm="confirmCandidates" />
        <p v-if="selectError" class="error">{{ selectError }}</p>
      </template>

      <template v-else>
        <p class="hint">{{ t('upload.external.switcherHeading', { n: selectedBuilds.length }) }}</p>
        <ul class="build-switcher">
          <li v-for="item in selectedBuilds" :key="item.buildId">
            <button type="button" class="link-button" @click="openExternalBuild(item.buildId)">
              {{ item.name || item.rootPath }}
            </button>
          </li>
        </ul>
      </template>
    </section>

    <section v-if="activeBuildId" class="mode-panel">
      <button
        v-if="mode === 'external' && selectedBuilds.length > 1"
        type="button"
        class="link-button back-to-switcher"
        @click="backToExternalSwitcher"
      >
        {{ t('upload.external.switcherBack') }}
      </button>
      <BuildWorkspace :build-id="activeBuildId" @expired="onWorkspaceExpired" />
    </section>
  </div>
</template>

<style scoped>
.back-link {
  display: inline-block;
  margin-bottom: 1rem;
  color: #888;
  text-decoration: none;
}
.retry-hint {
  color: #80cbc4;
}
.hint {
  color: #888;
  font-size: 0.9rem;
}
.back-to-entry {
  display: block;
  margin-bottom: 1rem;
}
.entry-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
}
.entry-card {
  background: #1c1c1c;
  border: 1px solid #333;
  border-radius: 8px;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.entry-card.disabled {
  color: #666;
  justify-content: center;
  align-items: center;
}
.entry-card h4 {
  margin: 0;
}
.entry-card p {
  margin: 0;
  font-size: 0.85rem;
  color: #ccc;
  flex: 1;
}
.mode-panel {
  margin-top: 1rem;
}
input[type='file'] {
  display: block;
  margin: 1rem 0;
}
button {
  padding: 0.5rem 1.2rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  cursor: pointer;
}
button:disabled {
  opacity: 0.5;
  cursor: default;
}
.primary-button {
  background: #26343a;
  color: #80cbc4;
}
.link-button {
  background: none;
  border: none;
  color: #80cbc4;
  cursor: pointer;
  padding: 0;
  font-size: 0.9rem;
}
.back-to-switcher {
  display: block;
  margin-bottom: 1rem;
}
.build-switcher {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.result {
  margin-top: 1.5rem;
  padding: 1rem;
  border-radius: 8px;
  border: 1px solid #333;
}
.result.error {
  border-color: #a94442;
}
.result pre {
  white-space: pre-wrap;
  color: #e06c75;
}
.error {
  color: #e06c75;
  font-size: 0.85rem;
}
</style>
