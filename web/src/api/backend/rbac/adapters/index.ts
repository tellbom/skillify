/**
 * RBAC 适配器 / 枚举映射
 *
 * 移植自 E:\Web\flow\web\src\api\backend\rbac\adapters\index.ts（N4.2），逐字未改动，无
 * store 依赖。
 *
 * 职责：
 * 1. 旧前端枚举（BuildAdmin 风格）↔ 后端 RBAC 枚举 双向映射
 * 2. permissionCode 自动生成逻辑
 * 3. 状态显示文案 / 标签颜色
 */

import type { RecordStatus, RuleMenuType, RuleType } from '../types'

// ── RuleType 映射 ─────────────────────────────────────────────────────────────

/** 旧前端值 → RBAC 后端枚举 */
const LEGACY_TO_RULE_TYPE: Record<string, RuleType> = {
    menu_dir: 'MenuDir',
    menu: 'Menu',
    button: 'Button',
}

/** RBAC 后端枚举 → 旧前端值 */
const RULE_TYPE_TO_LEGACY: Record<RuleType, string> = {
    MenuDir: 'menu_dir',
    Menu: 'menu',
    Button: 'button',
}

/** 旧 BuildAdmin type 字符串 → RBAC RuleType */
export function toRuleType(legacy: string): RuleType {
    const mapped = LEGACY_TO_RULE_TYPE[legacy]
    if (!mapped) {
        console.warn(`[rbac/adapters] Unknown legacy rule type: "${legacy}", fallback to "Menu"`)
        return 'Menu'
    }
    return mapped
}

/** RBAC RuleType → 旧 BuildAdmin type 字符串 */
export function fromRuleType(type: RuleType): string {
    return RULE_TYPE_TO_LEGACY[type] ?? 'menu'
}

// ── RuleMenuType 映射 ─────────────────────────────────────────────────────────

const LEGACY_TO_MENU_TYPE: Record<string, RuleMenuType> = {
    tab: 'Tab',
    link: 'Link',
    iframe: 'Iframe',
}

const MENU_TYPE_TO_LEGACY: Record<RuleMenuType, string> = {
    Tab: 'tab',
    Link: 'link',
    Iframe: 'iframe',
}

export function toMenuType(legacy: string): RuleMenuType {
    const mapped = LEGACY_TO_MENU_TYPE[legacy]
    if (!mapped) {
        console.warn(`[rbac/adapters] Unknown legacy menu type: "${legacy}", fallback to "Tab"`)
        return 'Tab'
    }
    return mapped
}

export function fromMenuType(type: RuleMenuType): string {
    return MENU_TYPE_TO_LEGACY[type] ?? 'tab'
}

// ── RecordStatus 映射 ─────────────────────────────────────────────────────────

/**
 * 旧前端 1/0 或 true/false → RBAC RecordStatus
 * 兼容处理：string "1"/"0"、number 1/0、boolean true/false
 */
export function toRecordStatus(legacy: string | number | boolean): RecordStatus {
    if (legacy === 1 || legacy === '1' || legacy === true) return 'Active'
    if (legacy === 0 || legacy === '0' || legacy === false) return 'Disabled'
    // 已是 RBAC 格式时直通
    if (legacy === 'Active' || legacy === 'Disabled') return legacy as RecordStatus
    console.warn(`[rbac/adapters] Unknown status value: "${legacy}", fallback to "Disabled"`)
    return 'Disabled'
}

/** RBAC RecordStatus → 旧前端数字 */
export function fromRecordStatus(status: RecordStatus): number {
    return status === 'Active' ? 1 : 0
}

// ── Keepalive 映射 ────────────────────────────────────────────────────────────

/** 旧前端 1/0 → boolean */
export function toKeepalive(legacy: number | string | boolean): boolean {
    if (typeof legacy === 'boolean') return legacy
    return legacy === 1 || legacy === '1'
}

/** boolean → 旧前端 0/1 */
export function fromKeepalive(keepalive: boolean): number {
    return keepalive ? 1 : 0
}

// ── permissionCode 自动生成 ───────────────────────────────────────────────────

/**
 * 根据 ruleCode 和类型自动生成推荐的 permissionCode。
 *
 * 规则：
 * - MenuDir / Menu → `menu:${ruleCode}`
 * - Button         → `button:${ruleCode}`
 *
 * 允许前端用户手动覆盖，此函数仅用于填充默认值和表单提示。
 */
export function suggestPermissionCode(ruleCode: string, type: RuleType): string {
    if (!ruleCode) return ''
    if (type === 'Button') return `button:${ruleCode}`
    return `menu:${ruleCode}`
}

// ── 状态显示配置 ──────────────────────────────────────────────────────────────

export interface StatusDisplay {
    label: string
    tagType: 'success' | 'danger' | 'warning' | 'info'
}

const STATUS_DISPLAY_MAP: Record<RecordStatus, StatusDisplay> = {
    Active: { label: '启用', tagType: 'success' },
    Disabled: { label: '禁用', tagType: 'danger' },
}

export function getStatusDisplay(status: RecordStatus): StatusDisplay {
    return STATUS_DISPLAY_MAP[status] ?? { label: status, tagType: 'info' }
}

// ── RuleType 显示配置 ─────────────────────────────────────────────────────────

export interface RuleTypeDisplay {
    label: string
    tagType: 'primary' | 'success' | 'warning' | 'info'
}

const RULE_TYPE_DISPLAY_MAP: Record<RuleType, RuleTypeDisplay> = {
    MenuDir: { label: '目录', tagType: 'primary' },
    Menu: { label: '菜单', tagType: 'success' },
    Button: { label: '按钮', tagType: 'warning' },
}

export function getRuleTypeDisplay(type: RuleType): RuleTypeDisplay {
    return RULE_TYPE_DISPLAY_MAP[type] ?? { label: type, tagType: 'info' }
}

// ── isSuper 显示 ──────────────────────────────────────────────────────────────

export function getSuperDisplay(isSuper: boolean): { label: string; tagType: 'warning' | 'info' } {
    return isSuper
        ? { label: '超管', tagType: 'warning' }
        : { label: '普通', tagType: 'info' }
}

// ── 分页参数标准化 ────────────────────────────────────────────────────────────

/**
 * 将旧 baTable 分页格式标准化为 RBAC API 分页参数。
 */
export function normalizePageParams(page = 1, pageSize = 20) {
    return {
        page: Math.max(1, page),
        pageSize: Math.min(100, Math.max(1, pageSize)),
    }
}
