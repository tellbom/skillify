<template>
    <div class="rbac-rule-page">
        <Commonsearch :fields="searchFields" @search="handleSearch" @reset="handleReset" />

        <div class="rule-table-wrapper">
            <!-- 工具栏 -->
            <div class="table-toolbar">
                <div class="toolbar-left">
                    <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openCreate(null)"> 新增规则 </el-button>
                    <el-button :icon="Refresh" @click="loadTree" title="刷新" />
                    <el-button :icon="isAllExpanded ? FolderOpened : Folder" @click="toggleExpandAll">
                        {{ isAllExpanded ? '全部收起' : '全部展开' }}
                    </el-button>
                </div>
                <span class="table-summary">共 {{ flatCount }} 项</span>
            </div>

            <el-table
                v-loading="loading"
                :data="treeData"
                row-key="ruleCode"
                :tree-props="{ children: 'children', hasChildren: 'hasChildren' }"
                :indent="32"
                style="width: 100%"
                :key="tableRenderKey"
                :default-expand-all="isAllExpanded"
                :header-cell-style="headerCellStyle"
            >
                <el-table-column label="标题" min-width="260">
                    <template #default="{ row }">
                        <div class="title-cell">
                            <span class="node-title">{{ row.title }}</span>
                            <code class="node-code">{{ row.ruleCode }}</code>
                        </div>
                    </template>
                </el-table-column>

                <el-table-column label="图标" width="72" align="center">
                    <template #default="{ row }">
                        <i v-if="row.icon" :class="row.icon" class="rule-icon" />
                        <span v-else class="nil">—</span>
                    </template>
                </el-table-column>

                <el-table-column label="名称" min-width="180" show-overflow-tooltip>
                    <template #default="{ row }">
                        <code v-if="row.name" class="code-text">{{ row.name }}</code>
                        <span v-else class="nil">—</span>
                    </template>
                </el-table-column>

                <el-table-column label="类型" width="90" align="center">
                    <template #default="{ row }">
                        <el-tag size="small" effect="plain">{{ getTypeLabel(row.type) }}</el-tag>
                    </template>
                </el-table-column>

                <el-table-column label="缓存" width="80" align="center">
                    <template #default="{ row }">
                        <el-switch :model-value="row.keepalive === true" size="small" disabled />
                    </template>
                </el-table-column>

                <el-table-column label="权限码" min-width="200" show-overflow-tooltip>
                    <template #default="{ row }">
                        <code v-if="row.permissionCode" class="code-text">{{ row.permissionCode }}</code>
                        <span v-else class="nil">—</span>
                    </template>
                </el-table-column>

                <el-table-column label="路由路径" min-width="150" show-overflow-tooltip>
                    <template #default="{ row }">
                        <span v-if="row.type === 'button'" class="nil">—</span>
                        <code v-else-if="row.path" class="code-text">{{ row.path }}</code>
                        <code v-else-if="row.url" class="code-text">{{ row.url }}</code>
                        <span v-else class="nil">—</span>
                    </template>
                </el-table-column>

                <el-table-column label="排序" width="96" align="center">
                    <template #default="{ row }">
                        <el-input-number
                            v-if="canEdit"
                            :model-value="row.weigh ?? 0"
                            :min="0"
                            :max="9999"
                            :step="10"
                            size="small"
                            controls-position="right"
                            class="weigh-input"
                            @change="(val) => handleWeighChange(row, val)"
                        />
                        <span v-else class="nil">{{ row.weigh ?? 0 }}</span>
                    </template>
                </el-table-column>

                <el-table-column label="状态" width="80" align="center">
                    <template #default="{ row }">
                        <el-switch
                            v-if="canEdit"
                            :model-value="row.status === 'Active'"
                            size="small"
                            :active-color="'#0066cc'"
                            @change="(val) => handleStatusToggle(row, val)"
                        />
                        <el-tag v-else :type="row.status === 'Active' ? 'success' : 'danger'" size="small">
                            {{ row.status === 'Active' ? '启用' : '禁用' }}
                        </el-tag>
                    </template>
                </el-table-column>

                <el-table-column label="操作" width="185" align="center" fixed="right">
                    <template #default="{ row }">
                        <el-button v-if="canCreate && row.type !== 'button'" type="primary" link size="small" :icon="Plus" @click="openCreate(row)"
                            >子项</el-button
                        >
                        <el-button v-if="canEdit" type="primary" link size="small" :icon="Edit" @click="openEdit(row)">编辑</el-button>
                        <el-button v-if="canDelete" type="danger" link size="small" :icon="Delete" @click="handleDelete(row)">删除</el-button>
                    </template>
                </el-table-column>
            </el-table>
        </div>

        <RuleFormDrawer
            v-model="formDrawerVisible"
            :mode="formMode"
            :model="currentRow"
            :parent-row="parentRow"
            :rule-tree="treeData"
            @submit="handleFormSubmit"
        />
    </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Plus, Delete, Edit, Refresh, Folder, FolderOpened } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import Commonsearch from '/@/components/claudetable/Commonsearch.vue'
import RuleFormDrawer from './components/RuleFormDrawer.vue'
import { getRuleList, updateRuleStatus, updateRuleWeigh, deleteRule, type RuleItem, type RuleTreeNode } from '/@/api/backend/rbac'
import { useAuthStore } from '/@/stores/auth.js'

type RuleTableNode = RuleTreeNode & {
    parentRuleCode?: string | null
    status?: 'Active' | 'Disabled' | string
    weigh?: number
    children?: RuleTableNode[]
}

defineOptions({ name: 'auth/rule' })

const auth = useAuthStore()
const canCreate = computed(() => auth.rbacInfo?.super || false)
const canEdit = computed(() => auth.rbacInfo?.super || false)
const canDelete = computed(() => auth.rbacInfo?.super || false)

const headerCellStyle = {
    background: '#fafafc',
    color: '#1d1d1f',
    fontSize: '12px',
    fontWeight: '600',
    letterSpacing: '-0.12px',
    borderBottom: '1px solid #e0e0e0',
}

const searchFields = [
    { prop: 'keyword', label: '关键字', type: 'input', placeholder: '标题 / ruleCode', width: '200px' },
    {
        prop: 'type',
        label: '类型',
        type: 'select',
        width: '140px',
        options: [
            { label: '目录', value: 'menu_dir' },
            { label: '菜单', value: 'menu' },
            { label: '按钮', value: 'button' },
        ],
    },
    {
        prop: 'status',
        label: '状态',
        type: 'select',
        width: '120px',
        options: [
            { label: '启用', value: 'Active' },
            { label: '禁用', value: 'Disabled' },
        ],
    },
]

const treeData = ref<RuleTableNode[]>([])
const loading = ref(false)
const isAllExpanded = ref(false)
const tableRenderKey = ref(0)
const filterParams = ref<Record<string, any>>({})

const flatCount = computed(() => countNodes(treeData.value))
function countNodes(nodes: RuleTableNode[]): number {
    return nodes.reduce((sum, n) => sum + 1 + countNodes(n.children ?? []), 0)
}

async function loadTree() {
    loading.value = true
    try {
        const raw = await loadAllRules()
        treeData.value = applyFilter(buildRuleTree(raw), filterParams.value)
    } catch {
    } finally {
        loading.value = false
    }
}

async function loadAllRules(): Promise<RuleItem[]> {
    const pageSize = 100
    let page = 1
    let total = 0
    const list: RuleItem[] = []

    do {
        const result = await getRuleList({ page, pageSize })
        list.push(...result.list)
        total = result.total
        page += 1
    } while (list.length < total)

    return list
}

function buildRuleTree(items: RuleItem[]): RuleTableNode[] {
    const nodeMap = new Map<string, RuleTableNode>()
    const roots: RuleTableNode[] = []

    for (const item of items) {
        nodeMap.set(item.ruleCode, toRuleTableNode(item))
    }

    for (const node of nodeMap.values()) {
        const parentCode = node.parentRuleCode || inferParentRuleCode(node.ruleCode, nodeMap)
        node.parentRuleCode = parentCode
        node.pid = parentCode
        const parent = parentCode ? nodeMap.get(parentCode) : null
        if (parent) {
            parent.children = parent.children ?? []
            parent.children.push(node)
        } else {
            roots.push(node)
        }
    }

    sortRuleNodes(roots)
    return roots
}

function toRuleTableNode(item: RuleItem): RuleTableNode {
    const parentRuleCode = resolveParentRuleCode(item)
    return {
        id: item.ruleCode,
        pid: parentRuleCode,
        title: item.title,
        name: item.name ?? item.ruleCode,
        path: item.path ?? '',
        icon: item.icon ?? '',
        type: normalizeRuleType(item.type),
        menu_type: item.menu_type ?? '',
        url: item.url ?? '',
        component: item.component ?? '',
        extend: item.extend ?? '',
        remark: item.remark ?? '',
        keepalive: item.keepalive ?? false,
        permissionCode: item.permissionCode,
        ruleCode: item.ruleCode,
        parentRuleCode,
        status: item.status,
        weigh: item.weigh ?? 0,
        children: [],
    }
}

function resolveParentRuleCode(item: RuleItem): string {
    const code = item.parentRuleCode ?? item.parent_rule_code ?? item.parent_ruleCode ?? item.pid ?? ''
    return normalizeParentCode(code)
}

function normalizeParentCode(code: unknown): string {
    const value = String(code ?? '').trim()
    return value && value !== '0' ? value : ''
}

function inferParentRuleCode(ruleCode: string, nodeMap: Map<string, RuleTableNode>): string {
    let parentCode = ''
    for (const code of nodeMap.keys()) {
        if (code === ruleCode) continue
        if ((ruleCode.startsWith(`${code}/`) || ruleCode.startsWith(`${code}.`)) && code.length > parentCode.length) {
            parentCode = code
        }
    }
    return parentCode
}

function normalizeRuleType(type: RuleItem['type']): 'menu_dir' | 'menu' | 'button' {
    const map: Record<string, 'menu_dir' | 'menu' | 'button'> = {
        MenuDir: 'menu_dir',
        Menu: 'menu',
        Button: 'button',
        menu_dir: 'menu_dir',
        menu: 'menu',
        button: 'button',
    }
    return map[type] ?? 'menu'
}

function sortRuleNodes(nodes: RuleTableNode[]) {
    nodes.sort((a, b) => (a.weigh ?? 0) - (b.weigh ?? 0))
    for (const node of nodes) {
        if (node.children?.length) sortRuleNodes(node.children)
        else delete node.children
    }
}

function applyFilter(nodes: RuleTableNode[], params: Record<string, any>): RuleTableNode[] {
    if (!params.keyword && !params.type && !params.status) return nodes
    return nodes.reduce<RuleTableNode[]>((acc, node) => {
        const kids = applyFilter(node.children ?? [], params)
        const hit =
            (!params.keyword || node.title.includes(params.keyword) || node.ruleCode.includes(params.keyword)) &&
            (!params.type || node.type === params.type) &&
            (!params.status || node.status === params.status)
        if (hit || kids.length) acc.push({ ...node, children: kids.length ? kids : node.children ?? [] })
        return acc
    }, [])
}

function handleSearch(params: Record<string, any>) {
    filterParams.value = params
    loadTree()
}
function handleReset() {
    filterParams.value = {}
    loadTree()
}

function toggleExpandAll() {
    isAllExpanded.value = !isAllExpanded.value
    tableRenderKey.value += 1
}

function getTypeLabel(type: string): string {
    return (
        (
            {
                menu_dir: '目录',
                menu: '菜单',
                button: '按钮',
            } as Record<string, string>
        )[type] ?? type
    )
}

const formDrawerVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const currentRow = ref<RuleTreeNode | null>(null)
const parentRow = ref<RuleTreeNode | null>(null)

function openCreate(parent: RuleTreeNode | null) {
    formMode.value = 'create'
    currentRow.value = null
    parentRow.value = parent
    formDrawerVisible.value = true
}
function openEdit(row: RuleTreeNode) {
    formMode.value = 'edit'
    currentRow.value = { ...row }
    parentRow.value = null
    formDrawerVisible.value = true
}
function handleFormSubmit() {
    formDrawerVisible.value = false
    loadTree()
}

async function handleStatusToggle(row: RuleTableNode, active: string | number | boolean) {
    const status = active === true ? 'Active' : 'Disabled'
    try {
        await updateRuleStatus(row.ruleCode, { status })
        row.status = status
        ElMessage.success(`已${active ? '启用' : '禁用'}「${row.title}」`)
    } catch {}
}
async function handleWeighChange(row: RuleTableNode, val: number | undefined) {
    try {
        await updateRuleWeigh(row.ruleCode, { weigh: val ?? 0 })
        row.weigh = val ?? 0
    } catch {}
}
async function handleDelete(row: RuleTreeNode) {
    const hasChildren = (row.children ?? []).length > 0
    try {
        await ElMessageBox.confirm(
            hasChildren ? `「${row.title}」下还有子规则，请先删除所有子规则。\n确定继续？` : `确定删除规则「${row.title}」（${row.ruleCode}）？`,
            '删除确认',
            { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
        )
        await deleteRule(row.ruleCode)
        ElMessage.success('规则已删除')
        loadTree()
    } catch (e: any) {
        if (e === 'cancel' || e?.message === 'cancel') return
    }
}

onMounted(() => loadTree())
</script>

<style scoped>
.rbac-rule-page {
    font-family:
        'SF Pro Text',
        system-ui,
        -apple-system,
        sans-serif;
}

.rule-table-wrapper {
    background: #fff;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #e0e0e0;
}

/* 工具栏 */
.table-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background: #fafafc;
    border-bottom: 1px solid #e0e0e0;
}
.toolbar-left {
    display: flex;
    align-items: center;
    gap: 8px;
}
.table-summary {
    color: #7a7a7a;
    font-size: 12px;
}

/* 标题列 */
.title-cell {
    display: inline-flex;
    flex-direction: column;
    justify-content: center;
    gap: 2px;
    min-width: 0;
    vertical-align: middle;
}
.node-title {
    color: #1d1d1f;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: -0.224px;
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.node-code,
.code-text {
    color: #333333;
    font-family: 'SF Mono', Menlo, Consolas, monospace;
    font-size: 12px;
    line-height: 1.4;
}
.node-code {
    color: #7a7a7a;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.nil {
    color: #b8b8be;
    font-size: 13px;
}
.weigh-input {
    width: 78px;
}

.rule-icon {
    color: #333333;
    font-size: 18px;
}

:deep(.el-button--primary) {
    --el-button-bg-color: #0066cc;
    --el-button-border-color: #0066cc;
    --el-button-hover-bg-color: #0071e3;
    --el-button-hover-border-color: #0071e3;
}
:deep(.el-button--primary.is-link) {
    --el-button-text-color: #0066cc;
    --el-button-hover-text-color: #0071e3;
}
:deep(.el-switch.is-checked .el-switch__core) {
    background-color: #0066cc;
    border-color: #0066cc;
}
:deep(.el-tag--success) {
    --el-tag-bg-color: #e6f4ea;
    --el-tag-border-color: #b7dfbc;
    --el-tag-text-color: #1e7e34;
}
:deep(.el-tag--danger) {
    --el-tag-bg-color: #fef0f0;
    --el-tag-border-color: #fbc4c4;
    --el-tag-text-color: #c0392b;
}
:deep(.el-table__inner-wrapper::before) {
    display: none;
}

@media (max-width: 640px) {
    .table-toolbar {
        align-items: flex-start;
        flex-direction: column;
        gap: 8px;
    }
}
</style>
