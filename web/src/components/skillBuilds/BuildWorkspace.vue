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
const currentStep = ref(1)
const stepInitialized = ref(false)

const STEPS = [
  '类型与运行时',
  '基础信息',
  '技能说明',
  '脚本与资源',
  '依赖与权限',
  '预览与发布',
]

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
  if (!stepInitialized.value) {
    currentStep.value = data.sourceType === 'native_zip' ? 6 : 1
    stepInitialized.value = true
  }
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
    return true
  } catch (err) {
    await handleMutationError(err, (e) => {
      saveError.value = t('upload.workspace.saveFailed') + e.message
    })
    return false
  } finally {
    savingManifest.value = false
  }
}

async function goNext() {
  if (currentStep.value >= STEPS.length) return
  const needsSave = [1, 2, 3, 5].includes(currentStep.value)
  if (needsSave && !(await saveChanges())) return
  currentStep.value += 1
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function goPrevious() {
  if (currentStep.value <= 1) return
  currentStep.value -= 1
  saveError.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function goToStep(step) {
  if (step >= currentStep.value) return
  currentStep.value = step
  saveError.value = ''
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
    <div v-if="loading" class="workspace-state"><span class="spinner" />{{ t('upload.workspace.loading') }}</div>
    <div v-else-if="loadError" class="workspace-state error">{{ loadError }}</div>

    <template v-else-if="build">
      <div class="workspace-meta">
        <div class="meta-left">
          <strong>{{ sourceTypeLabel }}</strong>
          <span class="status-badge" :class="build.publishable ? 'ready' : 'pending'">{{ statusLabel }}</span>
          <span>{{ t('upload.workspace.revision', { revision: build.revision }) }}</span>
        </div>
        <span class="expiry">临时工作区，{{ t('upload.workspace.expiresAt', { date: formatDateTime(build.expiresAt) }) }}，请在过期前完成确认与发布</span>
      </div>

      <p v-if="conflictNotice" class="notice conflict-notice">{{ t('upload.workspace.conflictNotice') }}</p>

      <nav v-if="!publishResult" class="stepper" aria-label="创建技能步骤">
        <button
          v-for="(label, index) in STEPS"
          :key="label"
          type="button"
          class="step-item"
          :class="{ active: currentStep === index + 1, complete: currentStep > index + 1 }"
          :disabled="index + 1 > currentStep"
          @click="goToStep(index + 1)"
        >
          <span>{{ index + 1 }}</span><strong>{{ label }}</strong>
        </button>
      </nav>

      <template v-if="!publishResult">
        <section class="workspace-card">
          <ManifestForm
            v-if="currentStep === 1"
            section="runtime"
            :manifest="manifestDraft"
            :missing-fields="build.missingFields"
            :unconfirmed-fields="build.unconfirmedFields"
            :detected-facts="build.detectedFacts"
            @change="(next) => (manifestDraft = next)"
          />

          <ManifestForm
            v-else-if="currentStep === 2"
            section="basic"
            :manifest="manifestDraft"
            :missing-fields="build.missingFields"
            :unconfirmed-fields="build.unconfirmedFields"
            :detected-facts="build.detectedFacts"
            @change="(next) => (manifestDraft = next)"
          />

          <div v-else-if="currentStep === 3" class="skill-md-step">
            <div class="section-intro">
              <h3>技能说明（SKILL.md）</h3>
              <p>SKILL.md 是技能的核心：它描述 Agent 在什么情况下使用该技能、如何操作、执行顺序、注意事项与输出要求。</p>
            </div>
            <textarea v-model="skillMdDraft" class="skill-md-editor" :placeholder="t('upload.workspace.skillMdPlaceholder')" />
          </div>

          <div v-else-if="currentStep === 4" class="files-step">
            <div class="section-intro"><h3>脚本与资源</h3><p>按用途添加文件，平台会将其映射到安全的相对路径。</p></div>
            <BuildFileTree :tree="build.tree" :busy="fileBusy" @add="onFileAdd" @remove="onFileRemove" />
            <p v-if="fileError" class="inline-error">{{ fileError }}</p>
          </div>

          <ManifestForm
            v-else-if="currentStep === 5"
            section="requirements"
            :manifest="manifestDraft"
            :missing-fields="build.missingFields"
            :unconfirmed-fields="build.unconfirmedFields"
            :detected-facts="build.detectedFacts"
            @change="(next) => (manifestDraft = next)"
          />

          <div v-else class="preview-step">
            <div class="section-intro"><h3>完整预览与二次确认</h3><p>以下是平台将真正发布的内容。请在确认前逐项核对。</p></div>
            <BuildPreviewPanel
              :manifest-yaml="build.manifestYaml"
              :skill-md="build.skillMd"
              :tree="build.tree"
              :issues="build.issues"
              :publishable="build.publishable"
              :expires-at="build.expiresAt"
            />
            <div class="publish-confirmation">
              <label><input v-model="confirmChecked" type="checkbox" /><span>{{ t('upload.workspace.confirmLabel') }}</span></label>
              <button type="button" class="publish-button" :disabled="!canPublish || publishing" @click="publish">
                {{ publishing ? t('upload.workspace.publishing') : t('upload.workspace.publish') }}
              </button>
            </div>
            <p v-if="publishError" class="inline-error">{{ publishError }}</p>
          </div>

          <footer v-if="currentStep < 6" class="step-actions">
            <button type="button" class="secondary-button" :disabled="currentStep === 1 || savingManifest" @click="goPrevious">上一步</button>
            <div class="action-right">
              <span v-if="saveError" class="inline-error">{{ saveError }}</span>
              <button type="button" class="next-button" :disabled="savingManifest" @click="goNext">{{ savingManifest ? t('upload.workspace.saving') : '下一步' }}</button>
            </div>
          </footer>
          <footer v-else class="step-actions preview-actions">
            <button type="button" class="secondary-button" @click="goPrevious">上一步</button>
          </footer>
        </section>
      </template>

      <section v-else class="workspace-card publish-result">
        <div class="success-icon">✓</div>
        <h3>{{ publishResult.indexError ? 'Release 已创建，但索引出现异常' : t('upload.workspace.publishSucceeded') }}</h3>
        <p>{{ publishResult.indexError ? t('upload.workspace.indexFailedNote', { error: publishResult.indexError }) : '技能已正式发布并写入搜索索引。' }}</p>
        <code>{{ publishResult.namespace }}/{{ publishResult.name }} · v{{ publishResult.version }}</code>
        <a :href="publishResult.releaseUrl" target="_blank" rel="noopener">{{ t('upload.workspace.viewRelease') }} →</a>
      </section>
    </template>
  </div>
</template>

<style scoped>
.build-workspace { display: flex; min-width: 0; gap: 28px; flex-direction: column; }
.workspace-state { display: flex; align-items: center; justify-content: center; min-height: 180px; color: #9f9f9f; font-size: 13px; gap: 12px; }
.workspace-state.error, .inline-error { color: #edb4b0; }
.spinner { width: 18px; height: 18px; border: 2.5px solid #333; border-top-color: #80cbc4; border-radius: 50%; animation: spin 0.7s linear infinite; }
.workspace-meta { display: flex; align-items: center; justify-content: space-between; min-height: 58px; padding: 0 18px; border: 1px solid #2c2c2c; border-radius: 12px; color: #6e6e6e; background: #181818; font-size: 12px; gap: 20px; }
.meta-left { display: flex; align-items: center; gap: 12px; white-space: nowrap; }
.meta-left strong { color: #d6d6d6; font-size: 14px; font-weight: 650; }
.status-badge { padding: 3px 9px; border: 1px solid; border-radius: 6px; font-size: 11px; }
.status-badge.pending { border-color: rgb(224 164 88 / 32%); color: #e0a458; background: rgb(224 164 88 / 7%); }
.status-badge.ready { border-color: rgb(95 184 142 / 32%); color: #79c89b; background: rgb(95 184 142 / 7%); }
.expiry { overflow: hidden; text-align: right; text-overflow: ellipsis; white-space: nowrap; }
.notice { margin: -14px 0 0; padding: 10px 14px; border-radius: 8px; font-size: 12px; }
.conflict-notice { border: 1px solid rgb(224 164 88 / 30%); color: #e0a458; background: rgb(224 164 88 / 5%); }

.stepper { display: flex; align-items: center; overflow-x: auto; }
.step-item { position: relative; display: flex; align-items: center; min-width: 0; padding: 0; border: 0; color: #777; background: none; font: inherit; cursor: default; flex: 1; gap: 9px; white-space: nowrap; }
.step-item:not(:last-child)::after { height: 1px; margin: 0 14px; background: #292929; content: ''; flex: 1; }
.step-item > span { display: inline-flex; flex: none; align-items: center; justify-content: center; width: 30px; height: 30px; border: 1px solid #333; border-radius: 50%; color: #777; background: #1c1c1c; font-size: 12px; }
.step-item strong { font-size: 12.5px; font-weight: 500; }
.step-item.complete { color: #9f9f9f; cursor: pointer; }
.step-item.complete > span { border-color: rgb(128 203 196 / 35%); color: #80cbc4; background: rgb(128 203 196 / 8%); }
.step-item.active { color: #dedede; }
.step-item.active > span { border-color: #80cbc4; color: #10201e; background: #80cbc4; font-weight: 700; }
.step-item.active strong { font-weight: 650; }

.workspace-card { padding: 28px 30px 24px; border: 1px solid #2c2c2c; border-radius: 12px; background: #181818; }
.section-intro { margin-bottom: 20px; }
.section-intro h3 { margin: 0 0 4px; color: #ededed; font-size: 15px; font-weight: 650; }
.section-intro p { margin: 0; color: #9f9f9f; font-size: 12.5px; line-height: 1.6; }
.skill-md-editor { box-sizing: border-box; width: 100%; min-height: 390px; padding: 14px 16px; border: 1px solid #2c2c2c; border-radius: 9px; color: #d8d8d8; background: #141414; font: 12.5px/1.65 ui-monospace, Menlo, monospace; resize: vertical; outline: none; }
.skill-md-editor:focus { border-color: rgb(128 203 196 / 45%); }
.inline-error { margin: 10px 0 0; font-size: 12px; }

.step-actions { display: flex; align-items: center; justify-content: space-between; margin-top: 28px; padding-top: 20px; border-top: 1px solid #292929; }
.action-right { display: flex; align-items: center; margin-left: auto; gap: 12px; }
.secondary-button, .next-button, .publish-button { padding: 9px 18px; border-radius: 8px; font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.secondary-button { border: 1px solid #353535; color: #aaa; background: #202020; }
.next-button, .publish-button { border: 1px solid #80cbc4; color: #10201e; background: #80cbc4; }
.secondary-button:disabled, .next-button:disabled, .publish-button:disabled { opacity: 0.38; cursor: not-allowed; }
.preview-actions { margin-top: 20px; }
.publish-confirmation { display: flex; align-items: center; justify-content: space-between; margin-top: 20px; padding: 16px; border: 1px solid #303030; border-radius: 9px; background: #151515; gap: 20px; }
.publish-confirmation label { display: flex; align-items: flex-start; color: #c9c9c9; font-size: 12.5px; line-height: 1.5; gap: 9px; cursor: pointer; }
.publish-confirmation input { width: 15px; height: 15px; margin-top: 2px; accent-color: #80cbc4; }

.publish-result { padding-block: 48px; text-align: center; }
.success-icon { display: flex; align-items: center; justify-content: center; width: 52px; height: 52px; margin: 0 auto 16px; border: 1px solid rgb(95 184 142 / 40%); border-radius: 50%; color: #5fb88e; background: rgb(95 184 142 / 12%); font-size: 24px; }
.publish-result h3 { margin: 0 0 8px; color: #ededed; font-size: 18px; }
.publish-result p { max-width: 540px; margin: 0 auto 16px; color: #9f9f9f; font-size: 13px; line-height: 1.6; }
.publish-result code { display: block; width: max-content; max-width: 100%; margin: 0 auto 14px; padding: 8px 14px; border: 1px solid #2c2c2c; border-radius: 8px; color: #cfe9e5; background: #141414; font-size: 12.5px; }
.publish-result a { color: #80cbc4; font-size: 12.5px; text-decoration: none; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .workspace-meta { align-items: flex-start; padding-block: 14px; flex-direction: column; } .expiry { text-align: left; white-space: normal; } .step-item strong { display: none; } .step-item:not(:last-child)::after { margin-inline: 8px; } }
@media (max-width: 640px) { .workspace-card { padding: 22px 18px; } .publish-confirmation { align-items: stretch; flex-direction: column; } }
</style>
