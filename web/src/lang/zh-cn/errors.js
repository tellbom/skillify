// Shared "failed to load X" key (docs/frontend-i18n-and-auth-module-plan.md §4.1) + frontend
//自抛 error strings (§4.2 boundary — these are OURS to translate; backend-sourced `detail`/
// `resp.data.message` text is NOT translated here, it passes through verbatim per contract).
export default {
  loadFailed: '加载失败：{error}',
  keycloakNotConfigured: 'Keycloak 未在此部署中配置（VITE_KEYCLOAK_REALM_URL）',
  rbacLoginRejected: 'RBAC 登录被拒绝',
  rbacMenusFailed: '加载 RBAC 菜单失败',
  routesNotConfigured: 'Keycloak 未在此部署中配置（VITE_KEYCLOAK_REALM_URL），Skillify 无法加载其路由。',
  noRoutesForAccount: '未从 Rbac.Api 获取到任何 Skillify 路由 —— RBAC 中心尚未为您的账户注册 Skillify 菜单/权限。',
}
