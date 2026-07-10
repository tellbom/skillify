<template>
  <div class="rbac-grant-page">

    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header__info">
        <h2 class="page-title">超管权限管理</h2>
        <p class="page-desc">
          管理用户在 Project
          <el-tag type="info" size="small" class="project-tag">{{ rbacProject }}</el-tag>
          下的超管权限。超管可访问完整菜单，不受权限组限制，变更立即触发缓存失效。
        </p>
      </div>
      <el-tag v-if="auth.rbacInfo?.super" size="small" class="self-super-tag">
        <i class="fa fa-star" /> 当前账号：超管
      </el-tag>
    </div>

    <!-- 搜索 -->
    <Commonsearch
      :fields="searchFields"
      @search="handleSearch"
      @reset="handleReset"
    />

    <!-- 表格 -->
    <Commontable
      :table-data="tableData"
      :columns="tableColumns"
      :total="total"
      :current-page="query.page"
      :page-size="query.pageSize"
      :show-operation="true"
      :operation-width="140"
      row-key="userid"
      storage-key="rbac-grant-table-columns"
      @page-change="handlePageChange"
      @size-change="handleSizeChange"
    >
      <template #toolbar-left>
        <el-button :icon="Refresh" @click="loadData" title="刷新" />
        <!-- 说明文字 -->
        <span class="toolbar-tip">
          <i class="fa fa-info-circle" />
          新增/删除管理员请前往「管理员管理」
        </span>
      </template>

      <!-- 用户列 -->
      <template #userid="{ row }">
        <div class="user-cell">
          <div class="user-avatar" :class="row.isSuper ? 'avatar--super' : ''">
            <i :class="row.isSuper ? 'fa fa-star' : 'fa fa-user'" />
          </div>
          <div class="user-info">
            <span class="user-name">{{ row.username }}</span>
            <code class="user-id">{{ row.userid }}</code>
          </div>
        </div>
      </template>

      <!-- 超管状态列 -->
      <template #isSuper="{ row }">
        <el-tag
          v-if="row.isSuper"
          size="small"
          class="super-tag"
        >
          <i class="fa fa-star" /> 超管
        </el-tag>
        <el-tag v-else size="small" type="info">普通</el-tag>
      </template>

      <!-- Project 授权列 -->
      <template #grantStatus="{ row }">
        <el-tag
          :type="isGranted(row) ? 'success' : 'info'"
          size="small"
        >
          {{ isGranted(row) ? '已授权' : '未授权' }}
        </el-tag>
      </template>

      <!-- 账号状态列 -->
      <template #status="{ row }">
        <el-tag :type="row.status === 'Active' ? 'success' : 'danger'" size="small">
          {{ row.status === 'Active' ? '启用' : '禁用' }}
        </el-tag>
      </template>

      <!-- 操作列：只有升级/降级 -->
      <template #operation="{ row }">
        <!-- 未授权 Project 时不显示超管操作 -->
        <template v-if="!isGranted(row)">
          <span class="no-grant-tip">未授权 Project</span>
        </template>

        <!-- 自己不能修改自己 -->
        <template v-else-if="row.userid === selfUserid">
          <span class="self-tip">当前账号</span>
        </template>

        <!-- 升/降级按钮 -->
        <template v-else-if="canManage">
          <el-button
            v-if="!row.isSuper"
            type="warning"
            link
            size="small"
            :icon="Star"
            :loading="loadingMap[row.userid]"
            @click="handleSetSuper(row, true)"
          >
            升为超管
          </el-button>
          <el-button
            v-else
            type="info"
            link
            size="small"
            :icon="StarFilled"
            :loading="loadingMap[row.userid]"
            @click="handleSetSuper(row, false)"
          >
            降为普通
          </el-button>
        </template>

        <!-- 无权限 -->
        <template v-else>
          <span class="no-perm-tip">无操作权限</span>
        </template>
      </template>
    </Commontable>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted } from 'vue'
import { Refresh, Star, StarFilled } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import Commonsearch from '/@/components/claudetable/Commonsearch.vue'
import Commontable  from '/@/components/claudetable/Commontable.vue'
import {
  getAdminList,
  toggleProjectSuper,
  RBAC_PROJECT,
  type AdminItem,
} from '/@/api/backend/rbac'
import { useAuthStore } from '/@/stores/auth.js'

defineOptions({ name: 'auth/projectGrant' })

const auth        = useAuthStore()
const rbacProject = RBAC_PROJECT
const selfUserid  = computed(() => auth.rbacInfo?.userid ?? '')
const canManage   = computed(() => auth.rbacInfo?.super === true)

// ── 搜索字段 ───────────────────────────────────────────────────
const searchFields = [
  { prop: 'keyword', label: '关键字', type: 'input', placeholder: '用户ID / 显示名称', width: '220px' },
  {
    prop: 'isSuper',
    label: '超管状态',
    type: 'select',
    width: '140px',
    options: [
      { label: '超管', value: 'true' },
      { label: '普通', value: 'false' },
    ],
  },
  {
    prop: 'status', label: '账号状态', type: 'select', width: '140px',
    options: [{ label: '启用', value: 'Active' }, { label: '禁用', value: 'Disabled' }],
  },
]

// ── 表格列 ─────────────────────────────────────────────────────
const tableColumns = [
  { prop: 'userid',      label: '用户',         minWidth: 200 },
  { prop: 'isSuper',     label: '超管权限',      width: 100, align: 'center' },
  { prop: 'grantStatus', label: 'Project 授权',  width: 110, align: 'center' },
  { prop: 'status',      label: '账号状态',      width: 90,  align: 'center' },
]

// ── 数据 ───────────────────────────────────────────────────────
const tableData  = ref<AdminItem[]>([])
const total      = ref(0)
const loading    = ref(false)
const loadingMap = reactive<Record<string, boolean>>({})

const query = ref({ page: 1, pageSize: 20, keyword: '', isSuper: '', status: '' })

function isGranted(row: AdminItem): boolean {
  return (row.projectCodes ?? []).includes(rbacProject)
}

// ── 加载 ───────────────────────────────────────────────────────
async function loadData() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: query.value.page, pageSize: query.value.pageSize }
    if (query.value.keyword) params.keyword = query.value.keyword
    if (query.value.status)  params.status  = query.value.status
    // isSuper 过滤暂时前端处理（后端 list 接口暂不支持此参数）
    const result = await getAdminList(params)

    // 前端过滤 isSuper
    let list = result.list
    if (query.value.isSuper === 'true')  list = list.filter(r => r.isSuper)
    if (query.value.isSuper === 'false') list = list.filter(r => !r.isSuper)

    tableData.value = list
    total.value     = query.value.isSuper ? list.length : result.total
  } catch { /* 统一处理 */ } finally {
    loading.value = false
  }
}

function handleSearch(params: Record<string, any>) {
  query.value = { ...query.value, ...params, page: 1 }
  loadData()
}
function handleReset() {
  query.value = { page: 1, pageSize: query.value.pageSize, keyword: '', isSuper: '', status: '' }
  loadData()
}
function handlePageChange(page: number)  { query.value.page = page; loadData() }
function handleSizeChange(size: number)  { query.value.pageSize = size; query.value.page = 1; loadData() }

// ── 超管升降级 ─────────────────────────────────────────────────
async function handleSetSuper(row: AdminItem, toSuper: boolean) {
  const action = toSuper ? '升为超管' : '降为普通用户'
  const confirmMsg = toSuper
    ? `确定将「${row.username}」升为超管？\n超管可访问 ${rbacProject} 完整菜单，不受权限组限制，权限变更立即生效。`
    : `确定将「${row.username}」从超管降为普通用户？\n降级后仅保留其权限组内的访问权限。`

  try {
    await ElMessageBox.confirm(confirmMsg, `${action}确认`, {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning',
    })
  } catch { return }

  loadingMap[row.userid] = true
  try {
    await toggleProjectSuper(row.userid, { isSuper: toSuper })
    ElMessage.success(`${action}成功`)
    loadData()
  } catch {
    // 统一处理
  } finally {
    loadingMap[row.userid] = false
  }
}

onMounted(() => loadData())
</script>

<style scoped>
.rbac-grant-page {
  font-family: 'SF Pro Text', system-ui, -apple-system, sans-serif;
}

/* 页头 */
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 16px 20px;
  background: #fff;
  border-radius: 10px;
  border: 1px solid #e5e5e5;
}

.page-title {
  font-family: 'SF Pro Display', system-ui, -apple-system, sans-serif;
  font-size: 20px;
  font-weight: 600;
  color: #1d1d1f;
  margin: 0 0 6px;
  letter-spacing: 0.231px;
}

.page-desc {
  font-size: 13px;
  color: #86868b;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  line-height: 1.5;
}

.project-tag {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 600;
}

.self-super-tag {
  background: #fff3e0;
  color: #e65100;
  border-color: #ffcc80;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

/* 工具栏提示 */
.toolbar-tip {
  font-size: 12px;
  color: #86868b;
  display: flex;
  align-items: center;
  gap: 5px;
  margin-left: 8px;
}

.toolbar-tip .fa { color: #0066cc; }

/* 用户单元格 */
.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #0066cc 0%, #2997ff 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 14px;
  flex-shrink: 0;
  transition: background 0.2s;
}

.user-avatar.avatar--super {
  background: linear-gradient(135deg, #e65100 0%, #ff8f00 100%);
}

.user-info { display: flex; flex-direction: column; gap: 2px; }

.user-name {
  font-size: 14px;
  font-weight: 500;
  color: #1d1d1f;
  letter-spacing: -0.224px;
}

.user-id {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 11px;
  color: #86868b;
  background: #f5f5f7;
  padding: 1px 5px;
  border-radius: 3px;
  display: inline-block;
}

/* 超管标签 */
.super-tag {
  background: #fff3e0;
  color: #e65100;
  border-color: #ffcc80;
  font-size: 12px;
  font-weight: 600;
}

/* 操作列占位文字 */
.no-grant-tip,
.self-tip,
.no-perm-tip {
  font-size: 12px;
  color: #c0c0c0;
}

/* 颜色覆盖 */
:deep(.el-button--primary) {
  --el-button-bg-color: #0066cc; --el-button-border-color: #0066cc;
  --el-button-hover-bg-color: #0071e3; --el-button-hover-border-color: #0071e3;
}
:deep(.el-button--warning.is-link) {
  --el-button-text-color: #e65100;
  --el-button-hover-text-color: #bf3600;
}
:deep(.el-button--info.is-link) {
  --el-button-text-color: #86868b;
  --el-button-hover-text-color: #3d3d3f;
}
:deep(.el-pagination.is-background .el-pager li.is-active) { background-color: #0066cc; }
:deep(.el-tag--success) { --el-tag-bg-color: #e6f4ea; --el-tag-border-color: #b7dfbc; --el-tag-text-color: #1e7e34; }
:deep(.el-tag--danger)  { --el-tag-bg-color: #fef0f0; --el-tag-border-color: #fbc4c4; --el-tag-text-color: #c0392b; }
:deep(.el-tag--info)    { --el-tag-bg-color: #f5f5f7; --el-tag-border-color: #e0e0e0; --el-tag-text-color: #86868b; }
:deep(.el-table th.el-table__cell) {
  background: #f5f5f7 !important;
  font-size: 13px; font-weight: 600; color: #1d1d1f;
}
</style>
