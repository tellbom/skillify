<template>
    <div class="rbac-group-page">
        <!-- 搜索区 -->
        <Commonsearch :fields="searchFields" @search="handleSearch" @reset="handleReset" />

        <div class="group-table-wrapper">
            <div class="table-toolbar">
                <div class="toolbar-left">
                    <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openCreate"> 新增权限组 </el-button>
                    <el-button :icon="Refresh" @click="loadData" title="刷新" />
                    <el-button :icon="isAllExpanded ? FolderOpened : Folder" @click="toggleExpandAll">
                        {{ isAllExpanded ? '全部收起' : '全部展开' }}
                    </el-button>
                </div>
                <span class="table-summary">共 {{ flatCount }} 项</span>
            </div>

            <el-table
                v-loading="loading"
                :data="treeData"
                row-key="groupCode"
                :tree-props="{ children: 'children', hasChildren: 'hasChildren' }"
                :indent="32"
                style="width: 100%"
                :key="tableRenderKey"
                :default-expand-all="isAllExpanded"
                :header-cell-style="headerCellStyle"
            >
                <el-table-column label="组编码" min-width="220">
                    <template #default="{ row }">
                        <div class="group-cell">
                            <span class="group-name">{{ row.groupName }}</span>
                            <code class="group-code">{{ row.groupCode }}</code>
                        </div>
                    </template>
                </el-table-column>

                <el-table-column label="Project" min-width="120" show-overflow-tooltip>
                    <template #default="{ row }">
                        <code v-if="row.project" class="code-text">{{ row.project }}</code>
                        <span v-else class="text-muted">—</span>
                    </template>
                </el-table-column>

                <el-table-column label="状态" width="90" align="center">
                    <template #default="{ row }">
                        <el-switch
                            v-if="canEdit"
                            :model-value="row.status === 'Active'"
                            size="small"
                            :active-color="'#0066cc'"
                            @change="(val: boolean) => handleStatusToggle(row, val)"
                        />
                        <el-tag v-else :type="row.status === 'Active' ? 'success' : 'danger'" size="small">
                            {{ row.status === 'Active' ? '启用' : '禁用' }}
                        </el-tag>
                    </template>
                </el-table-column>

                <el-table-column label="已授权权限" min-width="260">
                    <template #default="{ row }">
                        <div class="perm-tags">
                            <el-tag v-for="code in (row.permissionCodes || []).slice(0, 3)" :key="code" size="small" class="perm-tag">{{
                                code
                            }}</el-tag>
                            <el-tag v-if="(row.permissionCodes || []).length > 3" size="small" type="info"
                                >+{{ row.permissionCodes.length - 3 }}</el-tag
                            >
                            <el-tooltip v-if="(row.permissionCodes || []).length > 3" placement="top" :content="row.permissionCodes.join('\n')">
                                <el-icon class="perm-more-icon"><InfoFilled /></el-icon>
                            </el-tooltip>
                            <span v-if="!row.permissionCodes?.length" class="text-muted">—</span>
                        </div>
                    </template>
                </el-table-column>

                <el-table-column label="操作" width="220" align="center" fixed="right">
                    <template #default="{ row }">
                        <el-button v-if="canEdit" type="primary" link size="small" :icon="Edit" @click="openEdit(row)"> 编辑 </el-button>
                        <el-button v-if="canEdit" type="primary" link size="small" :icon="Key" @click="openRules(row)"> 授权规则 </el-button>
                        <el-button v-if="canDelete" type="danger" link size="small" :icon="Delete" @click="handleDelete(row)"> 删除 </el-button>
                    </template>
                </el-table-column>
            </el-table>
        </div>

        <!-- 新增/编辑抽屉 -->
        <GroupFormDrawer v-model="formDrawerVisible" :mode="formMode" :model="currentRow" :rule-tree="ruleTree" @submit="handleFormSubmit" />

        <!-- 规则授权抽屉 -->
        <GroupRulesDrawer v-model="rulesDrawerVisible" :target="currentRow" :rule-tree="ruleTree" @submit="handleRulesSubmit" />
    </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Plus, Delete, Edit, Refresh, Key, InfoFilled, Folder, FolderOpened } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import Commonsearch from '/@/components/claudetable/Commonsearch.vue'
import GroupFormDrawer from './components/GroupFormDrawer.vue'
import GroupRulesDrawer from './components/GroupRulesDrawer.vue'
import { getGroupList, deleteGroup, updateGroupStatus, getRuleTree, type GroupItem, type RuleTreeNode } from '/@/api/backend/rbac'
import { useAuthStore } from '/@/stores/auth.js'

defineOptions({ name: 'auth/group' })

type GroupTableNode = GroupItem & {
    parentGroupCode?: string | null
    children?: GroupTableNode[]
}

// ── 权限 ───────────────────────────────────────────────────────
const auth = useAuthStore()
const canCreate = computed(() => auth.rbacInfo?.super === true)
const canEdit = computed(() => auth.rbacInfo?.super === true)
const canDelete = computed(() => auth.rbacInfo?.super === true)

// ── 搜索字段 ───────────────────────────────────────────────────
const searchFields = [
    { prop: 'keyword', label: '关键字', type: 'input', placeholder: '组名 / groupCode', width: '220px' },
    { prop: 'permissionCode', label: '权限码', type: 'input', placeholder: '包含此权限码', width: '200px' },
    {
        prop: 'status',
        label: '状态',
        type: 'select',
        width: '140px',
        options: [
            { label: '启用', value: 'Active' },
            { label: '禁用', value: 'Disabled' },
        ],
    },
]

const headerCellStyle = {
    background: '#fafafc',
    color: '#1d1d1f',
    fontSize: '12px',
    fontWeight: '600',
    letterSpacing: '-0.12px',
    borderBottom: '1px solid #e0e0e0',
}

// ── 数据状态 ───────────────────────────────────────────────────
const treeData = ref<GroupTableNode[]>([])
const ruleTree = ref<RuleTreeNode[]>([])
const loading = ref(false)
const isAllExpanded = ref(false)
const tableRenderKey = ref(0)

const query = ref({
    page: 1,
    pageSize: 20,
    keyword: '',
    permissionCode: '',
    status: '',
})

const flatCount = computed(() => countNodes(treeData.value))
function countNodes(nodes: GroupTableNode[]): number {
    return nodes.reduce((sum, node) => sum + 1 + countNodes(node.children ?? []), 0)
}

// ── 抽屉状态 ───────────────────────────────────────────────────
const formDrawerVisible = ref(false)
const rulesDrawerVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const currentRow = ref<GroupItem | null>(null)

// ── 加载数据 ───────────────────────────────────────────────────
async function loadData() {
    loading.value = true
    try {
        const raw = await loadAllGroups()
        treeData.value = applyFilter(buildGroupTree(raw), query.value)
    } catch {
        // 统一处理
    } finally {
        loading.value = false
    }
}

async function loadAllGroups(): Promise<GroupItem[]> {
    const pageSize = 100
    let page = 1
    let total = 0
    const list: GroupItem[] = []

    do {
        const result = await getGroupList({ page, pageSize })
        list.push(...result.list)
        total = result.total
        page += 1
    } while (list.length < total)

    return list
}

function buildGroupTree(items: GroupItem[]): GroupTableNode[] {
    const nodeMap = new Map<string, GroupTableNode>()
    const roots: GroupTableNode[] = []

    for (const item of items) {
        const node = toGroupTableNode(item)
        nodeMap.set(node.groupCode, node)
    }

    for (const node of nodeMap.values()) {
        const parentCode = node.parentGroupCode ?? ''
        const parent = parentCode ? nodeMap.get(parentCode) : null
        if (parent) {
            parent.children = parent.children ?? []
            parent.children.push(node)
        } else {
            roots.push(node)
        }
    }

    cleanupEmptyChildren(roots)
    return roots
}

function toGroupTableNode(item: GroupItem): GroupTableNode {
    const groupCode = item.groupCode ?? item.group_code ?? ''
    return {
        ...item,
        groupCode,
        groupName: item.groupName ?? item.group_name ?? groupCode,
        parentGroupCode: item.parentGroupCode ?? item.parent_group_code ?? '',
        permissionCodes: item.permissionCodes ?? item.permission_codes ?? [],
        children: [],
    }
}

function cleanupEmptyChildren(nodes: GroupTableNode[]) {
    for (const node of nodes) {
        if (node.children?.length) cleanupEmptyChildren(node.children)
        else delete node.children
    }
}

function applyFilter(nodes: GroupTableNode[], params: Record<string, any>): GroupTableNode[] {
    if (!params.keyword && !params.permissionCode && !params.status) return nodes
    return nodes.reduce<GroupTableNode[]>((acc, node) => {
        const children = applyFilter(node.children ?? [], params)
        const hit =
            (!params.keyword || node.groupName.includes(params.keyword) || node.groupCode.includes(params.keyword)) &&
            (!params.permissionCode || (node.permissionCodes ?? []).some((code) => code.includes(params.permissionCode))) &&
            (!params.status || node.status === params.status)
        if (hit || children.length) acc.push({ ...node, children: children.length ? children : node.children ?? [] })
        return acc
    }, [])
}

async function loadRuleTree() {
    try {
        ruleTree.value = await getRuleTree()
    } catch {
        // 静默失败，授权树为空不影响列表展示
    }
}

// ── 搜索 / 重置 ────────────────────────────────────────────────
function handleSearch(params: Record<string, any>) {
    query.value = { ...query.value, ...params, page: 1 }
    loadData()
}
function handleReset() {
    query.value = { page: 1, pageSize: query.value.pageSize, keyword: '', permissionCode: '', status: '' }
    loadData()
}

function toggleExpandAll() {
    isAllExpanded.value = !isAllExpanded.value
    tableRenderKey.value += 1
}

// ── 新增 / 编辑 ────────────────────────────────────────────────
function openCreate() {
    formMode.value = 'create'
    currentRow.value = null
    formDrawerVisible.value = true
}
function openEdit(row: GroupItem) {
    formMode.value = 'edit'
    currentRow.value = { ...row }
    formDrawerVisible.value = true
}
function handleFormSubmit() {
    formDrawerVisible.value = false
    loadData()
}

// ── 规则授权 ───────────────────────────────────────────────────
function openRules(row: GroupItem) {
    currentRow.value = { ...row }
    rulesDrawerVisible.value = true
}
function handleRulesSubmit() {
    rulesDrawerVisible.value = false
    loadData()
}

// ── 状态切换 ───────────────────────────────────────────────────
async function handleStatusToggle(row: GroupItem, active: boolean) {
    const status = active ? 'Active' : 'Disabled'
    try {
        await updateGroupStatus(row.groupCode, { status })
        row.status = status
        ElMessage.success(`已${active ? '启用' : '禁用'}「${row.groupName}」`)
    } catch {
        /* 统一处理 */
    }
}

// ── 删除 ───────────────────────────────────────────────────────
async function handleDelete(row: GroupItem) {
    try {
        await ElMessageBox.confirm(
            `确定删除权限组「${row.groupName}」（${row.groupCode}）？\n删除前请确认无子组且无关联用户，否则后端会拒绝。`,
            '删除确认',
            { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
        )
        await deleteGroup(row.groupCode)
        ElMessage.success('权限组已删除')
        loadData()
    } catch (e: any) {
        if (e === 'cancel' || e?.message === 'cancel') return
    }
}

// ── 初始化 ─────────────────────────────────────────────────────
onMounted(() => {
    loadData()
    loadRuleTree()
})
</script>

<style scoped>
.rbac-group-page {
    font-family:
        'SF Pro Text',
        system-ui,
        -apple-system,
        sans-serif;
}

.group-table-wrapper {
    background: #fff;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #e0e0e0;
}

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

.group-cell {
    display: inline-flex;
    flex-direction: column;
    justify-content: center;
    gap: 2px;
    min-width: 0;
    vertical-align: middle;
}

.group-name {
    color: #1d1d1f;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.group-code {
    font-family: 'SF Mono', Menlo, Consolas, monospace;
    font-size: 12px;
    color: #0066cc;
    background: #f0f6ff;
    padding: 2px 7px;
    border-radius: 4px;
    border: 1px solid #cce0ff;
}

.code-text {
    color: #333333;
    font-family: 'SF Mono', Menlo, Consolas, monospace;
    font-size: 12px;
    line-height: 1.4;
}

.perm-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    align-items: center;
}

.perm-tag {
    font-family: 'SF Mono', Menlo, Consolas, monospace;
    font-size: 11px;
    border-radius: 4px;
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.perm-more-icon {
    color: #86868b;
    font-size: 14px;
    cursor: pointer;
    margin-left: 2px;
}

.text-muted {
    color: #86868b;
    font-size: 13px;
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
    background-color: #0066cc !important;
    border-color: #0066cc !important;
}

:deep(.el-pagination.is-background .el-pager li.is-active) {
    background-color: #0066cc;
}

:deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
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
