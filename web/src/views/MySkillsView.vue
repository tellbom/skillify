<script setup>
import { computed, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getMySkills, getMyNamespaces, getMyPublishJobs, getMyUsage, getMySubscriptions } from '../lib/api.js'
import { installCountFor, retryQueryFor } from '../lib/mySkills.js'
import { formatDateTime } from '../lib/datetime.js'

const { t } = useI18n()

const skills = ref([])
const skillsLoading = ref(true)
const skillsError = ref(null)
const usage = ref(null)

const namespaces = ref([])
const namespacesLoading = ref(true)
const namespacesError = ref(null)

const jobs = ref([])
const jobsLoading = ref(true)
const jobsError = ref(null)
const showAllJobs = ref(false)

const subscriptions = ref([])
const subscriptionsLoading = ref(true)
const subscriptionsError = ref(null)

const totalSkills = computed(() => usage.value?.totalSkills ?? skills.value.length)
const totalInstalls = computed(() => usage.value?.totalInstalls ?? 0)
const failedJobs = computed(() => jobs.value.filter((job) => job.status === 'failed').length)

async function loadSkills() {
  skillsLoading.value = true
  skillsError.value = null
  try {
    const [skillsData, usageData] = await Promise.all([getMySkills(), getMyUsage()])
    skills.value = skillsData
    usage.value = usageData
  } catch (err) {
    skillsError.value = err.message
  } finally {
    skillsLoading.value = false
  }
}

async function loadNamespaces() {
  namespacesLoading.value = true
  namespacesError.value = null
  try {
    namespaces.value = await getMyNamespaces()
  } catch (err) {
    namespacesError.value = err.message
  } finally {
    namespacesLoading.value = false
  }
}

async function loadJobs() {
  jobsLoading.value = true
  jobsError.value = null
  try {
    jobs.value = await getMyPublishJobs(showAllJobs.value ? 'all' : 'failed')
  } catch (err) {
    jobsError.value = err.message
  } finally {
    jobsLoading.value = false
  }
}

async function loadSubscriptions() {
  subscriptionsLoading.value = true
  subscriptionsError.value = null
  try {
    subscriptions.value = await getMySubscriptions()
  } catch (err) {
    subscriptionsError.value = err.message
  } finally {
    subscriptionsLoading.value = false
  }
}

function toggleJobsFilter() {
  showAllJobs.value = !showAllJobs.value
  loadJobs()
}

onMounted(() => {
  loadSkills()
  loadNamespaces()
  loadJobs()
  loadSubscriptions()
})
</script>

<template>
  <div class="workspace-page">
    <header class="page-heading">
      <h1>个人空间</h1>
      <p>发布者工作台 · 查看你的技能、命名空间与发布结果</p>
    </header>

    <section class="overview-grid" aria-label="个人空间概览">
      <article class="overview-card">
        <span>我的技能</span>
        <strong>{{ totalSkills }}</strong>
      </article>
      <article class="overview-card accent">
        <span>总安装量</span>
        <strong>{{ totalInstalls }}</strong>
      </article>
      <article class="overview-card">
        <span>命名空间</span>
        <strong>{{ namespaces.length }}</strong>
      </article>
      <article class="overview-card" :class="{ danger: failedJobs > 0 }">
        <span>发布失败</span>
        <strong>{{ failedJobs }}</strong>
      </article>
    </section>

    <div class="workspace-grid">
      <div class="workspace-main">
        <section class="workspace-section">
          <h2>{{ t('my-skills.skillsHeading') }}</h2>
          <div v-if="skillsLoading" class="empty-state">{{ t('my-skills.skillsLoading') }}</div>
          <div v-else-if="skillsError" class="empty-state error">{{ t('errors.loadFailed', { error: skillsError }) }}</div>
          <div v-else-if="skills.length === 0" class="empty-state">
            <strong>{{ t('my-skills.noSkillsFound') }}</strong>
            <span>{{ t('my-skills.noSkillsHint') }}</span>
          </div>
          <div v-else class="skill-list">
            <router-link
              v-for="skill in skills"
              :key="`${skill.namespace}/${skill.name}`"
              class="skill-row"
              :to="{ name: 'skill-detail', params: { namespace: skill.namespace, name: skill.name } }"
            >
              <span class="skill-copy">
                <span class="skill-title">
                  <strong>{{ skill.namespace }}/{{ skill.name }}</strong>
                  <small>v{{ skill.version }}</small>
                </span>
                <span class="skill-description">{{ skill.description }}</span>
              </span>
              <span class="skill-meta">
                <strong>↓ {{ installCountFor(usage, skill) }}</strong>
                <small>{{ skill.publishedAt ? formatDateTime(skill.publishedAt) : '最新版本' }}</small>
              </span>
            </router-link>
          </div>
        </section>

        <section class="workspace-section jobs-section">
          <div class="section-heading">
            <h2>发布记录</h2>
            <div class="job-tabs">
              <button type="button" :class="{ active: !showAllJobs }" @click="showAllJobs && toggleJobsFilter()">仅失败</button>
              <button type="button" :class="{ active: showAllJobs }" @click="!showAllJobs && toggleJobsFilter()">全部</button>
            </div>
          </div>
          <p class="section-note">发布记录是正式部署的历史日志，而非未完成的草稿。失败记录可返回创建/上传区重新准备内容。</p>

          <div v-if="jobsLoading" class="empty-state compact">{{ t('my-skills.jobsLoading') }}</div>
          <div v-else-if="jobsError" class="empty-state compact error">{{ t('errors.loadFailed', { error: jobsError }) }}</div>
          <div v-else-if="jobs.length === 0" class="empty-state compact">{{ t('my-skills.noFailedJobs') }}</div>
          <div v-else class="job-list">
            <article v-for="job in jobs" :key="`${job.namespace}/${job.name}@${job.version}`" class="job-card" :class="{ failed: job.status === 'failed' }">
              <div class="job-header">
                <strong>{{ job.namespace }}/{{ job.name }}</strong>
                <code>{{ job.version }}</code>
                <span class="status-badge" :class="job.status">{{ job.status === 'failed' ? '失败' : '成功' }}</span>
                <time>{{ formatDateTime(job.updatedAt) }}</time>
              </div>
              <p v-if="job.errorMessage" class="job-error">{{ job.errorMessage }}</p>
              <router-link
                v-if="job.status === 'failed'"
                class="retry-link"
                :to="{ name: 'upload', query: retryQueryFor(job) }"
              >重新处理</router-link>
            </article>
          </div>
        </section>
      </div>

      <aside class="workspace-sidebar">
        <section class="side-card">
          <h2>我的命名空间</h2>
          <p>命名空间代表平台上的发布归属与组织空间，首次成功发布后归属发布者。</p>
          <div v-if="namespacesLoading" class="side-state">{{ t('my-skills.namespacesLoading') }}</div>
          <div v-else-if="namespacesError" class="side-state error">{{ namespacesError }}</div>
          <div v-else-if="namespaces.length === 0" class="side-state">{{ t('my-skills.noNamespacesFound') }}</div>
          <div v-else class="namespace-list">
            <div v-for="item in namespaces" :key="item.namespace">
              <code>{{ item.namespace }}</code>
              <span>{{ formatDateTime(item.claimedAt) }} 占用</span>
            </div>
          </div>
        </section>

        <section class="side-card">
          <h2>我的订阅</h2>
          <p>当前订阅技能的最新版本快照。</p>
          <div v-if="subscriptionsLoading" class="side-state">加载订阅中…</div>
          <div v-else-if="subscriptionsError" class="side-state error">{{ subscriptionsError }}</div>
          <div v-else-if="subscriptions.length === 0" class="side-state">暂无订阅。</div>
          <div v-else class="subscription-list">
            <router-link
              v-for="item in subscriptions"
              :key="`${item.namespace}/${item.name}`"
              :to="{ name: 'skill-detail', params: { namespace: item.namespace, name: item.name } }"
            >
              <span><strong>{{ item.namespace }}/{{ item.name }}</strong><code>v{{ item.latestVersion }}</code></span>
              <small>{{ formatDateTime(item.publishedAt) }}</small>
            </router-link>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.workspace-page { padding: 2px 0 12px; animation: page-in 0.25s ease both; }
.page-heading { margin-bottom: 20px; }
.page-heading h1 { margin: 0 0 5px; color: #f2f2f2; font-size: 26px; font-weight: 700; letter-spacing: -0.4px; }
.page-heading p { margin: 0; color: #9f9f9f; font-size: 13.5px; }

.overview-grid { display: grid; margin-bottom: 28px; gap: 14px; grid-template-columns: repeat(4, 1fr); }
.overview-card { padding: 16px 18px; border: 1px solid #2c2c2c; border-radius: 12px; background: #1a1a1a; }
.overview-card span { display: block; margin-bottom: 8px; color: #9f9f9f; font-size: 12px; }
.overview-card strong { color: #e5e5e5; font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; }
.overview-card.accent strong { color: #80cbc4; }
.overview-card.danger strong { color: #e5807a; }

.workspace-grid { display: grid; align-items: start; gap: 28px; grid-template-columns: minmax(0, 1fr) 320px; }
.workspace-main { min-width: 0; }
.workspace-section { margin-bottom: 28px; }
.workspace-section h2 { margin: 0 0 14px; color: #ededed; font-size: 16px; font-weight: 650; }
.skill-list { overflow: hidden; border: 1px solid #2c2c2c; border-radius: 12px; }
.skill-row { display: flex; align-items: center; padding: 15px 18px; color: inherit; background: #181818; gap: 16px; text-decoration: none; transition: background-color 0.13s ease; }
.skill-row:not(:last-child) { border-bottom: 1px solid #212121; }
.skill-row:hover, .skill-row:focus-visible { background: #1e1e1e; outline: none; }
.skill-copy { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 3px; }
.skill-title { display: flex; align-items: center; gap: 9px; }
.skill-title strong { overflow: hidden; color: #80cbc4; font-size: 14px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.skill-title small, .skill-meta small { color: #6e6e6e; font-size: 11px; }
.skill-title small { padding: 1px 7px; border: 1px solid #2c2c2c; border-radius: 5px; background: #232323; font-family: ui-monospace, Menlo, monospace; }
.skill-description { overflow: hidden; color: #9f9f9f; font-size: 12.5px; text-overflow: ellipsis; white-space: nowrap; }
.skill-meta { display: flex; flex: none; align-items: flex-end; white-space: nowrap; flex-direction: column; }
.skill-meta strong { color: #c9c9c9; font-size: 13px; font-weight: 500; }

.section-heading { display: flex; align-items: center; margin-bottom: 10px; gap: 12px; }
.section-heading h2 { margin: 0; }
.job-tabs { display: flex; margin-left: auto; gap: 6px; }
.job-tabs button { padding: 6px 13px; border: 1px solid #2c2c2c; border-radius: 7px; color: #9f9f9f; background: transparent; font: inherit; font-size: 12.5px; cursor: pointer; }
.job-tabs button.active { border-color: #3d3d3d; color: #e5e5e5; background: #232323; }
.section-note { margin: 0 0 12px; color: #6e6e6e; font-size: 12px; }
.job-list { display: flex; gap: 10px; flex-direction: column; }
.job-card { padding: 13px 16px; border: 1px solid #2c2c2c; border-radius: 10px; background: #1a1a1a; }
.job-card.failed { border-color: rgb(229 128 122 / 28%); background: rgb(229 128 122 / 4%); }
.job-header { display: flex; align-items: center; margin-bottom: 6px; gap: 10px; flex-wrap: wrap; }
.job-header strong { color: #e5e5e5; font-size: 13.5px; font-weight: 600; }
.job-header code { color: #9f9f9f; font-size: 11px; }
.job-header time { margin-left: auto; color: #6e6e6e; font-size: 11.5px; }
.status-badge { padding: 2px 8px; border-radius: 999px; font-size: 10.5px; }
.status-badge.failed { color: #edb4b0; background: rgb(229 128 122 / 10%); }
.status-badge.succeeded { color: #79c89b; background: rgb(95 184 142 / 10%); }
.job-error { margin: 0 0 8px; padding: 7px 10px; border-radius: 6px; color: #edb4b0; background: rgb(229 128 122 / 6%); font-size: 12.5px; line-height: 1.5; }
.retry-link { display: inline-block; padding: 5px 12px; border: 1px solid rgb(128 203 196 / 30%); border-radius: 6px; color: #80cbc4; font-size: 12px; text-decoration: none; }
.retry-link:hover { background: rgb(128 203 196 / 8%); }

.workspace-sidebar { min-width: 0; }
.side-card { margin-bottom: 16px; padding: 16px; border: 1px solid #2c2c2c; border-radius: 12px; background: #1a1a1a; }
.side-card h2 { margin: 0 0 8px; color: #6e6e6e; font-size: 11px; font-weight: 600; letter-spacing: 0.6px; text-transform: uppercase; }
.side-card > p { margin: 0 0 12px; color: #6e6e6e; font-size: 11.5px; line-height: 1.5; }
.namespace-list { display: flex; gap: 10px; flex-direction: column; }
.namespace-list > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.namespace-list code { color: #cfe9e5; font-size: 13px; }
.namespace-list span, .side-state { color: #6e6e6e; font-size: 11px; }
.side-state { padding: 8px 0; }
.side-state.error { color: #edb4b0; }
.subscription-list { display: flex; gap: 12px; flex-direction: column; }
.subscription-list a { display: flex; color: inherit; text-decoration: none; flex-direction: column; gap: 3px; }
.subscription-list a > span { display: flex; align-items: center; gap: 8px; }
.subscription-list strong { overflow: hidden; color: #80cbc4; font-size: 12.5px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.subscription-list code { color: #9f9f9f; font-size: 10.5px; }
.subscription-list small { color: #6e6e6e; font-size: 10.5px; }

.empty-state { display: flex; align-items: center; justify-content: center; min-height: 120px; padding: 20px; border: 1px dashed #2c2c2c; border-radius: 10px; color: #6e6e6e; font-size: 13px; text-align: center; flex-direction: column; gap: 6px; }
.empty-state.compact { min-height: 70px; }
.empty-state.error { color: #edb4b0; }
.empty-state span { max-width: 620px; font-size: 11.5px; line-height: 1.6; }

@keyframes page-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }
@media (max-width: 900px) { .workspace-grid { grid-template-columns: 1fr; } .workspace-sidebar { display: grid; gap: 16px; grid-template-columns: 1fr 1fr; } .side-card { margin: 0; } }
@media (max-width: 640px) { .overview-grid { grid-template-columns: 1fr 1fr; } .workspace-sidebar { grid-template-columns: 1fr; } .skill-row { padding: 14px; } }
</style>
