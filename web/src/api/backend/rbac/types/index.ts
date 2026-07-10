/**
 * RBAC 前端类型定义
 *
 * 移植自 E:\Web\flow\web\src\api\backend\rbac\types\index.ts（N4.2），逐字未改动。
 * 所有类型以后端 README API 文档为准。
 * 禁止使用 dxeId 作为业务操作键。
 * 操作标识：管理员 userid / 权限组 groupCode / 规则 ruleCode / API映射 id(Guid)
 */

// ── 通用 ──────────────────────────────────────────────────────────────────────

export type RecordStatus = 'Active' | 'Disabled'

export type RuleType = 'MenuDir' | 'Menu' | 'Button'

export type RuleMenuType = 'Tab' | 'Link' | 'Iframe'

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'

export type ApiAction = 'read' | 'create' | 'update' | 'delete' | 'execute' | 'access'

// ── 认证 / 初始化 ─────────────────────────────────────────────────────────────

/** POST /api/auth/login 响应 data */
export interface LoginResult {
    token: string
    routePath: string
    adminInfo: RbacAdminInfo
}

/** GET /api/admin/index 响应 data */
export interface BackendIndexResult {
    adminInfo: RbacAdminInfo
    menus: MenuNode[]
    routePath: string
}

/** 当前登录管理员信息（RBAC 版本，DxE_id 以 string 返回） */
export interface RbacAdminInfo {
    /** DxE_id，JSON string，禁止当 number 用 */
    id: string
    /** 业务用户 ID，操作接口均使用此字段 */
    userid: string
    username: string
    super: boolean
    project: string
}

// ── 菜单节点（GET /api/admin/index menus / GET /api/rule/tree 节点） ─────────

export interface MenuNode {
    /** DxE_id，JSON string */
    id: string
    /** 父节点 DxE_id，根节点为 "0" */
    pid: string
    title: string
    name: string
    path: string
    icon: string
    type: 'menu_dir' | 'menu' | 'button'
    menu_type: string
    url: string
    component: string
    extend: string
    remark: string
    keepalive: boolean
    permissionCode: string
    ruleCode: string
    children?: MenuNode[]
}

// ── 管理员 /api/admin ─────────────────────────────────────────────────────────

/** GET /api/admin/list 响应项 */
export interface AdminItem {
    userid: string
    username: string
    status: RecordStatus
    /** 当前用户所属的 project 列表 */
    projectCodes: string[]
    /** 当前用户所属的权限组编码列表 */
    groupCodes: string[]
    /** 当前用户所属的权限组名称列表（展示用） */
    groupNames: string[]
    /** 该用户拥有超管身份的 project 列表 */
    superProjects: string[]
    /** 是否为当前 X-Project 的超管 */
    isSuper: boolean
}

/** POST /api/admin 请求体 */
export interface AdminCreateForm {
    userid: string
    username: string
    groupCode?: string[]
}

/** PUT /api/admin/{userid} 请求体（null 字段不修改） */
export interface AdminUpdateForm {
    username?: string | null
    status?: RecordStatus | null
    /** 目标权限组全量列表，服务端做 diff */
    groupArr?: string[] | null
}

/** PUT /api/admin/{userid}/status 请求体 */
export interface AdminStatusForm {
    status: RecordStatus
}

/** PUT /api/admin/{userid}/username 请求体 */
export interface AdminUsernameForm {
    username: string
}

// ── 权限组 /api/group ─────────────────────────────────────────────────────────

/** GET /api/group/index 普通响应 data */
export interface GroupIndexResult {
    list: GroupTreeNode[]
    total: number
    /** 当前操作者所属组编码列表（兼容旧 BuildAdmin） */
    group: string[]
    remark: string
}

/** GET /api/group/index 树节点（BuildAdmin 兼容格式） */
export interface GroupTreeNode {
    /** DxE_id，string */
    id: string
    /** 父节点 DxE_id，根节点为 "0" */
    pid: string
    name: string
    rules: string
    status: string
    update_time: number
    create_time: number
    children?: GroupTreeNode[]
    // 扩展字段（部分响应中包含）
    groupCode?: string
}

/** GET /api/group/index?select=true 响应 data */
export interface GroupSelectResult {
    options: GroupSelectOption[]
}

export interface GroupSelectOption {
    value: string
    label: string
    children?: GroupSelectOption[]
}

/** GET /api/group/list 响应项 */
export interface GroupItem {
    groupCode: string
    group_code?: string
    groupName: string
    group_name?: string
    parentGroupCode?: string | null
    parent_group_code?: string | null
    project: string
    status: RecordStatus
    permissionCodes: string[]
    permission_codes?: string[]
    children?: GroupItem[]
}

/** POST /api/group 请求体 */
export interface GroupCreateForm {
    groupCode?: string
    groupName: string
    parentGroupCode?: string
    status: RecordStatus
    /** 提交 ruleCode 列表，服务端推导 permissionCodes；["*"] 表示全部 */
    ruleCodes: string[]
}

/** PUT /api/group/{groupCode} 请求体（null 字段不修改） */
export interface GroupUpdateForm {
    groupName?: string | null
    parentGroupCode?: string | null
    status?: RecordStatus | null
    ruleCodes?: string[] | null
}

/** PUT /api/group/{groupCode}/rules 请求体 */
export interface GroupRulesForm {
    ruleCodes: string[]
}

/** PUT /api/group/{groupCode}/status 请求体 */
export interface GroupStatusForm {
    status: RecordStatus
}

/** POST /api/group/{groupCode}/members 请求体 */
export interface GroupMemberAddForm {
    userid: string
}

// ── 规则 /api/rule ─────────────────────────────────────────────────────────────

/** GET /api/rule/tree 节点（与 MenuNode 同结构，含 children） */
export type RuleTreeNode = MenuNode

/** GET /api/rule/list 响应项 */
export interface RuleItem {
    ruleCode: string
    parentRuleCode?: string | null
    parent_rule_code?: string | null
    parent_ruleCode?: string | null
    pid?: string | null
    permissionCode: string
    title: string
    type: RuleType | 'menu_dir' | 'menu' | 'button'
    status: RecordStatus
    icon: string
    name?: string
    path?: string
    menu_type?: string
    url?: string
    component?: string
    extend?: string
    remark: string
    keepalive?: boolean
    weigh?: number
}

/** POST /api/rule 请求体 */
export interface RuleCreateForm {
    ruleCode: string
    permissionCode: string
    title: string
    type: RuleType
    name?: string
    path?: string
    icon?: string
    /** Button 类型必填 */
    parentRuleCode?: string
    menuType?: RuleMenuType
    url?: string
    component?: string
    extend?: string
    remark?: string
    keepalive?: boolean
    weigh?: number
}

/** PUT /api/rule/{ruleCode} 请求体（null 字段不修改，parentRuleCode: "" 提升为根） */
export interface RuleUpdateForm {
    title?: string | null
    name?: string | null
    path?: string | null
    icon?: string | null
    parentRuleCode?: string | null
    menuType?: RuleMenuType | null
    url?: string | null
    component?: string | null
    extend?: string | null
    remark?: string | null
    keepalive?: boolean | null
    weigh?: number | null
    status?: RecordStatus | null
    permissionCode?: string | null
}

/** PUT /api/rule/{ruleCode}/status 请求体 */
export interface RuleStatusForm {
    status: RecordStatus
}

/** PUT /api/rule/{ruleCode}/weigh 请求体 */
export interface RuleWeighForm {
    weigh: number
}

// ── Project 授权 /api/project-grant ──────────────────────────────────────────

/** POST /api/project-grant 请求体 */
export interface ProjectGrantForm {
    userid: string
    isSuper: boolean
}

/** PUT /api/project-grant/{userid}/super 请求体 */
export interface ProjectGrantSuperForm {
    isSuper: boolean
}

// ── API 权限映射 /api/api-map ─────────────────────────────────────────────────

/**
 * GET /api/api-map/list 响应项（等价于权限视图，缺少 id/httpMethod/routePattern）
 * TODO: 后端补充 MySQL 源数据字段后，补充 id/httpMethod/routePattern，启用编辑/删除
 */
export interface ApiMapViewItem {
    permissionCode: string
    action: ApiAction
    resourceType: string
    title: string
}

/** GET /api/api-map/records 响应项，用于 API 映射增删改查 */
export interface ApiMapRecordItem {
    id: string
    httpMethod: HttpMethod
    routePattern: string
    permissionCode: string
    action: ApiAction
    status: RecordStatus
    createdAt: string
    updatedAt: string
}

/** POST /api/api-map 请求体 */
export interface ApiMapCreateForm {
    httpMethod: HttpMethod
    routePattern: string
    permissionCode: string
    action: ApiAction
}

/** POST /api/api-map 响应 data */
export interface ApiMapCreateResult {
    id: string
}

/** PUT /api/api-map/{id} 请求体 */
export interface ApiMapUpdateForm {
    permissionCode?: string
    action?: ApiAction
}

// ── 查询接口 /api/search ──────────────────────────────────────────────────────

/** GET /api/search/audit-logs Query 参数 */
export interface AuditLogQuery {
    userid?: string
    permissionCode?: string
    result?: 'Allow' | 'Deny' | 'Error'
    httpMethod?: string
    createdAtFrom?: string
    createdAtTo?: string
    keyword?: string
    status?: string
    page?: number
    pageSize?: number
}

/** GET /api/search/audit-logs 响应项 */
export interface AuditLogItem {
    auditId: string
    userid: string
    project: string
    permissionCode: string
    result: 'Allow' | 'Deny' | 'Error'
    reason: string
    createdAt: string
}

/** GET /api/search/permission-view Query 参数 */
export interface PermissionViewQuery {
    permissionCode?: string
    action?: string
    resourceType?: string
    keyword?: string
    status?: string
    page?: number
    pageSize?: number
}

/** GET /api/search/permission-view 响应项 */
export interface PermissionViewItem {
    permissionCode: string
    action: string
    resourceType: string
    title: string
}
