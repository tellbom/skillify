<template>
  <el-drawer
    v-model="visible"
    :title="`规则授权 · ${target?.groupName ?? ''}`"
    size="600px"
    direction="rtl"
    destroy-on-close
    class="group-rules-drawer"
    :before-close="handleBeforeClose"
  >
    <div class="drawer-body" v-loading="loading">

      <!-- 组信息卡片 -->
      <div class="group-card" v-if="target">
        <div class="group-card__icon"><i class="fa fa-users" /></div>
        <div class="group-card__info">
          <div class="group-card__name">{{ target.groupName }}</div>
          <code class="group-card__code">{{ target.groupCode }}</code>
        </div>
        <el-tag :type="target.status === 'Active' ? 'success' : 'danger'" size="small">
          {{ target.status === 'Active' ? '启用' : '禁用' }}
        </el-tag>
      </div>

      <!-- ══ 区块一：规则树 ══════════════════════════════════════ -->
      <div class="section">
        <div class="section-header">
          <div class="section-title">
            <i class="fa fa-sitemap" />
            规则授权
          </div>
          <div class="section-actions">
            <el-button size="small" text @click="checkAll">全选</el-button>
            <el-divider direction="vertical" />
            <el-button size="small" text @click="checkNone">清空</el-button>
            <el-divider direction="vertical" />
            <span class="check-count">已选 <strong>{{ checkedCount }}</strong> 项</span>
          </div>
          <el-input
            v-model="treeSearch"
            size="small"
            placeholder="搜索规则"
            clearable
            style="width: 150px"
            :prefix-icon="Search"
          />
        </div>

        <div class="info-tip">
          <i class="fa fa-info-circle" />
          父子节点互不级联。提交时仅包含当前手动勾选的 <code>ruleCode</code> 列表，
          服务端推导 <code>permissionCode</code>。
        </div>

        <!-- 规则树：check-strictly 关闭父子级联勾选 -->
        <el-tree
          ref="treeRef"
          :data="filteredRuleTree"
          :props="{ label: 'title', children: 'children' }"
          node-key="ruleCode"
          show-checkbox
          check-strictly
          :default-expand-all="true"
          :filter-node-method="filterNode"
          class="rule-tree"
          @check="handleCheck"
        >
          <template #default="{ data }">
            <span class="tree-node">
              <span :class="`node-badge node-badge--${data.type}`">
                {{ getTypeShort(data.type) }}
              </span>
              <span class="node-title">{{ data.title }}</span>
              <code class="node-perm" v-if="data.permissionCode">
                {{ data.permissionCode }}
              </code>
            </span>
          </template>
        </el-tree>
      </div>

      <!-- ══ 区块二：额外权限码（extraPermissionCodes）══════════ -->
      <div class="section">
        <div class="section-header">
          <div class="section-title">
            <i class="fa fa-plug" />
            额外 API 端点权限
            <el-tag size="small" type="info" class="optional-tag">可选</el-tag>
          </div>
        </div>

        <div class="info-tip">
          <i class="fa fa-info-circle" />
          追加直接来自 API 映射表的权限码，不依赖规则树推导。
          最终授权 = 规则树推导值 ∪ 额外权限码。
        </div>

        <!-- 已选额外权限码 Tags -->
        <div class="extra-tags" v-if="extraPermCodes.length">
          <el-tag
            v-for="code in extraPermCodes"
            :key="code"
            closable
            size="small"
            class="extra-tag"
            @close="removeExtraCode(code)"
          >{{ code }}</el-tag>
        </div>
        <div class="extra-empty" v-else>
          暂无额外权限码
        </div>

        <!-- API 映射选择器 -->
        <div class="api-picker">
          <div class="api-picker-toolbar">
            <el-input
              v-model="apiSearch"
              size="small"
              placeholder="搜索权限码"
              clearable
              :prefix-icon="Search"
              style="flex: 1"
            />
            <el-select
              v-model="apiActionFilter"
              size="small"
              placeholder="Action"
              clearable
              style="width: 110px"
            >
              <el-option v-for="a in API_ACTIONS" :key="a" :label="a" :value="a" />
            </el-select>
          </div>

          <div class="api-list" v-loading="apiMapLoading">
            <div
              v-for="item in filteredApiOptions"
              :key="item.permissionCode"
              class="api-item"
              :class="{ 'is-selected': extraPermCodes.includes(item.permissionCode) }"
              @click="toggleApiCode(item.permissionCode)"
            >
              <el-tag
                size="small"
                :type="getActionTagType(item.action)"
                class="action-tag"
              >{{ item.action }}</el-tag>
              <code class="api-perm-code">{{ item.permissionCode }}</code>
              <span class="api-title">{{ item.title }}</span>
              <i
                class="fa fa-check-circle check-indicator"
                v-if="extraPermCodes.includes(item.permissionCode)"
              />
            </div>
            <div class="api-empty" v-if="!filteredApiOptions.length && !apiMapLoading">
              无匹配结果
            </div>
          </div>
        </div>
      </div>

    </div>

    <!-- 底部 -->
    <template #footer>
      <div class="drawer-footer">
        <span class="footer-hint">
          规则 <strong>{{ checkedCount }}</strong> 项
          <template v-if="extraPermCodes.length">
            · 额外权限码 <strong>{{ extraPermCodes.length }}</strong> 项
          </template>
        </span>
        <div class="footer-actions">
          <el-button @click="handleCancel">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">
            保存授权
          </el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  updateGroupRules,
  getApiMapList,
  type GroupItem,
  type RuleTreeNode,
  type ApiMapViewItem,
} from '/@/api/backend/rbac'

// ── Props / Emits ──────────────────────────────────────────────
interface Props {
  modelValue: boolean
  target: GroupItem | null
  ruleTree: RuleTreeNode[]
}
const props = withDefaults(defineProps<Props>(), {
  modelValue: false, target: null, ruleTree: () => [],
})
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'submit'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

// ── 状态 ───────────────────────────────────────────────────────
const loading    = ref(false)
const submitting = ref(false)
const treeRef    = ref()
const treeSearch = ref('')
const checkedCount = ref(0)
const isDirty    = ref(false)

// extraPermissionCodes
const extraPermCodes = ref<string[]>([])

// API 映射选择器
const apiMapLoading   = ref(false)
const apiMapOptions   = ref<ApiMapViewItem[]>([])
const apiSearch       = ref('')
const apiActionFilter = ref('')

const API_ACTIONS = ['read', 'create', 'update', 'delete', 'execute', 'access']

// ── 过滤树 ─────────────────────────────────────────────────────
const filteredRuleTree = computed(() => {
  if (!treeSearch.value) return props.ruleTree
  return filterTree(props.ruleTree, treeSearch.value)
})

function filterTree(nodes: RuleTreeNode[], kw: string): RuleTreeNode[] {
  return nodes.reduce<RuleTreeNode[]>((acc, node) => {
    const children = filterTree(node.children ?? [], kw)
    if (node.title.includes(kw) || node.ruleCode.includes(kw) || children.length) {
      acc.push({ ...node, children })
    }
    return acc
  }, [])
}

function filterNode(value: string, data: RuleTreeNode) {
  if (!value) return true
  return data.title.includes(value) || data.ruleCode.includes(value)
}

// ── API 映射选项过滤 ───────────────────────────────────────────
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

// ── 打开时初始化 ───────────────────────────────────────────────
watch(
  () => [props.modelValue, props.target, props.ruleTree],
  () => {
    if (!props.modelValue || !props.target) return
    treeSearch.value = ''
    apiSearch.value  = ''
    apiActionFilter.value = ''
    isDirty.value    = false
    checkedCount.value = 0
    loadApiMapOptions()

    setTimeout(() => {
      if (!treeRef.value) return
      const splitResult = splitPermissionCodes(props.target!.permissionCodes ?? [])
      treeRef.value.setCheckedKeys(splitResult.ruleCodes)
      extraPermCodes.value = splitResult.extraPermissionCodes
      updateCheckedCount()
    }, 80)
  },
  { immediate: true }
)

function splitPermissionCodes(permissionCodes: string[]) {
  const targetSet = new Set(permissionCodes)
  const matchedPermissionCodes = new Set<string>()
  const ruleCodes: string[] = []
  collectRuleCodesByPermCodes(props.ruleTree, targetSet, ruleCodes, matchedPermissionCodes)
  return {
    ruleCodes,
    extraPermissionCodes: permissionCodes.filter(code => !matchedPermissionCodes.has(code)),
  }
}

function collectRuleCodesByPermCodes(
  nodes: RuleTreeNode[],
  targetSet: Set<string>,
  ruleCodes: string[],
  matchedPermissionCodes: Set<string>
) {
  for (const node of nodes) {
    if (node.permissionCode && targetSet.has(node.permissionCode)) {
      ruleCodes.push(node.ruleCode)
      matchedPermissionCodes.add(node.permissionCode)
    }
    if (node.children?.length) {
      collectRuleCodesByPermCodes(node.children, targetSet, ruleCodes, matchedPermissionCodes)
    }
  }
}

// ── 规则树操作 ─────────────────────────────────────────────────
function checkAll() {
  treeRef.value?.setCheckedKeys(flatCodes(props.ruleTree))
  updateCheckedCount(); isDirty.value = true
}
function checkNone() {
  treeRef.value?.setCheckedKeys([])
  updateCheckedCount(); isDirty.value = true
}
function flatCodes(nodes: RuleTreeNode[]): string[] {
  return nodes.reduce<string[]>((acc, n) => {
    acc.push(n.ruleCode)
    if (n.children?.length) acc.push(...flatCodes(n.children))
    return acc
  }, [])
}
function handleCheck() {
  updateCheckedCount(); isDirty.value = true
}
function updateCheckedCount() {
  if (!treeRef.value) return
  // check-strictly 模式下，getCheckedKeys 仅返回当前手动勾选的节点。
  checkedCount.value = treeRef.value.getCheckedKeys().length
}
function getTypeShort(type: string): string {
  return ({ menu_dir: '目', menu: '菜', button: '钮' } as Record<string, string>)[type] ?? '?'
}

// ── API 映射选择器 ─────────────────────────────────────────────
async function loadApiMapOptions() {
  if (apiMapOptions.value.length) return  // 已加载，不重复请求
  apiMapLoading.value = true
  try {
    const result = await getApiMapList({ pageSize: 200 })
    apiMapOptions.value = result.list
  } catch {
    // 静默失败
  } finally {
    apiMapLoading.value = false
  }
}

function toggleApiCode(code: string) {
  const idx = extraPermCodes.value.indexOf(code)
  if (idx === -1) extraPermCodes.value.push(code)
  else extraPermCodes.value.splice(idx, 1)
  isDirty.value = true
}

function removeExtraCode(code: string) {
  extraPermCodes.value = extraPermCodes.value.filter(c => c !== code)
  isDirty.value = true
}

function getActionTagType(action: string): '' | 'success' | 'warning' | 'info' | 'danger' {
  return ({
    read: 'info', create: 'success', update: '',
    delete: 'danger', execute: 'warning', access: 'info',
  } as Record<string, any>)[action] ?? 'info'
}

// ── 提交 ───────────────────────────────────────────────────────
async function handleSubmit() {
  if (!props.target) return

  // check-strictly 模式下，前端勾选哪些 ruleCode 就提交哪些 ruleCode。
  const ruleCodes: string[] = treeRef.value?.getCheckedKeys() ?? []

  submitting.value = true
  try {
    await updateGroupRules(props.target.groupCode, {
      ruleCodes,
      ...{ extraPermissionCodes: extraPermCodes.value },
    })
    ElMessage.success('规则授权已更新')
    isDirty.value = false
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
  if (isDirty.value) {
    try {
      await ElMessageBox.confirm(
        '有未保存的规则变更，确定关闭？', '提示',
        { confirmButtonText: '关闭', cancelButtonText: '继续编辑', type: 'warning' }
      )
      done()
    } catch { /* 继续编辑 */ }
  } else {
    done()
  }
}
</script>

<style scoped>
.group-rules-drawer {
  font-family: 'SF Pro Text', system-ui, -apple-system, sans-serif;
}

.drawer-body {
  padding: 0 20px 20px;
  box-sizing: border-box;
  height: 100%;
  overflow-y: auto;
}

/* 组信息卡片 */
.group-card {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 16px; background: #f5f5f7; border-radius: 10px; margin: 16px 0;
}
.group-card__icon {
  width: 38px; height: 38px; border-radius: 8px;
  background: linear-gradient(135deg, #0066cc 0%, #2997ff 100%);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 16px; flex-shrink: 0;
}
.group-card__info { flex: 1; min-width: 0; }
.group-card__name { font-size: 15px; font-weight: 600; color: #1d1d1f; }
.group-card__code {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px; color: #86868b; background: #ebebeb;
  padding: 1px 5px; border-radius: 3px; display: inline-block; margin-top: 2px;
}

/* 区块 */
.section {
  border: 1px solid #e5e5e5;
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 16px;
}

.section-header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px;
  background: #f5f5f7;
  border-bottom: 1px solid #e5e5e5;
  flex-wrap: wrap;
}

.section-title {
  font-size: 13px; font-weight: 600; color: #1d1d1f;
  display: flex; align-items: center; gap: 6px;
  flex: 1;
}
.section-title .fa { color: #0066cc; }

.section-actions {
  display: flex; align-items: center; gap: 4px;
}

.check-count { font-size: 12px; color: #86868b; }
.check-count strong { color: #0066cc; }

.optional-tag { margin-left: 4px; }

/* 说明提示 */
.info-tip {
  display: flex; align-items: flex-start; gap: 8px;
  padding: 8px 14px;
  background: #f0f6ff;
  border-bottom: 1px solid #e0ecff;
  font-size: 12px; color: #1d4e8a; line-height: 1.5;
}
.info-tip .fa { color: #0066cc; margin-top: 1px; flex-shrink: 0; }
.info-tip code {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px; background: #ddeeff; padding: 1px 4px; border-radius: 3px;
}

/* 规则树 */
.rule-tree {
  height: 320px;
  overflow-y: auto;
  padding: 8px 6px;
  overscroll-behavior: contain;
}

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
.node-perm {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 10px; color: #0066cc; background: #f0f6ff;
  padding: 1px 4px; border-radius: 3px; border: 1px solid #cce0ff;
  flex-shrink: 0; max-width: 200px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* 额外权限码 Tags */
.extra-tags {
  display: flex; flex-wrap: wrap; gap: 6px;
  padding: 10px 14px;
}
.extra-tag {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px; border-radius: 4px;
}
.extra-empty {
  padding: 10px 14px;
  font-size: 12px; color: #c0c0c8;
}

/* API 映射选择器 */
.api-picker {
  border-top: 1px solid #e5e5e5;
}
.api-picker-toolbar {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px;
  background: #fafafc;
  border-bottom: 1px solid #e5e5e5;
}

.api-list {
  height: 220px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.api-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px;
  cursor: pointer;
  border-bottom: 1px solid #f0f0f4;
  transition: background 0.12s;
}
.api-item:hover   { background: #f5f8ff; }
.api-item.is-selected { background: #f0f6ff; }
.api-item:last-child  { border-bottom: none; }

.action-tag {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 10px; font-weight: 700; border-radius: 3px;
  flex-shrink: 0;
}
.api-perm-code {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px; color: #0066cc; background: #f0f6ff;
  padding: 2px 6px; border-radius: 3px; border: 1px solid #cce0ff;
  flex-shrink: 0;
}
.api-title {
  font-size: 12px; color: #86868b;
  flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.check-indicator {
  color: #0066cc; font-size: 14px; flex-shrink: 0;
}
.api-empty { padding: 16px; text-align: center; font-size: 12px; color: #c0c0c8; }

/* 底部 */
.drawer-footer {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-top: 1px solid #e5e7eb;
}
.footer-hint { font-size: 13px; color: #86868b; }
.footer-hint strong { color: #0066cc; }
.footer-actions { display: flex; gap: 12px; }

/* 覆盖 */
:deep(.el-drawer__body) {
  padding: 0;
  overflow: hidden;
}
:deep(.el-checkbox__input.is-checked .el-checkbox__inner),
:deep(.el-checkbox__input.is-indeterminate .el-checkbox__inner) {
  background-color: #0066cc; border-color: #0066cc;
}
:deep(.el-button--primary) { background-color: #0066cc; border-color: #0066cc; }
:deep(.el-button--primary:hover) { background-color: #0071e3; border-color: #0071e3; }
:deep(.el-tag--success) { --el-tag-bg-color: #e6f4ea; --el-tag-border-color: #b7dfbc; --el-tag-text-color: #1e7e34; }
:deep(.el-tag--danger)  { --el-tag-bg-color: #fef0f0; --el-tag-border-color: #fbc4c4; --el-tag-text-color: #c0392b; }
:deep(.el-tag--info)    { --el-tag-bg-color: #f0f6ff; --el-tag-border-color: #cce0ff; --el-tag-text-color: #0066cc; }
</style>
