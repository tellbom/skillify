<template>
  <el-drawer
    v-model="visible"
    :title="mode === 'create' ? '新增管理员' : `编辑管理员 · ${model?.username ?? ''}`"
    size="560px"
    direction="rtl"
    destroy-on-close
    class="admin-form-drawer"
  >
    <div class="drawer-body">
      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-position="top"
        class="admin-form"
      >

        <!-- ══ 新增模式 ════════════════════════════════════════ -->
        <template v-if="mode === 'create'">

          <!-- 选择人员 -->
          <el-form-item label="选择人员" prop="selectedCount">
            <div class="user-select-area">
              <!-- 已选 Tags -->
              <div class="selected-tags" v-if="selectedUsers.length > 0">
                <el-tag
                  v-for="user in selectedUsers"
                  :key="user.id"
                  closable
                  size="default"
                  class="user-tag"
                  @close="removeUser(user.id)"
                >
                  <span class="tag-name">{{ user.name }}</span>
                  <code class="tag-workno">{{ user.workNo }}</code>
                </el-tag>
              </div>
              <div class="empty-tip" v-else>
                尚未选择人员，点击下方按钮从通讯录选取
              </div>
              <el-button
                :icon="UserFilled"
                :type="selectedUsers.length > 0 ? 'default' : 'primary'"
                :plain="selectedUsers.length > 0"
                @click="openContactDialog"
              >
                {{ selectedUsers.length > 0 ? `已选 ${selectedUsers.length} 人，重新选择` : '从通讯录选择' }}
              </el-button>
            </div>
            <div class="field-hint">工号将自动作为用户 ID（userid）</div>
          </el-form-item>

          <!-- 单人时允许手动覆盖 userid -->
          <el-form-item
            label="自定义用户ID（可选）"
            v-if="selectedUsers.length === 1"
          >
            <el-input
              v-model="formData.manualUserid"
              :placeholder="`默认使用工号 ${selectedUsers[0]?.workNo}`"
              clearable
            />
            <div class="field-hint">留空则使用工号作为 userid</div>
          </el-form-item>

        </template>

        <!-- ══ 编辑模式 ════════════════════════════════════════ -->
        <template v-else>
          <el-form-item label="用户ID">
            <el-input :value="model?.userid" disabled />
            <div class="field-hint">用户 ID 不可修改</div>
          </el-form-item>

          <el-form-item label="显示名称" prop="username">
            <el-input
              v-model="formData.username"
              placeholder="请输入显示名称"
              clearable
            />
          </el-form-item>

          <el-form-item label="状态">
            <el-radio-group v-model="formData.status">
              <el-radio-button value="Active">启用</el-radio-button>
              <el-radio-button value="Disabled">禁用</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </template>

        <!-- ══ 权限组（新增/编辑均显示） ════════════════════════ -->
        <el-form-item label="权限组">
          <el-select
            v-model="formData.groupCodes"
            multiple
            filterable
            clearable
            placeholder="请选择权限组（可留空）"
            style="width: 100%"
            :loading="groupLoading"
          >
            <el-option
              v-for="opt in groupOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
          <div class="field-hint" v-if="mode === 'create' && selectedUsers.length > 1">
            所选权限组对全部 {{ selectedUsers.length }} 个新增用户生效
          </div>
          <div class="field-hint" v-else-if="mode === 'edit'">
            提交全量目标权限组，服务端自动 diff 增减
          </div>
        </el-form-item>

        <!-- ══ 批量预览（新增有选人时显示） ═══════════════════════ -->
        <div class="batch-preview" v-if="mode === 'create' && selectedUsers.length > 0">
          <div class="preview-header">
            <i class="fa fa-info-circle" />
            即将创建 <strong>{{ selectedUsers.length }}</strong> 个管理员账号
          </div>
          <div class="preview-list">
            <div v-for="user in selectedUsers" :key="user.id" class="preview-row">
              <code class="preview-userid">{{ resolveUserid(user) }}</code>
              <span class="preview-name">{{ user.name }}</span>
              <span class="preview-arrow">→</span>
              <span class="preview-groups" v-if="formData.groupCodes.length">
                {{ formData.groupCodes.join(', ') }}
              </span>
              <span class="preview-nogroup" v-else>暂无权限组</span>
            </div>
          </div>
        </div>

      </el-form>
    </div>

    <!-- 底部 -->
    <template #footer>
      <div class="drawer-footer">
        <el-button @click="handleCancel">取消</el-button>
        <el-button
          type="primary"
          :loading="submitting"
          :disabled="mode === 'create' && selectedUsers.length === 0"
          @click="handleSubmit"
        >
          {{ submitLabel }}
        </el-button>
      </div>
    </template>
  </el-drawer>

  <!-- ══ ContactSelector 独立弹窗 ══════════════════════════════ -->
  <el-dialog
    v-model="contactDialogVisible"
    title="选择人员"
    width="860px"
    :close-on-click-modal="false"
    destroy-on-close
    class="contact-dialog"
    append-to-body
  >
    <ContactSelector
      :orgList="mockOrgList"
      :userList="mockUserList"
      :multiple="true"
      @confirm="handleContactConfirm"
      @cancel="contactDialogVisible = false"
    />
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { UserFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ContactSelector from '/@/components/ContactSelector.vue'
import {
  createAdmin,
  updateAdmin,
  getGroupIndex,
  type AdminItem,
} from '/@/api/backend/rbac'

// ── Props / Emits ──────────────────────────────────────────────
interface Props {
  modelValue: boolean
  mode: 'create' | 'edit'
  model: AdminItem | null
}
const props = withDefaults(defineProps<Props>(), {
  modelValue: false,
  mode: 'create',
  model: null,
})
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'submit'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

// ── 提交按钮文案 ───────────────────────────────────────────────
const submitLabel = computed(() => {
  if (props.mode === 'edit') return '保存修改'
  const n = selectedUsers.value.length
  return n > 0 ? `创建 ${n} 个账号` : '创建账号'
})

// ── ContactSelector 弹窗 ───────────────────────────────────────
const contactDialogVisible = ref(false)

type SelectedUser = {
  id: string; name: string; workNo: string
  phone: string; position: string; orgId: string; orgName: string
}

const selectedUsers = ref<SelectedUser[]>([])

function openContactDialog() {
  contactDialogVisible.value = true
}

function handleContactConfirm(users: SelectedUser[]) {
  selectedUsers.value = users
  contactDialogVisible.value = false
}

function removeUser(id: string) {
  selectedUsers.value = selectedUsers.value.filter(u => u.id !== id)
}

// ── 表单数据 ───────────────────────────────────────────────────
interface FormData {
  username:     string
  status:       'Active' | 'Disabled'
  groupCodes:   string[]
  manualUserid: string
}

const formRef    = ref()
const submitting = ref(false)
const formData   = reactive<FormData>({
  username:     '',
  status:       'Active',
  groupCodes:   [],
  manualUserid: '',
})

const formRules = computed(() => ({
  username: props.mode === 'edit'
    ? [{ required: true, message: '请输入显示名称', trigger: 'blur' }]
    : [],
}))

// ── 解析 userid ────────────────────────────────────────────────
function resolveUserid(user: SelectedUser): string {
  if (selectedUsers.value.length === 1 && formData.manualUserid.trim()) {
    return formData.manualUserid.trim()
  }
  return user.workNo
}

// ── 权限组选项（适配实际旧格式） ──────────────────────────────
const groupOptions = ref<{ label: string; value: string }[]>([])
const groupLoading = ref(false)

async function loadGroupOptions() {
  groupLoading.value = true
  try {
    const result = await getGroupIndex({ select: true }) as any
    if (Array.isArray(result?.options)) {
      // 实际返回：{ options: [{id, pid, name, rules, status, ...}] }
      groupOptions.value = result.options.map((item: any) => ({
        value: String(item.id),
        label: String(item.name).replace(/^[\s└─├│]+/, '').trim(),
      }))
    } else if (Array.isArray(result?.list)) {
      groupOptions.value = flattenGroupTree(result.list)
    } else {
      groupOptions.value = []
    }
  } catch {
    groupOptions.value = []
  } finally {
    groupLoading.value = false
  }
}

function flattenGroupTree(
  nodes: any[],
  acc: { label: string; value: string }[] = []
): { label: string; value: string }[] {
  for (const n of nodes) {
    acc.push({ value: n.groupCode ?? n.id, label: n.groupName ?? n.name })
    if (n.children?.length) flattenGroupTree(n.children, acc)
  }
  return acc
}

// ── Mock 数据（接口就绪后替换） ────────────────────────────────
const mockOrgList = [
  { id: 'org-1',   pid: null,    name: '总公司' },
  { id: 'org-1-1', pid: 'org-1', name: '技术部' },
  { id: 'org-1-2', pid: 'org-1', name: '运营部' },
  { id: 'org-1-3', pid: 'org-1', name: '财务部' },
  { id: 'org-2',   pid: null,    name: '分公司' },
  { id: 'org-2-1', pid: 'org-2', name: '市场部' },
]

const mockUserList = [
  { id: 'u001', name: '张三',   workNo: '196001', phone: '13800000001', position: '前端工程师', orgId: 'org-1-1' },
  { id: 'u002', name: '李四',   workNo: '196002', phone: '13800000002', position: '后端工程师', orgId: 'org-1-1' },
  { id: 'u003', name: '王五',   workNo: '196003', phone: '13800000003', position: '产品经理',   orgId: 'org-1-2' },
  { id: 'u004', name: '赵六',   workNo: '196004', phone: '13800000004', position: '运营专员',   orgId: 'org-1-2' },
  { id: 'u005', name: '孙七',   workNo: 'EMP005', phone: '13800000005', position: '财务主管',   orgId: 'org-1-3' },
  { id: 'u006', name: '周八',   workNo: 'EMP006', phone: '13800000006', position: '市场总监',   orgId: 'org-2-1' },
  { id: 'u007', name: '吴九',   workNo: 'EMP007', phone: '13800000007', position: '架构师',     orgId: 'org-1-1' },
  { id: 'u008', name: '郑十',   workNo: 'EMP008', phone: '13800000008', position: '测试工程师', orgId: 'org-1-1' },
  { id: 'u009', name: '陈一一', workNo: 'EMP009', phone: '13800000009', position: '数据分析师', orgId: 'org-1-2' },
  { id: 'u010', name: '冯一二', workNo: 'EMP010', phone: '13800000010', position: '客户经理',   orgId: 'org-2-1' },
]

// ── 监听打开 ───────────────────────────────────────────────────
watch(
  () => [props.modelValue, props.mode, props.model],
  () => {
    if (!props.modelValue) return
    loadGroupOptions()

    if (props.mode === 'create') {
      selectedUsers.value   = []
      formData.groupCodes   = []
      formData.manualUserid = ''
    } else if (props.mode === 'edit' && props.model) {
      formData.username   = props.model.username
      formData.status     = props.model.status
      formData.groupCodes = [...(props.model.groupCodes ?? [])]
    }
  },
  { immediate: true }
)

// ── 提交 ───────────────────────────────────────────────────────
async function handleSubmit() {
  try { await formRef.value?.validate() } catch { return }

  submitting.value = true
  try {
    if (props.mode === 'create') {
      if (selectedUsers.value.length === 0) return

      const results = { success: 0, fail: 0, failNames: [] as string[] }
      await Promise.allSettled(
        selectedUsers.value.map(async (user) => {
          try {
            await createAdmin({
              userid:    resolveUserid(user),
              username:  user.name,
              groupCode: formData.groupCodes.length ? formData.groupCodes : undefined,
            })
            results.success++
          } catch {
            results.fail++
            results.failNames.push(user.name)
          }
        })
      )

      if (results.fail === 0) {
        ElMessage.success(`成功创建 ${results.success} 个管理员账号`)
      } else {
        ElMessage.warning(
          `成功 ${results.success} 个，失败 ${results.fail} 个（${results.failNames.join('、')}）`
        )
      }
    } else {
      await updateAdmin(props.model!.userid, {
        username: formData.username.trim() || null,
        status:   formData.status,
        groupArr: formData.groupCodes,
      })
      ElMessage.success('管理员信息已更新')
    }

    emit('submit')
    visible.value = false
  } catch {
    // 统一处理
  } finally {
    submitting.value = false
  }
}

function handleCancel() {
  visible.value = false
}
</script>

<style scoped>
.admin-form-drawer {
  font-family: 'SF Pro Text', system-ui, -apple-system, sans-serif;
}

.drawer-body {
  padding: 0 20px 20px;
  height: 100%;
  overflow-y: auto;
}

.admin-form {
  padding: 16px 0 4px;
}

/* ── 选人区域 ─────────────────────────────────────────────────── */
.user-select-area {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.selected-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 12px;
  background: #f5f5f7;
  border: 1px solid #e5e5e5;
  border-radius: 8px;
  min-height: 48px;
  align-items: center;
}

.empty-tip {
  padding: 10px 12px;
  background: #f5f5f7;
  border: 1px dashed #d0d0d0;
  border-radius: 8px;
  font-size: 13px;
  color: #86868b;
  text-align: center;
}

.user-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid #cce0ff;
  color: #1d1d1f;
}

.tag-name {
  font-size: 13px;
  font-weight: 500;
}

.tag-workno {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #0066cc;
  background: #f0f6ff;
  padding: 1px 4px;
  border-radius: 3px;
}

/* ── 批量预览 ─────────────────────────────────────────────────── */
.batch-preview {
  margin-top: 4px;
  padding: 12px 14px;
  background: #f0f6ff;
  border: 1px solid #cce0ff;
  border-radius: 8px;
}

.preview-header {
  font-size: 13px;
  color: #1d4e8a;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.preview-header .fa { color: #0066cc; }

.preview-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  max-height: 140px;
  overflow-y: auto;
}

.preview-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #1d4e8a;
}

.preview-userid {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  background: #ddeeff;
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
  min-width: 68px;
}

.preview-name  { font-weight: 500; min-width: 52px; }
.preview-arrow { color: #86868b; }

.preview-groups {
  color: #0066cc;
  font-size: 11px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}

.preview-nogroup { color: #86868b; font-size: 11px; }

/* ── 提示文字 ─────────────────────────────────────────────────── */
.field-hint {
  margin-top: 5px;
  font-size: 12px;
  color: #86868b;
  line-height: 1.4;
  letter-spacing: -0.12px;
}

/* ── 表单控件 ─────────────────────────────────────────────────── */
:deep(.el-form-item__label) {
  font-size: 13px;
  font-weight: 600;
  color: #1d1d1f;
  letter-spacing: -0.12px;
  margin-bottom: 6px;
}

:deep(.el-input__wrapper.is-focus),
:deep(.el-select .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgba(0, 102, 204, 0.2) !important;
}

:deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background-color: #0066cc;
  border-color: #0066cc;
  box-shadow: -1px 0 0 0 #0066cc;
}

:deep(.el-button--primary) {
  background-color: #0066cc;
  border-color: #0066cc;
}
:deep(.el-button--primary:hover) {
  background-color: #0071e3;
  border-color: #0071e3;
}

/* ── 底部 ─────────────────────────────────────────────────────── */
.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid #e5e7eb;
}

/* ── ContactSelector Dialog ──────────────────────────────────── */
:deep(.contact-dialog .el-dialog__body) {
  padding: 0;
}

:deep(.contact-dialog .el-dialog__header) {
  padding: 16px 20px 14px;
  border-bottom: 1px solid #e5e5e5;
  margin-bottom: 0;
}
</style>
