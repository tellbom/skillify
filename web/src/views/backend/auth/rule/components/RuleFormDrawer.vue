<template>
  <el-drawer
    v-model="visible"
    :title="drawerTitle"
    size="620px"
    direction="rtl"
    destroy-on-close
    class="rule-form-drawer"
    :before-close="handleBeforeClose"
  >
    <div class="drawer-body">
      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-position="top"
        class="rule-form"
        @submit.prevent
      >
        <!-- ── 基础字段 ──────────────────────────────────────── -->
        <div class="form-section">
          <div class="section-title">基础信息</div>

          <!-- 类型选择：value 使用后端小写值 -->
          <el-form-item label="规则类型" prop="type">
            <el-radio-group v-model="formData.type" @change="handleTypeChange">
              <el-radio-button value="menu_dir">
                <i class="fa fa-folder-o" /> 目录
              </el-radio-button>
              <el-radio-button value="menu">
                <i class="fa fa-file-o" /> 菜单
              </el-radio-button>
              <el-radio-button value="button">
                <i class="fa fa-hand-pointer-o" /> 按钮
              </el-radio-button>
            </el-radio-group>
          </el-form-item>

          <!-- 显示标题 -->
          <el-form-item label="显示标题" prop="title">
            <el-input
              v-model="formData.title"
              placeholder="在菜单和管理界面中显示的名称"
              clearable
            />
          </el-form-item>

          <!-- ruleCode -->
          <el-form-item label="规则码 (ruleCode)" prop="ruleCode">
            <el-input
              v-model="formData.ruleCode"
              :disabled="mode === 'edit'"
              placeholder="project 内唯一，例如：system.user"
              clearable
              @input="handleRuleCodeInput"
            />
            <div class="field-hint" v-if="mode === 'create'">
              规则码创建后不可修改，建议使用点分层级命名，例如
              <code>system.user</code>
            </div>
            <div class="field-hint warning" v-else>规则码不可修改</div>
          </el-form-item>

          <!-- permissionCode -->
          <el-form-item label="权限码 (permissionCode)" prop="permissionCode">
            <div class="permission-input-wrapper">
              <el-input
                v-model="formData.permissionCode"
                placeholder="例如：menu:system.user"
                clearable
              />
              <el-button
                size="small"
                class="auto-gen-btn"
                @click="autoGenPermissionCode"
                :disabled="!formData.ruleCode"
              >
                自动生成
              </el-button>
            </div>
            <div class="field-hint warning">
              ⚠ API 映射和权限组授权依赖此字段，修改会影响已有授权关系
            </div>
          </el-form-item>

          <!-- 父规则（button 类型必填） -->
          <el-form-item
            label="父规则"
            prop="parentRuleCode"
            :required="formData.type === 'button'"
          >
            <el-tree-select
              v-model="formData.parentRuleCode"
              :data="parentOptions"
              :props="{ label: 'title', value: 'ruleCode', children: 'children' }"
              placeholder="请选择父规则（按钮必选）"
              clearable
              filterable
              style="width: 100%"
              check-strictly
              :render-after-expand="false"
            />
            <div class="field-hint" v-if="formData.type === 'button'">
              按钮规则必须挂载到菜单或目录下
            </div>
          </el-form-item>
        </div>

        <!-- ── 路由配置（menu_dir / menu 时显示） ─────────────── -->
        <div class="form-section" v-if="formData.type !== 'button'">
          <div class="section-title">路由配置</div>

          <el-form-item label="路由名称 (name)">
            <el-input v-model="formData.name" placeholder="前端路由 name，默认取 ruleCode" clearable />
          </el-form-item>

          <el-form-item label="路由路径 (path)" prop="path">
            <el-input v-model="formData.path" placeholder="/system/user" clearable />
          </el-form-item>

          <!-- N4.6: 图标选择器（flow 的 RuleIconSelector + 依赖的图标字体/CDN 资源）未移植 ——
               依赖外部 iconfont CDN 资产和 flow 专属 utils（loadCss/loadJs/getUrl），在此环境
               中无法验证渲染效果，收益也低于风险，故简化为纯文本输入图标类名。 -->
          <el-form-item label="图标 (icon)">
            <el-input v-model="formData.icon" placeholder="图标类名，例如 el-icon-setting" clearable />
          </el-form-item>

          <!-- menuType 仅 menu 显示 -->
          <el-form-item label="菜单类型 (menuType)" v-if="formData.type === 'menu'">
            <el-select
              v-model="formData.menuType"
              placeholder="请选择菜单类型"
              clearable
              style="width: 100%"
            >
              <el-option label="Tab（标签页）" value="tab" />
              <el-option label="Link（外链）"  value="link" />
              <el-option label="Iframe（内嵌）" value="iframe" />
            </el-select>
          </el-form-item>

          <!-- 外链 URL -->
          <el-form-item
            label="外链 / Iframe URL"
            v-if="formData.type === 'menu' && ['link', 'iframe'].includes(formData.menuType)"
          >
            <el-input v-model="formData.url" placeholder="https://example.com" clearable />
          </el-form-item>

          <!-- 组件路径（tab 时显示） -->
          <el-form-item
            label="组件路径 (component)"
            v-if="formData.type === 'menu'"
          >
            <el-input
              v-model="formData.component"
              placeholder="/src/views/system/user/index.vue"
              clearable
            />
          </el-form-item>

          <!-- Keep-alive -->
          <el-form-item label="路由缓存 (keepalive)" v-if="formData.type === 'menu'">
            <el-switch
              v-model="formData.keepalive"
              :active-color="'#0066cc'"
              active-text="开启"
              inactive-text="关闭"
            />
            <div class="field-hint" style="margin-top:4px">开启后浏览器后退时页面状态保持</div>
          </el-form-item>

          <el-form-item label="扩展标记 (extend)">
            <el-input v-model="formData.extend" placeholder="例如：fullpage" clearable />
          </el-form-item>
        </div>

        <!-- ── 其他配置 ─────────────────────────────────────── -->
        <div class="form-section">
          <div class="section-title">其他配置</div>

          <el-form-item label="排序权重 (weigh)">
            <el-input-number
              v-model="formData.weigh"
              :min="0" :max="9999" :step="10"
              controls-position="right"
              style="width: 160px"
            />
            <div class="field-hint">数值越小越靠前，默认 0</div>
          </el-form-item>

          <el-form-item label="状态" v-if="mode === 'edit'">
            <el-radio-group v-model="formData.status">
              <el-radio-button value="Active">启用</el-radio-button>
              <el-radio-button value="Disabled">禁用</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="备注 (remark)">
            <el-input v-model="formData.remark" type="textarea" :rows="2" placeholder="可选备注信息" />
          </el-form-item>
        </div>
      </el-form>
    </div>

    <template #footer>
      <div class="drawer-footer">
        <el-button @click="handleCancel">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ mode === 'create' ? '创建规则' : '保存修改' }}
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createRule,
  updateRule,
  type RuleTreeNode,
  type RuleCreateForm,
  type RuleUpdateForm,
  type RecordStatus,
} from '/@/api/backend/rbac'

// ── Props / Emits ──────────────────────────────────────────────
interface Props {
  modelValue:  boolean
  mode:        'create' | 'edit'
  model:       RuleTreeNode | null
  parentRow:   RuleTreeNode | null
  ruleTree:    RuleTreeNode[]
}
const props = withDefaults(defineProps<Props>(), {
  modelValue: false,
  mode: 'create',
  model: null,
  parentRow: null,
  ruleTree: () => [],
})
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'submit'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const drawerTitle = computed(() => {
  if (props.mode === 'edit') return `编辑规则 · ${props.model?.title ?? ''}`
  if (props.parentRow) return `新增子规则 → ${props.parentRow.title}`
  return '新增规则'
})

// 父规则选项：过滤掉 button 节点（小写）
const parentOptions = computed(() => filterButtonNodes(props.ruleTree))

function filterButtonNodes(nodes: RuleTreeNode[]): RuleTreeNode[] {
  return nodes
    .filter(n => n.type !== 'button')
    .map(n => ({ ...n, children: filterButtonNodes(n.children ?? []) }))
}

// ── 表单数据（type 存后端小写值）─────────────────────────────
interface FormData {
  ruleCode:       string
  permissionCode: string
  title:          string
  type:           'menu_dir' | 'menu' | 'button'
  name:           string
  path:           string
  icon:           string
  parentRuleCode: string
  menuType:       string
  url:            string
  component:      string
  extend:         string
  remark:         string
  keepalive:      boolean
  weigh:          number
  status:         RecordStatus
}

const formRef    = ref()
const submitting = ref(false)
const formData   = reactive<FormData>({
  ruleCode:       '',
  permissionCode: '',
  title:          '',
  type:           'menu',
  name:           '',
  path:           '',
  icon:           '',
  parentRuleCode: '',
  menuType:       'tab',
  url:            '',
  component:      '',
  extend:         '',
  remark:         '',
  keepalive:      false,
  weigh:          0,
  status:         'Active',
})

const formRules = computed(() => ({
  ruleCode: [
    { required: true, message: '请输入规则码', trigger: 'blur' },
    { max: 128, message: '规则码最长 128 字符', trigger: 'blur' },
  ],
  permissionCode: [
    { required: true, message: '请输入权限码', trigger: 'blur' },
    {
      validator: (_: any, val: string, cb: (e?: Error) => void) => {
        if (!val.includes(':')) cb(new Error('格式：{类型}:{scope}，例如 menu:system.user'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
  title: [
    { required: true, message: '请输入显示标题', trigger: 'blur' },
    { max: 64, message: '标题最长 64 字符', trigger: 'blur' },
  ],
  type: [{ required: true, message: '请选择规则类型', trigger: 'change' }],
  parentRuleCode: formData.type === 'button'
    ? [{ required: true, message: '按钮规则必须选择父规则', trigger: 'change' }]
    : [],
}))

// ── 监听打开，初始化表单 ──────────────────────────────────────
watch(
  () => [props.modelValue, props.model, props.parentRow],
  () => {
    if (!props.modelValue) return

    if (props.mode === 'edit' && props.model) {
      const m = props.model
      // type 直接赋值，后端已返回小写
      formData.type           = (m.type as 'menu_dir' | 'menu' | 'button') ?? 'menu'
      formData.ruleCode       = m.ruleCode ?? ''
      formData.permissionCode = m.permissionCode ?? ''
      formData.title          = m.title ?? ''
      formData.name           = m.name ?? ''
      formData.path           = m.path ?? ''
      formData.icon           = m.icon ?? ''
      // menu_type 后端也是小写（tab/link/iframe），直接存
      formData.menuType       = m.menu_type ?? 'tab'
      formData.url            = m.url ?? ''
      formData.component      = m.component ?? ''
      formData.extend         = m.extend ?? ''
      formData.remark         = m.remark ?? ''
      formData.keepalive      = m.keepalive ?? false
      formData.weigh          = (m as any).weigh ?? 0
      formData.status         = ((m as any).status as RecordStatus) ?? 'Active'
      // 从树中反查父 ruleCode
      formData.parentRuleCode = findParentRuleCode(m.ruleCode, props.ruleTree) ?? ''
    } else {
      formData.ruleCode       = ''
      formData.permissionCode = ''
      formData.title          = ''
      formData.type           = 'menu'
      formData.name           = ''
      formData.path           = ''
      formData.icon           = ''
      formData.parentRuleCode = props.parentRow?.ruleCode ?? ''
      formData.menuType       = 'tab'
      formData.url            = ''
      formData.component      = ''
      formData.extend         = ''
      formData.remark         = ''
      formData.keepalive      = false
      formData.weigh          = 0
      formData.status         = 'Active'
    }
  },
  { immediate: true }
)

function findParentRuleCode(
  targetCode: string,
  nodes: RuleTreeNode[],
  parentCode = ''
): string | null {
  for (const node of nodes) {
    if (node.ruleCode === targetCode) return parentCode
    if (node.children?.length) {
      const found = findParentRuleCode(targetCode, node.children, node.ruleCode)
      if (found !== null) return found
    }
  }
  return null
}

// 类型切换：比较小写值，提交时直接用 formData.type
function handleTypeChange(type: string | number | boolean | undefined) {
  const ruleType = String(type || 'menu') as FormData['type']
  if (ruleType === 'button') {
    formData.path      = ''
    formData.menuType  = ''
    formData.url       = ''
    formData.component = ''
    formData.keepalive = false
  }
  if (formData.ruleCode) {
    formData.permissionCode = buildPermissionCode(formData.ruleCode, ruleType)
  }
}

// permissionCode 联动
function handleRuleCodeInput(val: string) {
  const expected = buildPermissionCode(formData.ruleCode, formData.type)
  if (!formData.permissionCode || formData.permissionCode === expected) {
    formData.permissionCode = buildPermissionCode(val, formData.type)
  }
}

function autoGenPermissionCode() {
  formData.permissionCode = buildPermissionCode(formData.ruleCode, formData.type)
}

/** 根据 ruleCode + type（小写）生成推荐 permissionCode */
function buildPermissionCode(ruleCode: string, type: string): string {
  if (!ruleCode) return ''
  return type === 'button' ? `button:${ruleCode}` : `menu:${ruleCode}`
}

// ── 提交：type 直接传后端小写值，无需转换 ────────────────────
async function handleSubmit() {
  try { await formRef.value.validate() } catch { return }

  submitting.value = true
  try {
    if (props.mode === 'create') {
      const payload: RuleCreateForm = {
        ruleCode:       formData.ruleCode.trim(),
        permissionCode: formData.permissionCode.trim(),
        title:          formData.title.trim(),
        type:           formData.type as any,
        weigh:          formData.weigh,
      }
      if (formData.name.trim())           payload.name           = formData.name.trim()
      if (formData.path.trim())           payload.path           = formData.path.trim()
      if (formData.icon.trim())           payload.icon           = formData.icon.trim()
      if (formData.parentRuleCode.trim()) payload.parentRuleCode = formData.parentRuleCode.trim()
      if (formData.menuType)              payload.menuType       = formData.menuType as any
      if (formData.url.trim())            payload.url            = formData.url.trim()
      if (formData.component.trim())      payload.component      = formData.component.trim()
      if (formData.extend.trim())         payload.extend         = formData.extend.trim()
      if (formData.remark.trim())         payload.remark         = formData.remark.trim()
      payload.keepalive = formData.keepalive

      await createRule(payload)
      ElMessage.success('规则创建成功')
    } else {
      const payload: RuleUpdateForm = {
        title:          formData.title.trim()          || null,
        permissionCode: formData.permissionCode.trim() || null,
        name:           formData.name.trim()           || null,
        path:           formData.path.trim()           || null,
        icon:           formData.icon.trim()           || null,
        parentRuleCode: formData.parentRuleCode        || null,
        menuType:       (formData.menuType as any)     || null,
        url:            formData.url.trim()            || null,
        component:      formData.component.trim()      || null,
        extend:         formData.extend.trim()         || null,
        remark:         formData.remark.trim()         || null,
        keepalive:      formData.keepalive,
        weigh:          formData.weigh,
        status:         formData.status,
      }
      await updateRule(formData.ruleCode, payload)
      ElMessage.success('规则已更新')
    }
    emit('submit')
    visible.value = false
  } catch {
    // 统一处理
  } finally {
    submitting.value = false
  }
}

function handleCancel() { visible.value = false }

async function handleBeforeClose(done: () => void) {
  const hasInput = formData.title || formData.ruleCode
  if (hasInput && props.mode === 'create') {
    try {
      await ElMessageBox.confirm('有未保存的内容，确定关闭？', '提示', {
        confirmButtonText: '关闭', cancelButtonText: '继续编辑', type: 'warning',
      })
      done()
    } catch { /* 继续编辑 */ }
  } else {
    done()
  }
}
</script>

<style scoped>
.rule-form-drawer { font-family: 'SF Pro Text', system-ui, -apple-system, sans-serif; }

.drawer-body { padding: 0 20px 20px; height: 100%; overflow-y: auto; }

.form-section {
  margin-bottom: 8px; margin-top: 16px;
  border: 1px solid #e5e5e5; border-radius: 10px;
  padding: 16px 20px 8px; background: #fff;
}
.form-section:first-child { margin-top: 8px; }

.section-title {
  font-size: 13px; font-weight: 600; color: #86868b;
  letter-spacing: 0.5px; text-transform: uppercase; margin-bottom: 16px;
}

.field-hint { margin-top: 5px; font-size: 12px; color: #86868b; line-height: 1.4; letter-spacing: -0.12px; }
.field-hint.warning { color: #c0392b; }
.field-hint code {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  background: #f5f5f7; padding: 1px 4px; border-radius: 3px; font-size: 11px;
}

.permission-input-wrapper { display: flex; gap: 8px; width: 100%; }
.permission-input-wrapper .el-input { flex: 1; }
.auto-gen-btn { flex-shrink: 0; white-space: nowrap; }

:deep(.el-form-item__label) {
  font-size: 13px; font-weight: 600; color: #1d1d1f;
  letter-spacing: -0.12px; margin-bottom: 6px;
}
:deep(.el-input__wrapper.is-focus),
:deep(.el-select .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgba(0, 102, 204, 0.2) !important;
}
:deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background-color: #0066cc; border-color: #0066cc; box-shadow: -1px 0 0 0 #0066cc;
}
:deep(.el-switch.is-checked .el-switch__core) {
  background-color: #0066cc !important; border-color: #0066cc !important;
}
:deep(.el-button--primary) { background-color: #0066cc; border-color: #0066cc; }
:deep(.el-button--primary:hover) { background-color: #0071e3; border-color: #0071e3; }
:deep(.el-tree-select .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgba(0, 102, 204, 0.2) !important;
}

.drawer-footer {
  display: flex; justify-content: flex-end; gap: 12px;
  padding: 16px 20px; border-top: 1px solid #e5e7eb;
}
</style>
