/**
 * Project 授权接口模块 /api/project-grant
 *
 * 移植自 E:\Web\flow\web\src\api\backend\rbac\projectGrant\index.ts（N4.2），逐字未改动。
 *
 * 超管是 Project 维度，不是全局管理员字段。
 * 重要：
 * - 授权到 Project 和设为超管是两个独立动作。
 * - 用户没有当前 Project 授权时，直接调用 super 接口会失败。
 * - DELETE 是高风险操作，前端必须 ElMessageBox 二次确认。
 */

import { rbacClient } from '../client'
import type { ProjectGrantForm, ProjectGrantSuperForm } from '../types'

/**
 * POST /api/project-grant
 * 将用户授权到当前 project。若已存在，仅更新 super 标记。
 */
export async function grantProjectAccess(
    form: ProjectGrantForm
): Promise<void> {
    return rbacClient.post<any, void>('/api/project-grant', form)
}

/**
 * DELETE /api/project-grant/{userid}
 * 撤销指定用户在当前 project 的授权。⚠️ 高风险操作，调用前必须二次确认。
 */
export async function revokeProjectAccess(userid: string): Promise<void> {
    return rbacClient.delete<any, void>(
        `/api/project-grant/${encodeURIComponent(userid)}`
    )
}

/**
 * PUT /api/project-grant/{userid}/super
 * 切换用户在当前 project 下的 super 标记。⚠️ 超管权限变更，调用前必须二次确认。
 */
export async function toggleProjectSuper(
    userid: string,
    form: ProjectGrantSuperForm
): Promise<void> {
    return rbacClient.put<any, void>(
        `/api/project-grant/${encodeURIComponent(userid)}/super`,
        form
    )
}
