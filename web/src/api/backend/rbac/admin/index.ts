/**
 * 管理员接口模块 /api/admin
 *
 * 移植自 E:\Web\flow\web\src\api\backend\rbac\admin\index.ts（N4.2），逐字未改动。
 */

import { rbacClient } from '../client'
import type { PagedData } from '../client'
import type {
    AdminCreateForm,
    AdminItem,
    AdminStatusForm,
    AdminUpdateForm,
    AdminUsernameForm,
    BackendIndexResult,
    LoginResult,
    PagedQuery,
} from '../types'

// ── 认证 / 初始化 ─────────────────────────────────────────────────────────────

/**
 * POST /api/auth/login
 * 校验当前 JWT 用户是否可进入当前 project，回传登录态数据。
 * 不签发 token，仅验证通过性。
 */
export async function rbacLogin(): Promise<LoginResult> {
    return rbacClient.post<any, LoginResult>('/api/auth/login')
}

/**
 * GET /api/admin/index
 * 后台初始化：返回当前管理员信息、权限裁剪后的菜单树、初始路由。
 */
export async function getBackendIndex(): Promise<BackendIndexResult> {
    return rbacClient.get<any, BackendIndexResult>('/api/admin/index')
}

// ── 管理员 CRUD ───────────────────────────────────────────────────────────────

export interface AdminListQuery extends PagedQuery {
    userid?: string
    groupCode?: string
}

/**
 * GET /api/admin/list
 * 分页查询管理员列表。
 */
export async function getAdminList(
    query: AdminListQuery = {}
): Promise<PagedData<AdminItem>> {
    return rbacClient.get<any, PagedData<AdminItem>>('/api/admin/list', {
        params: query,
    })
}

/**
 * POST /api/admin
 * 新增管理员账号，可同时加入权限组。
 */
export async function createAdmin(
    form: AdminCreateForm
): Promise<{ userid: string }> {
    return rbacClient.post<any, { userid: string }>('/api/admin', form)
}

/**
 * PUT /api/admin/{userid}
 * 完整编辑管理员。null 字段不修改。
 */
export async function updateAdmin(
    userid: string,
    form: AdminUpdateForm
): Promise<void> {
    return rbacClient.put<any, void>(`/api/admin/${encodeURIComponent(userid)}`, form)
}

/**
 * PUT /api/admin/{userid}/status
 * 快速启用或禁用管理员。
 */
export async function updateAdminStatus(
    userid: string,
    form: AdminStatusForm
): Promise<void> {
    return rbacClient.put<any, void>(
        `/api/admin/${encodeURIComponent(userid)}/status`,
        form
    )
}

/**
 * PUT /api/admin/{userid}/username
 * 快速更新管理员显示名称。
 */
export async function updateAdminUsername(
    userid: string,
    form: AdminUsernameForm
): Promise<void> {
    return rbacClient.put<any, void>(
        `/api/admin/${encodeURIComponent(userid)}/username`,
        form
    )
}

/**
 * DELETE /api/admin/{userid}
 * 删除管理员账号，清理相关授权关系。
 */
export async function deleteAdmin(userid: string): Promise<void> {
    return rbacClient.delete<any, void>(`/api/admin/${encodeURIComponent(userid)}`)
}
