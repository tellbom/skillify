<template>
  <div class="rbac-admin-page">

    <Commonsearch
      :fields="searchFields"
      @search="handleSearch"
      @reset="handleReset"
    />

    <Commontable
      :table-data="tableData"
      :columns="tableColumns"
      :total="total"
      :current-page="query.page"
      :page-size="query.pageSize"
      :show-selection="true"
      row-key="userid"
      :operation-width="180"
      storage-key="rbac-admin-table-columns"
      @page-change="handlePageChange"
      @size-change="handleSizeChange"
      @selection-change="handleSelectionChange"
    >
      <template #toolbar-left="{ selection }">
        <el-button
          v-if="canCreate"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >
          新增管理员
        </el-button>
        <el-button
          v-if="selection.length > 0 && canDelete"
          type="danger"
          :icon="Delete"
          @click="handleBatchDelete(selection)"
        >
          批量删除 ({{ selection.length }})
        </el-button>
        <el-button :icon="Refresh" circle @click="loadData" title="刷新" />
      </template>

      <!-- 状态列 -->
      <template #status="{ row }">
        <el-tag
          :type="row.status === 'Active' ? 'success' : 'danger'"
          size="small"
          class="status-tag"
        >
          {{ row.status === 'Active' ? '启用' : '禁用' }}
        </el-tag>
      </template>

      <!-- 权限组列 -->
      <template #groupNames="{ row }">
        <div class="tag-list">
          <el-tag
            v-for="name in (row.groupNames || []).slice(0, 3)"
            :key="name"
            size="small"
            type="info"
            class="group-tag"
          >{{ name }}</el-tag>
          <el-tag v-if="(row.groupNames || []).length > 3" size="small" type="info">
            +{{ row.groupNames.length - 3 }}
          </el-tag>
          <span v-if="!row.groupNames?.length" class="text-muted">—</span>
        </div>
      </template>

      <!-- 超管标识（只读展示，操作在 projectGrant 页面） -->
      <template #isSuper="{ row }">
        <el-tooltip
          content="超管权限在「超管管理」页面调整"
          placement="top"
          :disabled="!row.isSuper"
        >
          <el-tag v-if="row.isSuper" size="small" class="super-tag">
            <i class="fa fa-star" /> 超管
          </el-tag>
          <span v-else class="text-muted">
              <el-tag size="small" type="info">普通</el-tag>
          </span>
        </el-tooltip>
      </template>

      <!-- 操作列：无授权相关按钮 -->
      <template #operation="{ row }">
        <el-button
          v-if="canEdit"
          type="primary" link size="small" :icon="Edit"
          @click="openEdit(row)"
        >编辑</el-button>
        <el-button
          v-if="canDelete && row.userid !== currentUserid"
          type="danger" link size="small" :icon="Delete"
          @click="handleDelete(row)"
        >删除</el-button>
      </template>
    </Commontable>

    <!-- 新增/编辑抽屉 -->
    <AdminFormDrawer
      v-model="formDrawerVisible"
      :mode="formMode"
      :model="currentRow"
      @submit="handleFormSubmit"
    />

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Plus, Delete, Edit, Refresh } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import Commonsearch from '/@/components/claudetable/Commonsearch.vue'
import Commontable  from '/@/components/claudetable/Commontable.vue'
import AdminFormDrawer from './components/AdminFormDrawer.vue'
import {
  getAdminList,
  deleteAdmin,
  type AdminItem,
} from '/@/api/backend/rbac'
import { useAuthStore } from '/@/stores/auth.js'

defineOptions({ name: 'auth/admin' })

const auth          = useAuthStore()
const currentUserid = computed(() => auth.rbacInfo?.userid ?? '')
const canCreate     = computed(() => auth.rbacInfo?.super === true)
const canEdit       = computed(() => auth.rbacInfo?.super === true)
const canDelete     = computed(() => auth.rbacInfo?.super === true)

const searchFields = [
  { prop: 'keyword',   label: '关键字', type: 'input',  placeholder: '用户ID / 显示名称', width: '220px' },
  { prop: 'groupCode', label: '权限组', type: 'input',  placeholder: '权限组编码',         width: '180px' },
  {
    prop: 'status', label: '状态', type: 'select', width: '140px',
    options: [{ label: '启用', value: 'Active' }, { label: '禁用', value: 'Disabled' }],
  },
]

const tableColumns = [
  { prop: 'userid',     label: '用户ID',   minWidth: 140, showOverflowTooltip: true },
  { prop: 'username',   label: '显示名称', minWidth: 120 },
  { prop: 'status',     label: '状态',     width: 80,  align: 'center' },
  { prop: 'groupNames', label: '权限组',   minWidth: 200 },
  { prop: 'isSuper',    label: '超管',     width: 90,  align: 'center' },
]

const tableData = ref<AdminItem[]>([])
const total     = ref(0)
const loading   = ref(false)
const query     = ref({ page: 1, pageSize: 20, keyword: '', groupCode: '', status: '' })

const formDrawerVisible = ref(false)
const formMode          = ref<'create' | 'edit'>('create')
const currentRow        = ref<AdminItem | null>(null)

async function loadData() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: query.value.page, pageSize: query.value.pageSize }
    if (query.value.keyword)   params.keyword   = query.value.keyword
    if (query.value.groupCode) params.groupCode = query.value.groupCode
    if (query.value.status)    params.status    = query.value.status
    const result = await getAdminList(params)
    tableData.value = result.list
    total.value     = result.total
  } catch { /* 统一处理 */ } finally {
    loading.value = false
  }
}

function handleSearch(params: Record<string, any>) {
  query.value = { ...query.value, ...params, page: 1 }
  loadData()
}
function handleReset() {
  query.value = { page: 1, pageSize: query.value.pageSize, keyword: '', groupCode: '', status: '' }
  loadData()
}
function handlePageChange(page: number)  { query.value.page = page; loadData() }
function handleSizeChange(size: number)  { query.value.pageSize = size; query.value.page = 1; loadData() }

const selectedRows = ref<AdminItem[]>([])
function handleSelectionChange(rows: AdminItem[]) { selectedRows.value = rows }

function openCreate() {
  formMode.value = 'create'; currentRow.value = null; formDrawerVisible.value = true
}
function openEdit(row: AdminItem) {
  formMode.value = 'edit'; currentRow.value = { ...row }; formDrawerVisible.value = true
}
function handleFormSubmit() {
  formDrawerVisible.value = false; loadData()
}

async function handleDelete(row: AdminItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除管理员「${row.username}」（${row.userid}）？`,
      '删除确认',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
    )
    await deleteAdmin(row.userid)
    ElMessage.success('删除成功')
    loadData()
  } catch (e: any) {
    if (e === 'cancel' || e?.message === 'cancel') return
  }
}

async function handleBatchDelete(rows: AdminItem[]) {
  try {
    await ElMessageBox.confirm(
      `确定批量删除选中的 ${rows.length} 位管理员？`,
      '批量删除确认',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
    )
    await Promise.all(rows.map(r => deleteAdmin(r.userid)))
    ElMessage.success(`已删除 ${rows.length} 位管理员`)
    loadData()
  } catch (e: any) {
    if (e === 'cancel' || e?.message === 'cancel') return
  }
}

onMounted(() => loadData())
</script>

<style scoped>
.rbac-admin-page { font-family: 'SF Pro Text', system-ui, -apple-system, sans-serif; }

.status-tag { font-size: 12px; font-weight: 600; border-radius: 6px; }

.super-tag {
  background: #fff3e0; color: #e65100;
  border-color: #ffcc80; font-size: 12px; font-weight: 600; border-radius: 6px;
  cursor: default;
}

.tag-list { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.group-tag { font-size: 12px; letter-spacing: -0.12px; border-radius: 6px; }
.text-muted { color: #86868b; font-size: 13px; }

:deep(.el-button--primary) {
  --el-button-bg-color: #0066cc; --el-button-border-color: #0066cc;
  --el-button-hover-bg-color: #0071e3; --el-button-hover-border-color: #0071e3;
}
:deep(.el-button--primary.is-link) {
  --el-button-text-color: #0066cc; --el-button-hover-text-color: #0071e3;
}
:deep(.el-pagination.is-background .el-pager li.is-active) { background-color: #0066cc; }
:deep(.el-checkbox__input.is-checked .el-checkbox__inner) { background-color: #0066cc; border-color: #0066cc; }
:deep(.el-tag--success) { --el-tag-bg-color: #e6f4ea; --el-tag-border-color: #b7dfbc; --el-tag-text-color: #1e7e34; }
:deep(.el-tag--danger)  { --el-tag-bg-color: #fef0f0; --el-tag-border-color: #fbc4c4; --el-tag-text-color: #c0392b; }
</style>
