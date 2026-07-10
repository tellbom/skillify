<script setup>
import { ref, onMounted, watch } from 'vue'
import { listSkills } from '../lib/api.js'

const skills = ref([])
const query = ref('')
const loading = ref(true)
const error = ref(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    skills.value = await listSkills(query.value.trim())
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

let debounceHandle
watch(query, () => {
  clearTimeout(debounceHandle)
  debounceHandle = setTimeout(load, 250)
})

onMounted(load)
</script>

<template>
  <div>
    <input
      v-model="query"
      class="search-input"
      type="search"
      placeholder="Search skills by name or description..."
    />

    <p v-if="loading" class="hint">Loading…</p>
    <p v-else-if="error" class="error">Failed to load skills: {{ error }}</p>
    <p v-else-if="skills.length === 0" class="hint">No skills found.</p>

    <ul v-else class="skill-list">
      <li v-for="skill in skills" :key="`${skill.namespace}/${skill.name}`" class="skill-card">
        <router-link :to="{ name: 'skill-detail', params: { namespace: skill.namespace, name: skill.name } }">
          <h3>{{ skill.namespace }}/{{ skill.name }} <span class="version">v{{ skill.version }}</span></h3>
        </router-link>
        <p class="description">{{ skill.description }}</p>
        <div class="tags">
          <span v-for="tag in skill.tags" :key="tag" class="tag">{{ tag }}</span>
        </div>
        <p class="author">by {{ skill.author }}</p>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.search-input {
  width: 100%;
  padding: 0.6rem 0.8rem;
  font-size: 1rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  margin-bottom: 1.5rem;
}
.hint {
  color: #888;
}
.error {
  color: #e06c75;
}
.skill-list {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.skill-card {
  border: 1px solid #333;
  border-radius: 8px;
  padding: 1rem 1.2rem;
}
.skill-card h3 {
  margin: 0 0 0.4rem;
}
.version {
  color: #888;
  font-weight: 400;
  font-size: 0.85rem;
}
.description {
  color: #ccc;
  margin: 0 0 0.5rem;
}
.tags {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  margin-bottom: 0.4rem;
}
.tag {
  background: #263238;
  color: #80cbc4;
  border-radius: 999px;
  padding: 0.1rem 0.6rem;
  font-size: 0.75rem;
}
.author {
  color: #888;
  font-size: 0.8rem;
  margin: 0;
}
</style>
