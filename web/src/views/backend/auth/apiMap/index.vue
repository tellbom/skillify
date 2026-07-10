<template>
    <div class="rbac-apimap-page">

        <Commonsearch :fields="searchFields" @search="handleSearch" @reset="handleReset" />

        <Commontable
            :table-data="tableData"
            :columns="tableColumns"
            :total="total"
            :current-page="query.page"
            :page-size="query.pageSize"
            :show-operation="true"
            :operation-width="160"
            row-key="id"
            storage-key="rbac-apimap-records-table-columns"
            @page-change="handlePageChange"
            @size-change="handleSizeChange"
        >
            <template #toolbar-left>
                <el-button type="primary" :icon="Plus" @click="openCreate"> 新增映射 </el-button>
                <el-button :icon="Refresh" circle @click="loadData" title="刷新" />
            </template>

            <template #httpMethod="{ row }">
                <el-tag size="small" :type="getMethodTagType(row.httpMethod)" class="method-tag">
                    {{ row.httpMethod }}
                </el-tag>
            </template>

            <template #routePattern="{ row }">
                <code class="route-code">{{ row.routePattern }}</code>
            </template>

            <template #permissionCode="{ row }">
                <code class="perm-code">{{ row.permissionCode }}</code>
            </template>

            <template #action="{ row }">
                <el-tag :type="getActionTagType(row.action)" size="small" class="action-tag">
                    {{ row.action }}
                </el-tag>
            </template>

            <template #status="{ row }">
                <el-tag :type="row.status === 'Active' ? 'success' : 'danger'" size="small" class="status-tag">
                    {{ row.status === 'Active' ? '启用' : '禁用' }}
                </el-tag>
            </template>

            <template #updatedAt="{ row }">
                <span class="time-text">{{ formatTime(row.updatedAt) }}</span>
            </template>

            <template #operation="{ row }">
                <el-button type="primary" link size="small" :icon="Edit" @click="openEdit(row)"> 编辑 </el-button>
                <el-button type="danger" link size="small" :icon="Delete" @click="handleDelete(row)"> 删除 </el-button>
            </template>
        </Commontable>

        <ApiMapCreateDrawer v-model="formDrawerVisible" :mode="formMode" :model="currentRow" :rule-tree="ruleTree" @submit="handleFormSubmit" />
    </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Delete, Edit, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Commonsearch from '/@/components/claudetable/Commonsearch.vue'
import Commontable from '/@/components/claudetable/Commontable.vue'
import ApiMapCreateDrawer from './components/ApiMapCreateDrawer.vue'
import { deleteApiMap, getApiMapRecords, getRuleTree, type ApiMapRecordItem, type RuleTreeNode } from '/@/api/backend/rbac'

defineOptions({ name: 'auth/apiMap' })

const searchFields = [
    {
        prop: 'keyword',
        label: '关键字',
        type: 'input',
        placeholder: '路由模板 / 权限码',
        width: '260px',
    },
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

const tableColumns = [
    { prop: 'httpMethod', label: '方法', width: 90, align: 'center' },
    { prop: 'routePattern', label: '路由模板', minWidth: 260, showOverflowTooltip: false },
    { prop: 'permissionCode', label: '权限码', minWidth: 220, showOverflowTooltip: false },
    { prop: 'action', label: 'Action', width: 110, align: 'center' },
    { prop: 'status', label: '状态', width: 90, align: 'center' },
    { prop: 'updatedAt', label: '修改时间', width: 170, align: 'center' },
]

const tableData = ref<ApiMapRecordItem[]>([])
const total = ref(0)
const loading = ref(false)
const ruleTree = ref<RuleTreeNode[]>([])

const query = ref({
    page: 1,
    pageSize: 20,
    keyword: '',
    status: '',
})

const formDrawerVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const currentRow = ref<ApiMapRecordItem | null>(null)

async function loadData() {
    loading.value = true
    try {
        const params: Record<string, any> = {
            page: query.value.page,
            pageSize: query.value.pageSize,
        }
        if (query.value.keyword) params.keyword = query.value.keyword
        if (query.value.status) params.status = query.value.status

        const result = await getApiMapRecords(params)
        tableData.value = result.list
        total.value = result.total
    } catch {
        // rbacClient 统一处理
    } finally {
        loading.value = false
    }
}

async function loadRuleTree() {
    try {
        ruleTree.value = await getRuleTree()
    } catch {
        ruleTree.value = []
    }
}

function handleSearch(params: Record<string, any>) {
    query.value = { ...query.value, ...params, page: 1 }
    loadData()
}

function handleReset() {
    query.value = {
        page: 1,
        pageSize: query.value.pageSize,
        keyword: '',
        status: '',
    }
    loadData()
}

function handlePageChange(page: number) {
    query.value.page = page
    loadData()
}

function handleSizeChange(size: number) {
    query.value.pageSize = size
    query.value.page = 1
    loadData()
}

function openCreate() {
    formMode.value = 'create'
    currentRow.value = null
    formDrawerVisible.value = true
}

function openEdit(row: ApiMapRecordItem) {
    formMode.value = 'edit'
    currentRow.value = { ...row }
    formDrawerVisible.value = true
}

function handleFormSubmit() {
    formDrawerVisible.value = false
    loadData()
}

async function handleDelete(row: ApiMapRecordItem) {
    try {
        await ElMessageBox.confirm(`确定删除 ${row.httpMethod} ${row.routePattern} 的 API 映射？删除后会触发 api-map 缓存失效。`, '删除确认', {
            confirmButtonText: '确定删除',
            cancelButtonText: '取消',
            type: 'warning',
        })
    } catch {
        return
    }

    try {
        await deleteApiMap(row.id)
        ElMessage.success('API 映射已删除')
        loadData()
    } catch {
        // rbacClient 统一处理
    }
}

function getActionTagType(action: string): '' | 'success' | 'warning' | 'info' | 'danger' {
    const map: Record<string, any> = {
        read: 'info',
        create: 'success',
        update: '',
        delete: 'danger',
        execute: 'warning',
        access: 'info',
    }
    return map[action] ?? 'info'
}

function getMethodTagType(method: string): '' | 'success' | 'warning' | 'info' | 'danger' {
    const map: Record<string, any> = {
        GET: 'success',
        POST: '',
        PUT: 'warning',
        DELETE: 'danger',
        PATCH: 'info',
    }
    return map[method] ?? 'info'
}

function formatTime(value?: string) {
    if (!value) return '—'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    return date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(() => {
    loadData()
    loadRuleTree()
})
</script>

<style scoped>
.rbac-apimap-page {
    font-family:
        'SF Pro Text',
        system-ui,
        -apple-system,
        sans-serif;
}

.page-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 16px;
    padding: 16px 20px;
    background: #fff;
    border-radius: 8px;
    border: 1px solid #e5e5e5;
}

.page-title {
    font-family:
        'SF Pro Display',
        system-ui,
        -apple-system,
        sans-serif;
    font-size: 20px;
    font-weight: 600;
    color: #1d1d1f;
    margin: 0 0 6px;
}

.page-desc {
    font-size: 13px;
    color: #86868b;
    margin: 0;
    line-height: 1.5;
}

.page-desc code,
.route-code,
.perm-code {
    font-family: 'SF Mono', Menlo, Consolas, monospace;
}

.route-code,
.perm-code {
    font-size: 12px;
    padding: 2px 7px;
    border-radius: 4px;
    border: 1px solid #e0e0e0;
    word-break: break-all;
}

.route-code {
    color: #3d3d3f;
    background: #f5f5f7;
}

.perm-code {
    color: #0066cc;
    background: #f0f6ff;
    border-color: #cce0ff;
}

.method-tag,
.action-tag,
.status-tag {
    font-size: 12px;
    font-weight: 600;
    border-radius: 6px;
}

.action-tag {
    font-family: 'SF Mono', Menlo, Consolas, monospace;
    text-transform: lowercase;
}

.time-text {
    font-size: 12px;
    color: #606266;
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

:deep(.el-pagination.is-background .el-pager li.is-active) {
    background-color: #0066cc;
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

:deep(.el-tag--info) {
    --el-tag-bg-color: #f0f6ff;
    --el-tag-border-color: #cce0ff;
    --el-tag-text-color: #0066cc;
}

:deep(.el-tag--warning) {
    --el-tag-bg-color: #fff3e0;
    --el-tag-border-color: #ffcc80;
    --el-tag-text-color: #e65100;
}
</style>
