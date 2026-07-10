<script setup>
import { ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getComments, postComment } from '../lib/api.js'
import { useAuthStore } from '../stores/auth.js'
import { formatDateTime } from '../lib/datetime.js'

const props = defineProps({ namespace: { type: String, required: true }, name: { type: String, required: true } })

const { t } = useI18n()
const auth = useAuthStore()
const comments = ref([])
const loading = ref(true)
const error = ref(null)
const draft = ref('')
const posting = ref(false)
const postError = ref(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    comments.value = await getComments(props.namespace, props.name)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!draft.value.trim()) return
  posting.value = true
  postError.value = null
  try {
    await postComment(props.namespace, props.name, draft.value.trim())
    draft.value = ''
    await load()
  } catch (err) {
    postError.value = err.message
  } finally {
    posting.value = false
  }
}

watch(() => [props.namespace, props.name], load)
onMounted(load)
</script>

<template>
  <section class="comments">
    <h3>{{ t('comment-rating.commentsTitle') }}</h3>

    <p v-if="loading" class="hint">{{ t('common.loading') }}</p>
    <p v-else-if="error" class="error">{{ t('errors.loadFailed', { error }) }}</p>
    <p v-else-if="comments.length === 0" class="hint">{{ t('comment-rating.noComments') }}</p>

    <ul v-else class="comment-list">
      <li v-for="c in comments" :key="c.id" class="comment">
        <span class="comment-author">{{ c.author }}</span>
        <span class="comment-time">{{ formatDateTime(c.createdAt) }}</span>
        <p class="comment-body">{{ c.body }}</p>
      </li>
    </ul>

    <div v-if="auth.isAuthenticated" class="comment-form">
      <textarea v-model="draft" rows="3" :placeholder="t('comment-rating.addCommentPlaceholder')" />
      <button type="button" :disabled="!draft.trim() || posting" @click="submit">
        {{ posting ? t('comment-rating.posting') : t('comment-rating.postComment') }}
      </button>
      <p v-if="postError" class="error">{{ postError }}</p>
    </div>
    <p v-else class="hint">{{ t('comment-rating.loginToComment') }}</p>
  </section>
</template>

<style scoped>
.comments {
  margin-top: 2rem;
  border-top: 1px solid #333;
  padding-top: 1.5rem;
}
.hint { color: #888; }
.error { color: #e06c75; }
.comment-list {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  margin-bottom: 1rem;
}
.comment {
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  padding: 0.6rem 0.8rem;
}
.comment-author {
  font-weight: 600;
  margin-right: 0.5rem;
}
.comment-time {
  color: #888;
  font-size: 0.8rem;
}
.comment-body {
  margin: 0.3rem 0 0;
  white-space: pre-wrap;
}
.comment-form textarea {
  width: 100%;
  box-sizing: border-box;
  background: #1c1c1c;
  color: inherit;
  border: 1px solid #444;
  border-radius: 6px;
  padding: 0.5rem;
  font-family: inherit;
  resize: vertical;
}
.comment-form button {
  margin-top: 0.5rem;
  padding: 0.4rem 1rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  cursor: pointer;
}
.comment-form button:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
