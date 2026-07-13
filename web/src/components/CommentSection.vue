<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getComments, postComment, deleteComment } from '../lib/api.js'
import { buildCommentTree, canDeleteComment, avatarColorFor } from '../lib/comments.js'
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
    <div class="comments-head">
      <h2 class="comments-title">{{ t('comment-rating.commentsTitle') }}</h2>
      <span v-if="!loading && !error" class="comments-count">{{ tree.length }}</span>
    </div>

    <div class="comment-form">
      <textarea v-model="draft" :placeholder="t('comment-rating.addCommentPlaceholder')" />
      <div class="form-row">
        <button type="button" class="submit-btn" :disabled="!draft.trim() || posting" @click="submit">
          {{ posting ? t('comment-rating.posting') : t('comment-rating.postComment') }}
        </button>
        <span v-if="postError" class="error">{{ postError }}</span>
      </div>
    </div>
    <p v-if="!auth.isAuthenticated" class="hint">{{ t('comment-rating.loginToComment') }}</p>

    <p v-if="loading" class="hint">{{ t('common.loading') }}</p>
    <p v-else-if="error" class="error">{{ t('errors.loadFailed', { error }) }}</p>
    <div v-else-if="tree.length === 0" class="empty-box">{{ t('comment-rating.noComments') }}</div>

    <div v-else class="comment-list">
      <template v-for="c in tree" :key="c.id">
        <div class="comment-row">
          <div v-if="c.deleted" class="deleted-placeholder">{{ t('comment-rating.deletedPlaceholder') }}</div>
          <template v-else>
            <div class="comment-meta">
              <div class="avatar" :style="{ background: avatarColorFor(c.author) }">{{ c.author.slice(0, 2).toUpperCase() }}</div>
              <span class="comment-author">{{ c.author }}</span>
              <span class="comment-time">{{ formatDateTime(c.createdAt) }}</span>
            </div>
            <p class="comment-body">{{ c.body }}</p>
            <div class="comment-actions">
              <button v-if="auth.isAuthenticated" type="button" class="link-button" @click="toggleReply(c.id)">
                {{ replyingTo === c.id ? t('comment-rating.cancelReply') : t('comment-rating.reply') }}
              </button>
              <button v-if="canDelete(c)" type="button" class="link-button danger" :disabled="deleteBusy === c.id" @click="removeComment(c.id)">
                {{ deleteBusy === c.id ? t('comment-rating.deleting') : t('comment-rating.delete') }}
              </button>
            </div>

            <div v-if="replyingTo === c.id" class="reply-form">
              <textarea v-model="replyDraft" :placeholder="t('comment-rating.replyPlaceholder')" />
              <div class="form-row">
                <button type="button" class="submit-btn submit-btn-sm" :disabled="!replyDraft.trim() || replying" @click="submitReply(c.id)">
                  {{ replying ? t('comment-rating.posting') : t('comment-rating.postReply') }}
                </button>
                <button type="button" class="link-button" @click="toggleReply(c.id)">{{ t('comment-rating.cancelReply') }}</button>
                <span v-if="replyError" class="error">{{ replyError }}</span>
              </div>
            </div>
          </template>
        </div>

        <div v-for="r in c.replies" :key="r.id" class="comment-row reply-row">
          <div v-if="r.deleted" class="deleted-placeholder">{{ t('comment-rating.deletedPlaceholder') }}</div>
          <template v-else>
            <div class="comment-meta">
              <div class="avatar" :style="{ background: avatarColorFor(r.author) }">{{ r.author.slice(0, 2).toUpperCase() }}</div>
              <span class="comment-author">{{ r.author }}</span>
              <span class="comment-time">{{ formatDateTime(r.createdAt) }}</span>
            </div>
            <p class="comment-body">{{ r.body }}</p>
            <div class="comment-actions">
              <button v-if="auth.isAuthenticated" type="button" class="link-button" @click="toggleReply(r.id)">
                {{ replyingTo === r.id ? t('comment-rating.cancelReply') : t('comment-rating.reply') }}
              </button>
              <button v-if="canDelete(r)" type="button" class="link-button danger" :disabled="deleteBusy === r.id" @click="removeComment(r.id)">
                {{ deleteBusy === r.id ? t('comment-rating.deleting') : t('comment-rating.delete') }}
              </button>
            </div>

            <div v-if="replyingTo === r.id" class="reply-form">
              <textarea v-model="replyDraft" :placeholder="t('comment-rating.replyPlaceholder')" />
              <div class="form-row">
                <button type="button" class="submit-btn submit-btn-sm" :disabled="!replyDraft.trim() || replying" @click="submitReply(r.id)">
                  {{ replying ? t('comment-rating.posting') : t('comment-rating.postReply') }}
                </button>
                <button type="button" class="link-button" @click="toggleReply(r.id)">{{ t('comment-rating.cancelReply') }}</button>
                <span v-if="replyError" class="error">{{ replyError }}</span>
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>

    <p v-if="deleteError" class="error">{{ t('comment-rating.deleteFailed', { error: deleteError }) }}</p>
  </section>
</template>

<style scoped>
.comments {
  margin-top: 28px;
  border-top: 1px solid #232323;
  padding-top: 20px;
}
.comments-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 16px;
}
.comments-title {
  font-size: 16px;
  font-weight: 650;
  margin: 0;
  color: #ededed;
}
.comments-count {
  font-size: 13px;
  color: #6e6e6e;
}
.hint {
  color: #9f9f9f;
  font-size: 13.5px;
}
.error {
  color: #e5807a;
  font-size: 12.5px;
}
.empty-box {
  border: 1px dashed #2c2c2c;
  border-radius: 10px;
  padding: 36px 20px;
  text-align: center;
  color: #6e6e6e;
  font-size: 13.5px;
}

.comment-form {
  margin-bottom: 22px;
}
.comment-form textarea,
.reply-form textarea {
  width: 100%;
  box-sizing: border-box;
  background: #1c1c1c;
  border: 1px solid #2c2c2c;
  border-radius: 10px;
  padding: 12px 14px;
  color: #e5e5e5;
  font-size: 13.5px;
  font-family: inherit;
  outline: none;
  line-height: 1.55;
  resize: vertical;
  min-height: 82px;
}
.comment-form textarea:focus,
.reply-form textarea:focus {
  border-color: #80cbc4;
}
.reply-form textarea {
  min-height: 60px;
  border-radius: 8px;
  font-size: 13px;
}
.form-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}
.submit-btn {
  padding: 8px 18px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  background: #80cbc4;
  color: #0f1615;
}
.submit-btn:disabled {
  cursor: not-allowed;
  background: #232323;
  color: #6e6e6e;
}
.submit-btn-sm {
  padding: 6px 14px;
  border-radius: 7px;
  font-size: 12.5px;
}

.comment-list {
  display: flex;
  flex-direction: column;
}
.comment-row {
  padding: 14px 0;
  border-top: 1px solid #1e1e1e;
}
.reply-row {
  margin-left: 33px;
  padding-left: 16px;
  border-left: 1px solid #232323;
}
.deleted-placeholder {
  padding: 12px 0;
  font-size: 13px;
  color: #6e6e6e;
  font-style: italic;
}
.comment-meta {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 6px;
}
.avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10.5px;
  font-weight: 700;
  color: #0f1615;
  flex: none;
}
.comment-author {
  font-size: 13px;
  font-weight: 600;
  color: #e5e5e5;
}
.comment-time {
  font-size: 11.5px;
  color: #6e6e6e;
}
.comment-body {
  font-size: 13.5px;
  color: #c9c9c9;
  line-height: 1.6;
  margin: 0 0 8px 33px;
  white-space: pre-wrap;
}
.comment-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-left: 33px;
}
.link-button {
  background: none;
  border: none;
  color: #9f9f9f;
  cursor: pointer;
  padding: 0;
  font-size: 12px;
}
.link-button:hover {
  color: #80cbc4;
}
.link-button:disabled {
  opacity: 0.5;
  cursor: default;
}
.link-button.danger:hover {
  color: #e5807a;
}
.reply-form {
  margin: 12px 0 4px 33px;
}
</style>
