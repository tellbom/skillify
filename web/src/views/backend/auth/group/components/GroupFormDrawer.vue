<template>
  <el-drawer
    v-model="visible"
    :title="mode === 'create' ? '新增权限组' : `编辑权限组 · ${model?.groupName ?? ''}`"
    size="620px"
    direction="rtl"
    destroy-on-close
  >
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-position="top"
      class="group-form"
    >
      <!-- groupCode -->
      <el-form-item label="组编码 (groupCode)" prop="groupCode" v-if="mode === 'create'">
        <el-input v-model="formData.groupCode" placeholder="留空则自动生成，建议：ops_admin" clearable />
        <div class="field-hint">创建后不可修改；留空由服务端生成 group_&lt;uuid&gt;</div>
      </el-form-item>
      <el-form-item label="组编码 (groupCode)" v-else>
        <el-input :value="model?.groupCode" disabled />
      </el-form-item>

      <!-- 组名称 -->
      <el-form-item label="组名称 (groupName)" prop="groupName">
        <el-input v-model="formData.groupName" placeholder="例如：运营管理员" clearable />
      </el-form-item>

      <!-- 父组 -->
      <el-form-item label="父权限组 (parentGroupCode)">
        <el-tree-select
          v-model="formData.parentGroupCode"
          :data="parentGroupOptions"
          :props="{ label: 'label', value: 'value', children: 'children' }"
          placeholder="不选则为根组" clearable filterable
          style="width: 100%" check-strictly :render-after-expand="false"
        />
        <div class="field-hint">设置后该组继承父组的权限范围约束</div>
      </el-form-item>

      <!-- 状态（编辑时） -->
      <el-form-item label="状态" v-if="mode === 'edit'">
        <el-radio-group v-model="formData.status">
          <el-radio-button value="Active">启用</el-radio-button>
          <el-radio-button value="Disabled">禁用</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <!-- ══ 规则授权树（仅新增） ════════════════════════════════ -->
      <el-form-item label="初始规则授权" v-if="mode === 'create'">
        <div class="tree-section">
          <div class="tree-toolbar">
            <div class="toolbar-left">
              <el-button size="small" text @click="checkAll">全选</el-button>
              <el-divider direction="vertical" />
              <el-button size="small" text @click="checkNone">清空</el-button>
              <el-divider direction="vertical" />
              <span class="check-count">已选 <strong>{{ checkedCount }}</strong> 项</span>
            </div>
            <el-input
              v-model="treeSearch" size="small" placeholder="搜索规则"
              clearable style="width: 150px" :prefix-icon="Search"
            />
          </div>
          <div class="info-tip">
            <i class="fa fa-info-circle" />
            父子节点互不级联，提交时仅包含当前手动勾选的规则。
          </div>
          <el-tree
            ref="treeRef"
            :data="filteredRuleTree"
            :props="{ label: 'title', children: 'children' }"
            node-key="ruleCode" show-checkbox
            check-strictly
            :default-expand-all="true"
            :filter-node-method="filterNode"
            class="rule-tree"
            @check="() => updateCheckedCount()"
          >
            <template #default="{ data }">
              <span class="tree-node">
                <span :class="`node-badge node-badge--${data.type}`">{{ getTypeShort(data.type) }}</span>
                <span class="node-title">{{ data.title }}</span>
                <code class="node-code">{{ data.ruleCode }}</code>
              </span>
            </template>
          </el-tree>
        </div>
        <div class="field-hint" style="margin-top:8px">
          提交 <code>ruleCode</code> 列表，服务端推导 permissionCodes。编辑已有权限组的规则请使用「授权规则」按钮。
        </div>
      </el-form-item>

      <!-- ══ 额外 API 端点权限（新增 + 编辑都显示）═════════════ -->
      <el-form-item label="额外 API 端点权限">

        <!-- 说明 -->
        <div class="extra-info">
          <i class="fa fa-info-circle" style="color: #0066cc; flex-shrink:0" />
          <span>
            追加直接来自 API 映射的权限码，不依赖规则树推导。
            最终授权 = 规则推导值 ∪ 额外权限码。
          </span>
        </div>

        <!-- 已选 Tags -->
        <div class="extra-tags" v-if="extraPermCodes.length">
          <el-tag
            v-for="code in extraPermCodes" :key="code"
            closable size="small" class="extra-tag"
            @close="removeExtraCode(code)"
          >{{ code }}</el-tag>
        </div>

        <!-- API 列表区域：固定高度，打开抽屉时直接渲染 -->
        <div class="api-panel">
          <!-- 过滤栏 -->
          <div class="api-panel-toolbar">
            <el-input
              v-model="apiSearch" size="small"
              placeholder="搜索权限码 / 标题" clearable
              :prefix-icon="Search" style="flex:1"
            />
            <el-select
              v-model="apiActionFilter" size="small"
              placeholder="全部 Action" clearable style="width:120px"
            >
              <el-option v-for="a in API_ACTIONS" :key="a" :label="a" :value="a" />
            </el-select>
          </div>

          <!-- 列表体：固定高度 220px，内部滚动，绝不撑开抽屉 -->
          <div class="api-list" v-loading="apiMapLoading">
            <template v-if="filteredApiOptions.length">
              <div
                v-for="item in filteredApiOptions" :key="item.permissionCode"
                class="api-item"
                :class="{ 'is-selected': extraPermCodes.includes(item.permissionCode) }"
                @click="toggleApiCode(item.permissionCode)"
              >
                <el-tag size="small" :type="getActionTagType(item.action)" class="action-tag">
                  {{ item.action }}
                </el-tag>
                <code class="api-perm-code">{{ item.permissionCode }}</code>
                <span class="api-title">{{ item.title || '—' }}</span>
                <i class="fa fa-check-circle check-icon" v-if="extraPermCodes.includes(item.permissionCode)" />
              </div>
            </template>
            <div class="api-empty" v-else-if="!apiMapLoading">
              {{ apiMapOptions.length ? '无匹配结果' : '暂无 API 映射数据' }}
            </div>
          </div>
        </div>

      </el-form-item>

    </el-form>

    <template #footer>
      <div class="drawer-footer">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ mode === 'create' ? '创建权限组' : '保存修改' }}
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { TreeNodeData } from 'element-plus/es/components/tree/src/tree.type'
import {
  createGroup, updateGroup,
  getGroupOptions, getApiMapList,
  type GroupItem, type RuleTreeNode,
  type GroupSelectResult, type ApiMapViewItem,
} from '/@/api/backend/rbac'

// ── Props / Emits ──────────────────────────────────────────────
interface Props {
  modelValue: boolean
  mode: 'create' | 'edit'
  model: GroupItem | null
  ruleTree: RuleTreeNode[]
}
const props = withDefaults(defineProps<Props>(), {
  modelValue: false, mode: 'create', model: null, ruleTree: () => [],
})
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'submit'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

// ── 父组选项 ───────────────────────────────────────────────────
const parentGroupOptions = ref<{ label: string; value: string; children?: any[] }[]>([])
async function loadParentOptions() {
  try {
    const result = await getGroupOptions() as GroupSelectResult
    parentGroupOptions.value = result.options ?? []
  } catch {}
}

// ── 表单 ───────────────────────────────────────────────────────
interface FormData {
  groupCode: string; groupName: string
  parentGroupCode: string; status: 'Active' | 'Disabled'
}
const formRef    = ref()
const submitting = ref(false)
const formData   = reactive<FormData>({
  groupCode: '', groupName: '', parentGroupCode: '', status: 'Active',
})
const formRules = {
  groupName: [
    { required: true, message: '请输入组名称', trigger: 'blur' },
    { max: 64, message: '组名称最长 64 字符', trigger: 'blur' },
  ],
  groupCode: [
    { pattern: /^[a-zA-Z0-9_-]*$/, message: '只允许字母、数字、下划线、连字符', trigger: 'blur' },
    { max: 64, message: '组编码最长 64 字符', trigger: 'blur' },
  ],
}

// ── 规则树（仅新增） ───────────────────────────────────────────
const treeRef = ref(); const treeSearch = ref(''); const checkedCount = ref(0)

const filteredRuleTree = computed(() => {
  if (!treeSearch.value) return props.ruleTree
  return filterTree(props.ruleTree, treeSearch.value)
})
function filterTree(nodes: RuleTreeNode[], kw: string): RuleTreeNode[] {
  return nodes.reduce<RuleTreeNode[]>((acc, node) => {
    const children = filterTree(node.children ?? [], kw)
    if (node.title.includes(kw) || node.ruleCode.includes(kw) || children.length)
      acc.push({ ...node, children })
    return acc
  }, [])
}
function filterNode(value: string, data: TreeNodeData) {
  const node = data as RuleTreeNode
  return !value || node.title.includes(value) || node.ruleCode.includes(value)
}
function checkAll()  { treeRef.value?.setCheckedKeys(flatCodes(props.ruleTree)); updateCheckedCount() }
function checkNone() { treeRef.value?.setCheckedKeys([]); updateCheckedCount() }
function flatCodes(nodes: RuleTreeNode[]): string[] {
  return nodes.reduce<string[]>((acc, n) => {
    acc.push(n.ruleCode); if (n.children?.length) acc.push(...flatCodes(n.children)); return acc
  }, [])
}
function collectRulePermissionCodes(nodes: RuleTreeNode[], result = new Set<string>()) {
  nodes.forEach((node) => {
    if (node.permissionCode) result.add(node.permissionCode)
    if (node.children?.length) collectRulePermissionCodes(node.children, result)
  })
  return result
}
function getExtraPermissionCodesFromUnion(permissionCodes: string[] = []) {
  const rulePermissionCodes = collectRulePermissionCodes(props.ruleTree)
  return permissionCodes.filter(code => !rulePermissionCodes.has(code))
}
function updateCheckedCount() { checkedCount.value = treeRef.value?.getCheckedKeys().length ?? 0 }
function getCheckedRuleCodes(): string[] { return treeRef.value?.getCheckedKeys() ?? [] }
function getTypeShort(type: string): string {
  return ({ menu_dir: '目', menu: '菜', button: '钮' } as Record<string, string>)[type] ?? '?'
}

// ── API 映射 extraPermissionCodes ─────────────────────────────
const extraPermCodes  = ref<string[]>([])
const apiMapLoading   = ref(false)
const apiMapOptions   = ref<ApiMapViewItem[]>([])
const apiSearch       = ref('')
const apiActionFilter = ref('')
const API_ACTIONS = ['read', 'create', 'update', 'delete', 'execute', 'access']

const filteredApiOptions = computed(() => {
  let list = apiMapOptions.value
  if (apiActionFilter.value) list = list.filter(i => i.action === apiActionFilter.value)
  if (apiSearch.value) {
    const kw = apiSearch.value.toLowerCase()
    list = list.filter(i =>
      i.permissionCode.toLowerCase().includes(kw) ||
      (i.title ?? '').toLowerCase().includes(kw)
    )
  }
  return list
})

// 打开时直接调用，不等用户点击
async function loadApiMapOptions() {
  if (apiMapOptions.value.length) return  // 已有缓存，跳过
  apiMapLoading.value = true
  try {
    const result = await getApiMapList({ pageSize: 200 })
    apiMapOptions.value = result.list
  } catch {} finally {
    apiMapLoading.value = false
  }
}

function toggleApiCode(code: string) {
  const idx = extraPermCodes.value.indexOf(code)
  if (idx === -1) extraPermCodes.value.push(code)
  else extraPermCodes.value.splice(idx, 1)
}
function removeExtraCode(code: string) {
  extraPermCodes.value = extraPermCodes.value.filter(c => c !== code)
}
function getActionTagType(action: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  return ({ read:'info', create:'success', update:'primary', delete:'danger', execute:'warning', access:'info' } as any)[action] ?? 'info'
}

// ── 监听打开：立即调用 API ────────────────────────────────────
watch(
  () => [props.modelValue, props.mode, props.model, props.ruleTree],
  () => {
    if (!props.modelValue) return

    // 每次打开都并发发起这两个请求
    loadParentOptions()
    loadApiMapOptions()  // 立即加载，不等用户操作

    if (props.mode === 'edit' && props.model) {
      formData.groupCode       = props.model.groupCode
      formData.groupName       = props.model.groupName
      formData.parentGroupCode = ''
      formData.status          = props.model.status
      extraPermCodes.value = getExtraPermissionCodesFromUnion(props.model.permissionCodes ?? [])
      apiSearch.value = ''
      apiActionFilter.value = ''
    } else {
      formData.groupCode = ''; formData.groupName = ''
      formData.parentGroupCode = ''; formData.status = 'Active'
      treeSearch.value = ''; extraPermCodes.value = []
      apiSearch.value = ''; apiActionFilter.value = ''
      checkedCount.value = 0
      setTimeout(() => { treeRef.value?.setCheckedKeys([]); updateCheckedCount() }, 50)
    }
  },
  { immediate: true }
)

// ── 提交 ───────────────────────────────────────────────────────
async function handleSubmit() {
  try { await formRef.value.validate() } catch { return }
  submitting.value = true
  try {
    if (props.mode === 'create') {
      await createGroup({
        groupCode:       formData.groupCode.trim() || undefined,
        groupName:       formData.groupName.trim(),
        parentGroupCode: formData.parentGroupCode || undefined,
        status:          formData.status,
        ruleCodes:       getCheckedRuleCodes(),
        ...(extraPermCodes.value.length ? { extraPermissionCodes: extraPermCodes.value } : {}),
      })
      ElMessage.success('权限组创建成功')
    } else {
      await updateGroup(formData.groupCode, {
        groupName: formData.groupName.trim() || null,
        status:    formData.status,
        ...{ extraPermissionCodes: extraPermCodes.value },
      })
      ElMessage.success('权限组已更新')
    }
    emit('submit'); visible.value = false
  } catch {} finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.group-form { padding: 4px 0; }

.field-hint {
  margin-top: 5px; font-size: 12px; color: #86868b; line-height: 1.4;
}
.field-hint code {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px; background: #f5f5f7; padding: 1px 4px; border-radius: 3px;
}

/* 树区块 */
.tree-section { width: 100%; border: 1px solid #e5e5e5; border-radius: 8px; overflow: hidden; }
.tree-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 4px; padding: 8px 12px; background: #f5f5f7; border-bottom: 1px solid #e5e5e5;
}
.toolbar-left { display: flex; align-items: center; gap: 4px; }
.check-count { font-size: 12px; color: #86868b; }
.check-count strong { color: #0066cc; }
.info-tip {
  display: flex; align-items: flex-start; gap: 6px;
  padding: 7px 12px; background: #f0f6ff; border-bottom: 1px solid #e0ecff;
  font-size: 12px; color: #1d4e8a; line-height: 1.4;
}
.info-tip .fa { margin-top: 1px; }
/* 规则树固定高度，内部滚动 */
.rule-tree { height: 260px; overflow-y: auto; padding: 8px 4px; }

.tree-node { display: flex; align-items: center; gap: 6px; }
.node-badge {
  width: 18px; height: 18px; border-radius: 4px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700; flex-shrink: 0;
}
.node-badge--menu_dir { background: #e8f0fe; color: #1a73e8; }
.node-badge--menu     { background: #e6f4ea; color: #1e7e34; }
.node-badge--button   { background: #fff3e0; color: #e65100; }
.node-title {
  font-size: 13px; color: #1d1d1f; flex: 1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.node-code {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 10px; color: #86868b; background: #f5f5f7;
  padding: 1px 4px; border-radius: 3px; flex-shrink: 0;
}

/* 额外权限码区域 */
.extra-info {
  display: flex; align-items: flex-start; gap: 7px;
  padding: 7px 0 10px;
  font-size: 12px; color: #86868b; line-height: 1.5;
  width: 100%;
}

/* 已选 Tags */
.extra-tags {
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-bottom: 10px; width: 100%;
}
.extra-tag {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px; border-radius: 4px;
}

/* API 选择面板：固定高度，绝不撑开抽屉 */
.api-panel {
  width: 100%;
  border: 1px solid #e5e5e5;
  border-radius: 8px;
  overflow: hidden;
  /* 面板本身不滚动，只有内部 api-list 滚动 */
}

.api-panel-toolbar {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px;
  background: #f5f5f7;
  border-bottom: 1px solid #e5e5e5;
}

/* 关键：固定高度 220px，内部独立滚动，不影响抽屉外层 */
.api-list {
  height: 220px;
  overflow-y: auto;
  overscroll-behavior: contain; /* 防止滚动穿透到抽屉 */
}

.api-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 12px; cursor: pointer;
  border-bottom: 1px solid #f0f0f4;
  transition: background 0.1s;
  user-select: none;
}
.api-item:last-child  { border-bottom: none; }
.api-item:hover       { background: #f5f8ff; }
.api-item.is-selected { background: #f0f6ff; }

.action-tag {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 10px; font-weight: 700; border-radius: 3px; flex-shrink: 0;
}
.api-perm-code {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px; color: #0066cc; background: #f0f6ff;
  padding: 2px 6px; border-radius: 3px; border: 1px solid #cce0ff;
  flex-shrink: 0; max-width: 200px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.api-title {
  font-size: 12px; color: #86868b; flex: 1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.check-icon { color: #0066cc; font-size: 14px; flex-shrink: 0; }
.api-empty { height: 100%; display: flex; align-items: center; justify-content: center; font-size: 12px; color: #c0c0c8; }

/* 表单控件 */
:deep(.el-form-item__label) {
  font-size: 13px; font-weight: 600; color: #1d1d1f; letter-spacing: -0.12px; margin-bottom: 6px;
}
:deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 2px rgba(0,102,204,0.2) !important; }
:deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background-color: #0066cc; border-color: #0066cc; box-shadow: -1px 0 0 0 #0066cc;
}
:deep(.el-checkbox__input.is-checked .el-checkbox__inner),
:deep(.el-checkbox__input.is-indeterminate .el-checkbox__inner) {
  background-color: #0066cc; border-color: #0066cc;
}
:deep(.el-button--primary) { background-color: #0066cc; border-color: #0066cc; }
:deep(.el-button--primary:hover) { background-color: #0071e3; border-color: #0071e3; }
:deep(.el-tag--info)    { --el-tag-bg-color: #f0f6ff; --el-tag-border-color: #cce0ff; --el-tag-text-color: #0066cc; }
:deep(.el-tag--success) { --el-tag-bg-color: #e6f4ea; --el-tag-border-color: #b7dfbc; --el-tag-text-color: #1e7e34; }
:deep(.el-tag--danger)  { --el-tag-bg-color: #fef0f0; --el-tag-border-color: #fbc4c4; --el-tag-text-color: #c0392b; }

.drawer-footer {
  display: flex; justify-content: flex-end; gap: 12px;
  padding: 16px 20px; border-top: 1px solid #e5e7eb;
}
</style>
