/**
 * RBAC API 模块统一出口
 *
 * 移植自 E:\Web\flow\web\src\api\backend\rbac\index.ts（N4.2），逐字未改动。
 *
 * 使用方式：
 *   import { getAdminList, createAdmin } from '/@/api/backend/rbac'
 *   import type { AdminItem, GroupForm } from '/@/api/backend/rbac'
 */

// Client 核心
export { rbacClient, RBAC_PROJECT, RbacApiError, isRbacConfigured } from './client'
export type { RbacResponse, PagedData, PagedQuery } from './client'

// 类型定义
export type {
    RecordStatus,
    RuleType,
    RuleMenuType,
    HttpMethod,
    ApiAction,
    LoginResult,
    BackendIndexResult,
    RbacAdminInfo,
    MenuNode,
    AdminItem,
    AdminCreateForm,
    AdminUpdateForm,
    AdminStatusForm,
    AdminUsernameForm,
    GroupIndexResult,
    GroupTreeNode,
    GroupSelectResult,
    GroupSelectOption,
    GroupItem,
    GroupCreateForm,
    GroupUpdateForm,
    GroupRulesForm,
    GroupStatusForm,
    GroupMemberAddForm,
    RuleTreeNode,
    RuleItem,
    RuleCreateForm,
    RuleUpdateForm,
    RuleStatusForm,
    RuleWeighForm,
    ProjectGrantForm,
    ProjectGrantSuperForm,
    ApiMapRecordItem,
    ApiMapViewItem,
    ApiMapCreateForm,
    ApiMapCreateResult,
    ApiMapUpdateForm,
    AuditLogQuery,
    AuditLogItem,
    PermissionViewQuery,
    PermissionViewItem,
} from './types'

// 适配器工具
export {
    toRuleType,
    fromRuleType,
    toMenuType,
    fromMenuType,
    toRecordStatus,
    fromRecordStatus,
    toKeepalive,
    fromKeepalive,
    suggestPermissionCode,
    getStatusDisplay,
    getRuleTypeDisplay,
    getSuperDisplay,
    normalizePageParams,
} from './adapters'

// 管理员 API
export { rbacLogin, getBackendIndex, getAdminList, createAdmin, updateAdmin, updateAdminStatus, updateAdminUsername, deleteAdmin } from './admin'
export type { AdminListQuery } from './admin'

// 权限组 API
export {
    getGroupIndex,
    getGroupOptions,
    getGroupList,
    createGroup,
    updateGroup,
    updateGroupRules,
    updateGroupStatus,
    addGroupMember,
    removeGroupMember,
    deleteGroup,
} from './group'
export type { GroupIndexQuery, GroupListQuery } from './group'

// 规则 API
export { getRuleTree, getRuleList, createRule, updateRule, updateRuleStatus, updateRuleWeigh, deleteRule } from './rule'
export type { RuleListQuery } from './rule'

// Project 授权 API
export { grantProjectAccess, revokeProjectAccess, toggleProjectSuper } from './projectGrant'

// API 映射 API
export { getApiMapList, getApiMapRecords, createApiMap, updateApiMap, deleteApiMap, searchAuditLogs, searchPermissionView } from './apiMap'
export type { ApiMapListQuery, ApiMapRecordsQuery } from './apiMap'
