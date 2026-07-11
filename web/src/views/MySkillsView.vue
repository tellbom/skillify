<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getMySkills, getMyNamespaces, getMyPublishJobs, getMyUsage } from '../lib/api.js'
import { installCountFor, retryQueryFor } from '../lib/mySkills.js'
import { formatDateTime } from '../lib/datetime.js'

const { t } = useI18n()

// Section 1: my skills (author == my Keycloak username in skill.yaml — NOT "uploaded by me",
// see Task 4/5 brief's semantic-gap note; noSkillsHint below surfaces that instead of papering
// over it).
const skills = ref([])
const skillsLoading = ref(true)
const skillsError = ref(null)
const usage = ref(null)

// Section 2: namespaces I've claimed.
const namespaces = ref([])
const namespacesLoading = ref(true)
const namespacesError = ref(null)

// Section 3: publish jobs (failed by default; toggle to see all, incl. succeeded).
const jobs = ref([])
const jobsLoading = ref(true)
const jobsError = ref(null)
const showAllJobs = ref(false)

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

function toggleJobsFilter() {
  showAllJobs.value = !showAllJobs.value
  loadJobs()
}

onMounted(() => {
  loadSkills()
  loadNamespaces()
  loadJobs()
})
</script>

<template>
  <div>
    <router-link to="/" class="back-link">{{ t('my-skills.backLink') }}</router-link>
    <h2>{{ t('my-skills.title') }}</h2>

    <section class="my-section">
      <h3>{{ t('my-skills.skillsHeading') }}</h3>
      <p v-if="skillsLoading" class="hint">{{ t('my-skills.skillsLoading') }}</p>
      <p v-else-if="skillsError" class="error">{{ t('errors.loadFailed', { error: skillsError }) }}</p>
      <template v-else-if="skills.length === 0">
        <p class="hint">{{ t('my-skills.noSkillsFound') }}</p>
        <p class="hint sub-hint">{{ t('my-skills.noSkillsHint') }}</p>
      </template>
      <ul v-else class="skill-list">
        <li v-for="skill in skills" :key="`${skill.namespace}/${skill.name}`" class="skill-card">
          <router-link :to="{ name: 'skill-detail', params: { namespace: skill.namespace, name: skill.name } }">
            <h4>{{ skill.namespace }}/{{ skill.name }} <span class="version">v{{ skill.version }}</span></h4>
          </router-link>
          <p class="description">{{ skill.description }}</p>
          <p class="install-count">{{ t('my-skills.installCount', { n: installCountFor(usage, skill) }) }}</p>
        </li>
      </ul>
    </section>

    <section class="my-section">
      <h3>{{ t('my-skills.namespacesHeading') }}</h3>
      <p v-if="namespacesLoading" class="hint">{{ t('my-skills.namespacesLoading') }}</p>
      <p v-else-if="namespacesError" class="error">{{ t('errors.loadFailed', { error: namespacesError }) }}</p>
      <p v-else-if="namespaces.length === 0" class="hint">{{ t('my-skills.noNamespacesFound') }}</p>
      <ul v-else class="namespace-list">
        <li v-for="ns in namespaces" :key="ns.namespace" class="namespace-card">
          <span class="namespace-name">{{ ns.namespace }}</span>
          <span class="hint">{{ t('my-skills.claimedAt', { date: formatDateTime(ns.claimedAt) }) }}</span>
        </li>
      </ul>
    </section>

    <section class="my-section">
      <div class="jobs-header">
        <h3>{{ t('my-skills.jobsHeading') }}</h3>
        <button type="button" class="toggle-button" @click="toggleJobsFilter">
          {{ showAllJobs ? t('my-skills.showFailedOnly') : t('my-skills.showAllJobs') }}
        </button>
      </div>
      <p v-if="jobsLoading" class="hint">{{ t('my-skills.jobsLoading') }}</p>
      <p v-else-if="jobsError" class="error">{{ t('errors.loadFailed', { error: jobsError }) }}</p>
      <p v-else-if="jobs.length === 0" class="hint">{{ t('my-skills.noFailedJobs') }}</p>
      <ul v-else class="job-list">
        <li
          v-for="job in jobs"
          :key="`${job.namespace}/${job.name}@${job.version}`"
          class="job-card"
          :class="{ failed: job.status === 'failed' }"
        >
          <div class="job-header">
            <span class="job-target">{{ job.namespace }}/{{ job.name }} <span class="version">v{{ job.version }}</span></span>
            <span class="badge" :class="job.status === 'failed' ? 'badge-failed' : 'badge-succeeded'">
              {{ job.status === 'failed' ? t('my-skills.statusFailed') : t('my-skills.statusSucceeded') }}
            </span>
          </div>
          <p class="hint">{{ t('my-skills.jobUpdatedAt', { date: formatDateTime(job.updatedAt) }) }}</p>
          <p v-if="job.errorMessage" class="error job-error">{{ t('my-skills.jobError', { error: job.errorMessage }) }}</p>
          <router-link
            v-if="job.status === 'failed'"
            class="retry-link"
            :to="{ name: 'upload', query: retryQueryFor(job) }"
          >
            {{ t('my-skills.retry') }}
          </router-link>
        </li>
      </ul>
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
.hint {
  color: #888;
  font-size: 0.85rem;
}
.sub-hint {
  margin-top: 0.3rem;
}
.error {
  color: #e06c75;
}
.my-section {
  margin-bottom: 2rem;
}
.my-section h3 {
  margin-bottom: 0.6rem;
}
.jobs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.toggle-button {
  padding: 0.3rem 0.8rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  cursor: pointer;
  font-size: 0.8rem;
}
.skill-list, .namespace-list, .job-list {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
}
.skill-card, .namespace-card, .job-card {
  border: 1px solid #333;
  border-radius: 8px;
  padding: 0.8rem 1rem;
}
.job-card.failed {
  border-color: #a94442;
}
.skill-card h4 {
  margin: 0 0 0.3rem;
}
.version {
  color: #888;
  font-weight: 400;
  font-size: 0.85rem;
}
.description {
  color: #ccc;
  margin: 0 0 0.3rem;
  font-size: 0.9rem;
}
.install-count {
  color: #888;
  font-size: 0.8rem;
  margin: 0;
}
.namespace-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.namespace-name {
  font-weight: 600;
}
.job-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.6rem;
}
.job-target {
  font-weight: 600;
}
.badge {
  border-radius: 999px;
  padding: 0.1rem 0.6rem;
  font-size: 0.75rem;
}
.badge-failed {
  background: #4a1f1f;
  color: #e06c75;
}
.badge-succeeded {
  background: #1f3a2a;
  color: #80cbc4;
}
.job-error {
  font-size: 0.85rem;
}
.retry-link {
  display: inline-block;
  margin-top: 0.4rem;
  color: #80cbc4;
  text-decoration: none;
  border: 1px solid #80cbc4;
  border-radius: 6px;
  padding: 0.2rem 0.7rem;
  font-size: 0.8rem;
}
</style>
