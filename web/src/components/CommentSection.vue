<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getComments, postComment, deleteComment } from '../lib/api.js'
import { buildCommentTree, canDeleteComment } from '../lib/comments.js'
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

// Reply UI state: which comment (top-level or reply) currently has its reply box open, keyed by
// comment id. Only one open at a time keeps this simple (matches Task 2's yankBusy pattern).
const replyingTo = ref(null)
const replyDraft = ref('')
const replying = ref(false)
const replyError = ref(null)

// Delete in-flight/error state, keyed by comment id.
const deleteBusy = ref(null)
const deleteError = ref(null)

const tree = computed(() => buildCommentTree(comments.value))

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

function toggleReply(commentId) {
  if (replyingTo.value === commentId) {
    replyingTo.value = null
    replyDraft.value = ''
    replyError.value = null
    return
  }
  replyingTo.value = commentId
  replyDraft.value = ''
  replyError.value = null
}

async function submitReply(parentId) {
  if (!replyDraft.value.trim()) return
  replying.value = true
  replyError.value = null
  try {
    await postComment(props.namespace, props.name, replyDraft.value.trim(), parentId)
    replyDraft.value = ''
    replyingTo.value = null
    await load()
  } catch (err) {
    replyError.value = err.message
  } finally {
    replying.value = false
  }
}

async function removeComment(commentId) {
  if (!window.confirm(t('comment-rating.deleteConfirm'))) return
  deleteBusy.value = commentId
  deleteError.value = null
  try {
    await deleteComment(props.namespace, props.name, commentId)
    await load()
  } catch (err) {
    deleteError.value = err.message
  } finally {
    deleteBusy.value = null
  }
}

function canDelete(comment) {
  return canDeleteComment(comment, auth.username)
}

watch(() => [props.namespace, props.name], load)
onMounted(load)
</script>

<template>
  <section class="comments">
    <h3>{{ t('comment-rating.commentsTitle') }}</h3>

    <p v-if="loading" class="hint">{{ t('common.loading') }}</p>
    <p v-else-if="error" class="error">{{ t('errors.loadFailed', { error }) }}</p>
    <p v-else-if="tree.length === 0" class="hint">{{ t('comment-rating.noComments') }}</p>

    <ul v-else class="comment-list">
      <li v-for="c in tree" :key="c.id" class="comment-thread">
        <div class="comment" :class="{ deleted: c.deleted }">
          <span class="comment-author">{{ c.author }}</span>
          <span class="comment-time">{{ formatDateTime(c.createdAt) }}</span>
          <p class="comment-body">{{ c.body }}</p>
          <div class="comment-actions">
            <button v-if="auth.isAuthenticated && !c.deleted" type="button" class="link-button" @click="toggleReply(c.id)">
              {{ replyingTo === c.id ? t('comment-rating.cancelReply') : t('comment-rating.reply') }}
            </button>
            <button v-if="canDelete(c)" type="button" class="link-button danger" :disabled="deleteBusy === c.id" @click="removeComment(c.id)">
              {{ deleteBusy === c.id ? t('comment-rating.deleting') : t('comment-rating.delete') }}
            </button>
          </div>

          <div v-if="replyingTo === c.id" class="reply-form">
            <textarea v-model="replyDraft" rows="2" :placeholder="t('comment-rating.replyPlaceholder')" />
            <button type="button" :disabled="!replyDraft.trim() || replying" @click="submitReply(c.id)">
              {{ replying ? t('comment-rating.posting') : t('comment-rating.postReply') }}
            </button>
            <p v-if="replyError" class="error">{{ replyError }}</p>
          </div>
        </div>

        <ul v-if="c.replies.length" class="reply-list">
          <li v-for="r in c.replies" :key="r.id" class="comment reply" :class="{ deleted: r.deleted }">
            <span class="comment-author">{{ r.author }}</span>
            <span class="comment-time">{{ formatDateTime(r.createdAt) }}</span>
            <p class="comment-body">{{ r.body }}</p>
            <div class="comment-actions">
              <button v-if="auth.isAuthenticated && !r.deleted" type="button" class="link-button" @click="toggleReply(r.id)">
                {{ replyingTo === r.id ? t('comment-rating.cancelReply') : t('comment-rating.reply') }}
              </button>
              <button v-if="canDelete(r)" type="button" class="link-button danger" :disabled="deleteBusy === r.id" @click="removeComment(r.id)">
                {{ deleteBusy === r.id ? t('comment-rating.deleting') : t('comment-rating.delete') }}
              </button>
            </div>

            <div v-if="replyingTo === r.id" class="reply-form">
              <textarea v-model="replyDraft" rows="2" :placeholder="t('comment-rating.replyPlaceholder')" />
              <button type="button" :disabled="!replyDraft.trim() || replying" @click="submitReply(r.id)">
                {{ replying ? t('comment-rating.posting') : t('comment-rating.postReply') }}
              </button>
              <p v-if="replyError" class="error">{{ replyError }}</p>
            </div>
          </li>
        </ul>
      </li>
    </ul>

    <p v-if="deleteError" class="error">{{ t('comment-rating.deleteFailed', { error: deleteError }) }}</p>

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
.comment-thread {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.comment {
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  padding: 0.6rem 0.8rem;
}
.comment.deleted {
  opacity: 0.6;
}
.reply-list {
  list-style: none;
  margin: 0;
  padding-left: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  border-left: 2px solid #2a2a2a;
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
.comment-actions {
  display: flex;
  gap: 0.8rem;
  margin-top: 0.4rem;
}
.link-button {
  background: none;
  border: none;
  color: #80cbc4;
  cursor: pointer;
  padding: 0;
  font-size: 0.8rem;
}
.link-button:disabled {
  opacity: 0.5;
  cursor: default;
}
.link-button.danger {
  color: #e06c75;
}
.reply-form {
  margin-top: 0.5rem;
}
.reply-form textarea {
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
.reply-form button {
  margin-top: 0.4rem;
  padding: 0.3rem 0.8rem;
  border-radius: 6px;
  border: 1px solid #444;
  background: #1c1c1c;
  color: inherit;
  cursor: pointer;
  font-size: 0.8rem;
}
.reply-form button:disabled {
  opacity: 0.5;
  cursor: default;
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
