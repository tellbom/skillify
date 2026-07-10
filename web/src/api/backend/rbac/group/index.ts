/**
 * 权限组接口模块 /api/group
 *
 * 移植自 E:\Web\flow\web\src\api\backend\rbac\group\index.ts（N4.2），逐字未改动。
 */

import { rbacClient } from '../client'
import type { PagedData } from '../client'
import type {
    GroupCreateForm,
    GroupIndexResult,
    GroupItem,
    GroupMemberAddForm,
    GroupRulesForm,
    GroupSelectResult,
    GroupStatusForm,
    GroupUpdateForm,
    PagedQuery,
} from '../types'

// ── 权限组查询 ─────────────────────────────────────────────────────────────────

export interface GroupIndexQuery {
    select?: boolean
    isTree?: boolean
    quickSearch?: string
}

/**
 * GET /api/group/index
 * 返回 BuildAdmin 兼容的权限组树/选择项。
 */
export async function getGroupIndex(
    query: GroupIndexQuery = {}
): Promise<GroupIndexResult | GroupSelectResult> {
    return rbacClient.get<any, GroupIndexResult | GroupSelectResult>(
        '/api/group/index',
        { params: query }
    )
}

/**
 * GET /api/group/index?select=true
 * 获取权限组选择项（用于 el-select 和管理员表单中的权限组多选）。
 */
export async function getGroupOptions(): Promise<GroupSelectResult> {
    return rbacClient.get<any, GroupSelectResult>('/api/group/index', {
        params: { select: true },
    })
}

export interface GroupListQuery extends PagedQuery {
    groupCode?: string
    permissionCode?: string
}

/**
 * GET /api/group/list
 * 分页查询权限组列表。
 */
export async function getGroupList(
    query: GroupListQuery = {}
): Promise<PagedData<GroupItem>> {
    return rbacClient.get<any, PagedData<GroupItem>>('/api/group/list', {
        params: query,
    })
}

// ── 权限组 CRUD ───────────────────────────────────────────────────────────────

/**
 * POST /api/group
 * 新建权限组。ruleCodes: ["*"] 表示全部权限。
 */
export async function createGroup(
    form: GroupCreateForm
): Promise<{ groupCode: string }> {
    return rbacClient.post<any, { groupCode: string }>('/api/group', form)
}

/**
 * PUT /api/group/{groupCode}
 * 完整编辑权限组。null 字段不修改。parentGroupCode: "" 表示提升为根组。
 */
export async function updateGroup(
    groupCode: string,
    form: GroupUpdateForm
): Promise<void> {
    return rbacClient.put<any, void>(
        `/api/group/${encodeURIComponent(groupCode)}`,
        form
    )
}

/**
 * PUT /api/group/{groupCode}/rules
 * 更新权限组规则授权。
 */
export async function updateGroupRules(
    groupCode: string,
    form: GroupRulesForm
): Promise<void> {
    return rbacClient.put<any, void>(
        `/api/group/${encodeURIComponent(groupCode)}/rules`,
        form
    )
}

/**
 * PUT /api/group/{groupCode}/status
 * 快速启用或禁用权限组。
 */
export async function updateGroupStatus(
    groupCode: string,
    form: GroupStatusForm
): Promise<void> {
    return rbacClient.put<any, void>(
        `/api/group/${encodeURIComponent(groupCode)}/status`,
        form
    )
}

// ── 权限组成员管理 ─────────────────────────────────────────────────────────────

/**
 * POST /api/group/{groupCode}/members
 * 将用户加入权限组。
 */
export async function addGroupMember(
    groupCode: string,
    form: GroupMemberAddForm
): Promise<void> {
    return rbacClient.post<any, void>(
        `/api/group/${encodeURIComponent(groupCode)}/members`,
        form
    )
}

/**
 * DELETE /api/group/{groupCode}/members/{userid}
 * 将用户从权限组移除。
 */
export async function removeGroupMember(
    groupCode: string,
    userid: string
): Promise<void> {
    return rbacClient.delete<any, void>(
        `/api/group/${encodeURIComponent(groupCode)}/members/${encodeURIComponent(userid)}`
    )
}

/**
 * DELETE /api/group/{groupCode}
 * 删除权限组。前置条件（由后端校验）：无子组、无关联用户、操作人不属于该组。
 */
export async function deleteGroup(groupCode: string): Promise<void> {
    return rbacClient.delete<any, void>(
        `/api/group/${encodeURIComponent(groupCode)}`
    )
}
