/**
 * 菜单/按钮规则接口模块 /api/rule
 *
 * 移植自 E:\Web\flow\web\src\api\backend\rbac\rule\index.ts（N4.2），逐字未改动。
 */

import { rbacClient } from '../client'
import type { PagedData, PagedQuery } from '../client'
import type {
    RuleCreateForm,
    RuleItem,
    RuleMenuType,
    RuleStatusForm,
    RuleTreeNode,
    RuleType,
    RuleUpdateForm,
    RuleWeighForm,
} from '../types'

// ── 规则查询 ──────────────────────────────────────────────────────────────────

/**
 * GET /api/rule/tree
 * 获取当前 project 下的完整菜单/按钮规则树。
 * 注意：权限组授权树 el-tree 必须使用 node-key="ruleCode"，不要使用 id 或 DxE_id。
 */
export async function getRuleTree(): Promise<RuleTreeNode[]> {
    return rbacClient.get<any, RuleTreeNode[]>('/api/rule/tree')
}

export interface RuleListQuery extends PagedQuery {
    ruleCode?: string
    permissionCode?: string
    type?: RuleType
    menuType?: RuleMenuType
}

/**
 * GET /api/rule/list
 * 分页查询规则列表。
 */
export async function getRuleList(
    query: RuleListQuery = {}
): Promise<PagedData<RuleItem>> {
    return rbacClient.get<any, PagedData<RuleItem>>('/api/rule/list', {
        params: query,
    })
}

// ── 规则 CRUD ─────────────────────────────────────────────────────────────────

/**
 * POST /api/rule
 * 新建菜单目录、菜单或按钮规则。Button 类型必须提供 parentRuleCode。
 */
export async function createRule(
    form: RuleCreateForm
): Promise<{ ruleCode: string }> {
    return rbacClient.post<any, { ruleCode: string }>('/api/rule', form)
}

/**
 * PUT /api/rule/{ruleCode}
 * 完整编辑规则元数据。null 字段不修改。parentRuleCode: "" 表示提升为根节点。
 */
export async function updateRule(
    ruleCode: string,
    form: RuleUpdateForm
): Promise<void> {
    return rbacClient.put<any, void>(
        `/api/rule/${encodeURIComponent(ruleCode)}`,
        form
    )
}

/**
 * PUT /api/rule/{ruleCode}/status
 * 快速启用或禁用规则。
 */
export async function updateRuleStatus(
    ruleCode: string,
    form: RuleStatusForm
): Promise<void> {
    return rbacClient.put<any, void>(
        `/api/rule/${encodeURIComponent(ruleCode)}/status`,
        form
    )
}

/**
 * PUT /api/rule/{ruleCode}/weigh
 * 更新规则排序权重。
 */
export async function updateRuleWeigh(
    ruleCode: string,
    form: RuleWeighForm
): Promise<void> {
    return rbacClient.put<any, void>(
        `/api/rule/${encodeURIComponent(ruleCode)}/weigh`,
        form
    )
}

/**
 * DELETE /api/rule/{ruleCode}
 * 删除规则。
 */
export async function deleteRule(ruleCode: string): Promise<void> {
    return rbacClient.delete<any, void>(
        `/api/rule/${encodeURIComponent(ruleCode)}`
    )
}
