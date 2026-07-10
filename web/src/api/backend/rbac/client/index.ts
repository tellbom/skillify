/**
 * RBAC 专用 Axios 客户端
 *
 * 移植自 E:\Web\flow\web\src\api\backend\rbac\client\index.ts（N4.2，
 * docs/frontend-i18n-and-auth-module-plan.md D8）。与项目原有 api.js 完全隔离，独立实例、
 * 独立拦截器。
 *
 * 与 flow 版本的差异（均为有意为之，非移植遗漏）：
 * 1. Token 来源：flow 从其专属 `useAdminInfo` store 读取；此处改读 Skillify 的
 *    `useAuthStore().token`（即桥接 RBAC 前使用的同一枚 Keycloak token —— 与既有
 *    src/lib/rbacClient.js 的做法一致，见 authBootstrap.js 的 bridgeToRbac）。
 * 2. baseURL 解析：flow 的 getUrl() 始终返回 '/rbacServer'（连计算出的候选值都未使用，
 *    是其自身未完工的桩代码），生产环境下并不存在这个 dev-only 代理路径。此处改用
 *    Skillify 既有 src/lib/rbacClient.js 已验证过的判断：dev 走 `/rbacServer` 代理，
 *    生产读 `VITE_RBAC_BASE_URL`。
 * 3. 401 处理：不调用 `auth.clear()` —— Skillify 的 Keycloak token 生命周期由
 *    lib/keycloak.js 的刷新轮询统一管理（M-E），RBAC 侧 401 不代表 Keycloak 会话本身失效，
 *    仅导航到登录页，不在此处清空全局鉴权状态。
 *
 * 成功条件：code === 0。失败时抛出 RbacApiError，携带 code + msg，供页面 catch 处理。
 */

import axios, {
    type AxiosInstance,
    type AxiosRequestConfig,
    type AxiosResponse,
    type InternalAxiosRequestConfig,
} from 'axios'
import { ElNotification } from 'element-plus'
import { useAuthStore } from '/@/stores/auth.js'

// ── 项目常量 ──────────────────────────────────────────────────────────────────

export const RBAC_PROJECT: string =
    (import.meta.env.VITE_RBAC_PROJECT as string) || 'skillify'

// ── 统一响应类型 ───────────────────────────────────────────────────────────────

/** RBAC 统一响应包装体 */
export interface RbacResponse<T = unknown> {
    code: number
    msg: string
    data: T
    time: number
}

/** 分页数据体 */
export interface PagedData<T> {
    list: T[]
    total: number
}

/** 分页查询基础参数 */
export interface PagedQuery {
    page?: number
    pageSize?: number
    keyword?: string
    status?: 'Active' | 'Disabled'
}

// ── 自定义错误类 ───────────────────────────────────────────────────────────────

export class RbacApiError extends Error {
    constructor(
        public readonly code: number,
        public readonly msg: string
    ) {
        super(msg)
        this.name = 'RbacApiError'
    }
}

// ── HTTP 状态码错误信息映射 ────────────────────────────────────────────────────

const HTTP_ERROR_MESSAGES: Record<number, string> = {
    400: '请求参数错误',
    401: '身份验证失败，请重新登录',
    403: '无权限执行此操作',
    404: '请求的资源不存在',
    408: '请求超时',
    500: '服务器内部错误',
    502: '网关错误',
    503: '服务暂不可用',
    504: '网关超时',
}

// ── 业务错误码映射 ─────────────────────────────────────────────────────────────

const RBAC_BUSINESS_CODES: Record<number, string> = {
    40001: '参数校验失败',
    40009: '业务前置条件不满足',
    40100: 'JWT 用户信息缺失，请重新登录',
    40300: '无权限执行此操作',
    40400: '资源不存在',
    50000: '运维操作部分或全部失败',
}

// ── 重复请求取消 ───────────────────────────────────────────────────────────────

const pendingMap = new Map<string, AbortController>()

function getPendingKey(config: AxiosRequestConfig): string {
    return [
        config.url ?? '',
        config.method ?? '',
        JSON.stringify(config.params ?? {}),
        typeof config.data === 'string' ? config.data : JSON.stringify(config.data ?? {}),
    ].join('::')
}

function addPending(config: InternalAxiosRequestConfig): void {
    const key = getPendingKey(config)
    if (pendingMap.has(key)) {
        pendingMap.get(key)!.abort()
        pendingMap.delete(key)
    }
    const controller = new AbortController()
    config.signal = controller.signal
    pendingMap.set(key, controller)
}

function removePending(config: AxiosRequestConfig): void {
    const key = getPendingKey(config)
    pendingMap.delete(key)
}

function getUrl(): string {
    if (import.meta.env.DEV) return '/rbacServer'
    return (import.meta.env.VITE_RBAC_BASE_URL as string) || ''
}

/** Whether RBAC is reachable in this deployment (dev proxy always counts; prod needs the
 * base URL configured). Mirrors the old src/lib/rbacClient.js's isRbacConfigured(). */
export function isRbacConfigured(): boolean {
    return Boolean(getUrl())
}

// ── 创建 RBAC 专用实例 ────────────────────────────────────────────────────────

function createRbacAxios(): AxiosInstance {
    const instance = axios.create({
        baseURL: getUrl(),
        timeout: 15_000,
        headers: {
            'Content-Type': 'application/json',
        },
        responseType: 'json',
    })

    // ── 请求拦截器 ─────────────────────────────────────────────────────────────
    instance.interceptors.request.use(
        (config: InternalAxiosRequestConfig) => {
            // 取消重复请求
            addPending(config)

            // 注入鉴权头：从 Pinia store 实时读取，避免闭包过期 token
            const auth = useAuthStore()
            const token = auth.token ?? ''
            if (token) {
                config.headers['Authorization'] = `Bearer ${token}`
            }
            config.headers['X-Project'] = RBAC_PROJECT

            return config
        },
        (error) => Promise.reject(error)
    )

    // ── 响应拦截器 ─────────────────────────────────────────────────────────────
    instance.interceptors.response.use(
        (response: AxiosResponse<RbacResponse>) => {
            removePending(response.config)

            const { code, msg, data } = response.data

            // RBAC 成功条件：code === 0
            if (code === 0) {
                return data as any
            }

            // 业务错误：code !== 0
            const displayMsg =
                msg ||
                RBAC_BUSINESS_CODES[code] ||
                `业务错误 (code: ${code})`

            ElNotification({
                type: 'error',
                title: '操作失败',
                message: displayMsg,
                zIndex: 9999,
                duration: 4500,
            })

            return Promise.reject(new RbacApiError(code, displayMsg))
        },
        (error) => {
            if (error.config) removePending(error.config)

            // AbortController 主动取消的请求，静默处理
            if (axios.isCancel(error) || error.name === 'AbortError') {
                return Promise.reject(error)
            }

            // HTTP 层面错误
            let message = '网络异常，请稍后重试'

            if (error.response) {
                const status: number = error.response.status
                message = HTTP_ERROR_MESSAGES[status] ?? `HTTP ${status} 错误`

                // 401：RBAC 侧鉴权失败，跳转登录（不清空 Keycloak 会话状态，见文件头说明）
                if (status === 401) {
                    setTimeout(() => {
                        import('/@/router/index.js').then(({ default: router }) => {
                            if (router.currentRoute.value.name !== 'login') {
                                router.push({ name: 'login' })
                            }
                        })
                    }, 0)
                }
            } else if (error.message?.includes('timeout')) {
                message = '请求超时，请检查网络连接'
            } else if (!window.navigator.onLine) {
                message = '网络已断开，请检查网络连接'
            }

            ElNotification({
                type: 'error',
                title: '请求失败',
                message,
                zIndex: 9999,
                duration: 4500,
            })

            return Promise.reject(error)
        }
    )

    return instance
}

// ── 导出单例 ──────────────────────────────────────────────────────────────────

export const rbacClient = createRbacAxios()
