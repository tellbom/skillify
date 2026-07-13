<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getSkillBuild,
  patchSkillBuild,
  addSkillBuildFile,
  deleteSkillBuildFile,
  publishSkillBuild,
} from '../../lib/api.js'
import { manifestDraftFrom } from '../../lib/skillBuilds.js'
import { formatDateTime } from '../../lib/datetime.js'
import ManifestForm from './ManifestForm.vue'
import BuildFileTree from './BuildFileTree.vue'
import BuildPreviewPanel from './BuildPreviewPanel.vue'

const props = defineProps({
  buildId: { type: String, required: true },
})
const emit = defineEmits(['expired'])

const { t } = useI18n()

const build = ref(null)
const loading = ref(true)
const loadError = ref('')

const manifestDraft = ref(manifestDraftFrom(undefined))
const skillMdDraft = ref('')
const savingManifest = ref(false)
const saveError = ref('')

const fileBusy = ref(false)
const fileError = ref('')

const publishing = ref(false)
const publishError = ref('')
const publishResult = ref(null)
const confirmChecked = ref(false)

const conflictNotice = ref(false)

const SOURCE_TYPE_KEYS = {
  native_zip: 'upload.workspace.sourceTypeNative',
  guided: 'upload.workspace.sourceTypeGuided',
  external: 'upload.workspace.sourceTypeExternal',
}
const STATUS_KEYS = {
  needs_input: 'upload.workspace.statusNeedsInput',
  ready: 'upload.workspace.statusReady',
  publishing: 'upload.workspace.statusPublishing',
  published: 'upload.workspace.statusPublished',
}

const sourceTypeLabel = computed(() => (build.value ? t(SOURCE_TYPE_KEYS[build.value.sourceType] || build.value.sourceType) : ''))
const statusLabel = computed(() => (build.value ? t(STATUS_KEYS[build.value.status] || build.value.status) : ''))

function applyBuild(data) {
  build.value = data
  manifestDraft.value = manifestDraftFrom(data.manifest)
  skillMdDraft.value = data.skillMd || ''
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await getSkillBuild(props.buildId)
    applyBuild(data)
  } catch (err) {
    if (err.status === 404) {
      emit('expired')
    } else {
      loadError.value = t('upload.workspace.loadFailed', { error: err.message })
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)

// Shared 409/404 handling for every mutation below: on conflict, always refetch the latest
// full BuildPreview and replace local state with it — never keep the local draft, since the
// backend copy is the only one that can be trusted after a concurrent change.
async function handleMutationError(err, onOther) {
  if (err.status === 409) {
    conflictNotice.value = true
    try {
      const fresh = await getSkillBuild(props.buildId)
      applyBuild(fresh)
    } catch (refetchErr) {
      if (refetchErr.status === 404) emit('expired')
    }
    return
  }
  if (err.status === 404) {
    emit('expired')
    return
  }
  onOther(err)
}

async function saveChanges() {
  savingManifest.value = true
  saveError.value = ''
  conflictNotice.value = false
  try {
    const data = await patchSkillBuild(props.buildId, {
      expectedRevision: build.value.revision,
      manifest: manifestDraft.value,
      skillMd: skillMdDraft.value,
    })
    applyBuild(data)
  } catch (err) {
    await handleMutationError(err, (e) => {
      saveError.value = t('upload.workspace.saveFailed') + e.message
    })
  } finally {
    savingManifest.value = false
  }
}

async function onFileAdd({ path, file }) {
  fileBusy.value = true
  fileError.value = ''
  conflictNotice.value = false
  try {
    const data = await addSkillBuildFile(props.buildId, { path, expectedRevision: build.value.revision, file })
    applyBuild(data)
  } catch (err) {
    await handleMutationError(err, (e) => {
      fileError.value = t('upload.workspace.addFileFailed') + e.message
    })
  } finally {
    fileBusy.value = false
  }
}

async function onFileRemove(path) {
  fileBusy.value = true
  fileError.value = ''
  conflictNotice.value = false
  try {
    const data = await deleteSkillBuildFile(props.buildId, { path, expectedRevision: build.value.revision })
    applyBuild(data)
  } catch (err) {
    await handleMutationError(err, (e) => {
      fileError.value = t('upload.workspace.removeFileFailed') + e.message
    })
  } finally {
    fileBusy.value = false
  }
}

const canPublish = computed(() => !!build.value && build.value.publishable === true && confirmChecked.value)

async function publish() {
  publishing.value = true
  publishError.value = ''
  conflictNotice.value = false
  try {
    const data = await publishSkillBuild(props.buildId, { expectedRevision: build.value.revision, confirmed: true })
    publishResult.value = data
  } catch (err) {
    await handleMutationError(err, (e) => {
      if (e.status === 422 && e.detail && typeof e.detail === 'object') {
        publishError.value = e.detail.message || e.message
        if (Array.isArray(e.detail.missingFields)) build.value.missingFields = e.detail.missingFields
        if (Array.isArray(e.detail.unconfirmedFields)) build.value.unconfirmedFields = e.detail.unconfirmedFields
        if (Array.isArray(e.detail.issues)) build.value.issues = e.detail.issues
      } else {
        publishError.value = t('upload.workspace.publishFailed') + e.message
      }
    })
  } finally {
    publishing.value = false
  }
}
</script>

<template>
  <div class="build-workspace">
    <p v-if="loading">{{ t('upload.workspace.loading') }}</p>
    <p v-else-if="loadError" class="error">{{ loadError }}</p>

    <template v-else-if="build">
      <div class="workspace-meta">
        <span>{{ sourceTypeLabel }}</span>
        <span>{{ statusLabel }}</span>
        <span>{{ t('upload.workspace.revision', { revision: build.revision }) }}</span>
        <span>{{ t('upload.workspace.expiresAt', { date: formatDateTime(build.expiresAt) }) }}</span>
      </div>

      <p v-if="conflictNotice" class="conflict-notice">{{ t('upload.workspace.conflictNotice') }}</p>

      <template v-if="!publishResult">
        <section class="workspace-section">
          <h3>{{ t('upload.workspace.manifestHeading') }}</h3>
          <ManifestForm
            :manifest="manifestDraft"
            :missing-fields="build.missingFields"
            :unconfirmed-fields="build.unconfirmedFields"
            :detected-facts="build.detectedFacts"
            @change="(next) => (manifestDraft = next)"
          />
        </section>

        <section class="workspace-section">
          <h3>{{ t('upload.workspace.skillMdHeading') }}</h3>
          <textarea
            v-model="skillMdDraft"
            rows="10"
            class="skill-md-editor"
            :placeholder="t('upload.workspace.skillMdPlaceholder')"
          />
        </section>

        <div class="save-row">
          <button type="button" class="primary-button" :disabled="savingManifest" @click="saveChanges">
            {{ savingManifest ? t('upload.workspace.saving') : t('upload.workspace.saveChanges') }}
          </button>
          <span v-if="saveError" class="error">{{ saveError }}</span>
        </div>

        <section class="workspace-section">
          <h3>{{ t('upload.workspace.filesHeading') }}</h3>
          <BuildFileTree :tree="build.tree" :busy="fileBusy" @add="onFileAdd" @remove="onFileRemove" />
          <p v-if="fileError" class="error">{{ fileError }}</p>
        </section>

        <section class="workspace-section">
          <h3>{{ t('upload.workspace.previewHeading') }}</h3>
          <BuildPreviewPanel
            :manifest-yaml="build.manifestYaml"
            :skill-md="build.skillMd"
            :tree="build.tree"
            :issues="build.issues"
            :publishable="build.publishable"
            :expires-at="build.expiresAt"
          />
        </section>

        <section class="workspace-section publish-section">
          <label class="confirm-label">
            <input type="checkbox" v-model="confirmChecked" />
            {{ t('upload.workspace.confirmLabel') }}
          </label>
          <button type="button" class="primary-button" :disabled="!canPublish || publishing" @click="publish">
            {{ publishing ? t('upload.workspace.publishing') : t('upload.workspace.publish') }}
          </button>
          <p v-if="publishError" class="error">{{ publishError }}</p>
        </section>
      </template>

      <section v-else class="workspace-section publish-result">
        <h3>{{ t('upload.workspace.publishSucceeded') }}</h3>
        <p>{{ publishResult.namespace }} / {{ publishResult.name }} @ {{ publishResult.version }}</p>
        <a :href="publishResult.releaseUrl" target="_blank" rel="noopener" class="link-button">{{ t('upload.workspace.viewRelease') }}</a>
        <p v-if="publishResult.indexError" class="index-error-note">
          {{ t('upload.workspace.indexFailedNote', { error: publishResult.indexError }) }}
        </p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.build-workspace {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}
.workspace-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.8rem;
  color: #888;
}
.conflict-notice {
  color: #f5b942;
  font-size: 0.85rem;
  margin: 0;
}
.workspace-section {
  background: #1c1c1c;
  border: 1px solid #333;
  border-radius: 6px;
  padding: 1rem;
}
.workspace-section h3 {
  margin: 0 0 0.8rem;
  font-size: 0.95rem;
  color: #ccc;
}
.skill-md-editor {
  width: 100%;
  box-sizing: border-box;
  background: #1c1c1c;
  color: inherit;
  border: 1px solid #444;
  border-radius: 6px;
  padding: 0.6rem;
  font-family: monospace;
  resize: vertical;
}
.save-row {
  display: flex;
  align-items: center;
  gap: 0.8rem;
}
.confirm-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: #ccc;
  margin-bottom: 0.8rem;
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
.error {
  color: #e06c75;
  font-size: 0.85rem;
}
.publish-result p {
  margin: 0.3rem 0;
}
.link-button {
  color: #80cbc4;
  text-decoration: none;
}
.index-error-note {
  color: #f5b942;
  font-size: 0.85rem;
}
</style>
