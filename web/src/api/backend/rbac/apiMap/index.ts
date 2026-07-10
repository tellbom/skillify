/**
 * API 权限映射接口模块 /api/api-map
 *
 * 移植自 E:\Web\flow\web\src\api\backend\rbac\apiMap\index.ts（N4.2），逐字未改动。
 *
 * /list 是权限视图查询，适合只读展示和授权选择；
 * /records 是 MySQL 真相表查询，适合管理页增删改查。
 */

import { rbacClient } from '../client'
import type { PagedData, PagedQuery } from '../client'
import type {
    ApiMapCreateForm,
    ApiMapCreateResult,
    ApiMapRecordItem,
    ApiMapUpdateForm,
    ApiMapViewItem,
    AuditLogItem,
    AuditLogQuery,
    PermissionViewItem,
    PermissionViewQuery,
} from '../types'

// ── API 映射 ──────────────────────────────────────────────────────────────────

export interface ApiMapListQuery extends PagedQuery {
    permissionCode?: string
    action?: string
    resourceType?: string
}

export type ApiMapRecordsQuery = Pick<PagedQuery, 'page' | 'pageSize' | 'keyword' | 'status'>

/**
 * GET /api/api-map/list
 * 分页查询权限视图（等价于 /api/search/permission-view）。
 * 当前响应缺少 id/httpMethod/routePattern，仅支持只读展示。
 */
export async function getApiMapList(query: ApiMapListQuery = {}): Promise<PagedData<ApiMapViewItem>> {
    return rbacClient.get<any, PagedData<ApiMapViewItem>>('/api/api-map/list', {
        params: query,
    })
}

/**
 * GET /api/api-map/records
 * 分页查询 API 映射完整记录，用于管理页列表、编辑回显和删除定位。
 */
export async function getApiMapRecords(query: ApiMapRecordsQuery = {}): Promise<PagedData<ApiMapRecordItem>> {
    return rbacClient.get<any, PagedData<ApiMapRecordItem>>('/api/api-map/records', { params: query })
}

/**
 * POST /api/api-map
 * 新增 API 权限映射。routePattern 必须以 /api/ 开头，路由参数使用 {name} 格式。
 */
export async function createApiMap(form: ApiMapCreateForm): Promise<ApiMapCreateResult> {
    return rbacClient.post<any, ApiMapCreateResult>('/api/api-map', form)
}

/**
 * PUT /api/api-map/{id}
 * 更新权限码或动作。id 为后端返回的 Guid。
 */
export async function updateApiMap(id: string, form: ApiMapUpdateForm): Promise<void> {
    return rbacClient.put<any, void>(`/api/api-map/${encodeURIComponent(id)}`, form)
}

/**
 * DELETE /api/api-map/{id}
 * 删除 API 权限映射。⚠️ 变更会触发 api-map 缓存失效。
 */
export async function deleteApiMap(id: string): Promise<void> {
    return rbacClient.delete<any, void>(`/api/api-map/${encodeURIComponent(id)}`)
}

// ── 查询接口 /api/search ──────────────────────────────────────────────────────

/**
 * GET /api/search/audit-logs
 * 查询鉴权审计日志（只读，不产生写操作和 Outbox 事件）。
 */
export async function searchAuditLogs(query: AuditLogQuery = {}): Promise<PagedData<AuditLogItem>> {
    return rbacClient.get<any, PagedData<AuditLogItem>>('/api/search/audit-logs', { params: query })
}

/**
 * GET /api/search/permission-view
 * 查询 API 到权限码的权限视图（只读）。
 */
export async function searchPermissionView(query: PermissionViewQuery = {}): Promise<PagedData<PermissionViewItem>> {
    return rbacClient.get<any, PagedData<PermissionViewItem>>('/api/search/permission-view', { params: query })
}
