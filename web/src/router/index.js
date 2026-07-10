import { createRouter, createWebHistory } from 'vue-router'
import { installAuthGuard } from './guard.js'
import { LAYOUT_ROUTE_NAME } from './constants.js'

// Only framework-level static routes live here (user decision 2026-07-10, aligning with
// E:\Web\flow\web): login, the error pages, the root layout shell, and the catch-all. Every
// Skillify BUSINESS route is registered at runtime from Rbac.Api's /api/admin/index — see
// router/dynamicRoutes.js and router/guard.js. The four previously-hardcoded business routes
// (skills / skill-detail / upload / leaderboard) are intentionally gone, with no fallback.
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/Login.vue'),
    },
    {
      path: '/401',
      name: 'unauthorized',
      component: () => import('../views/error/Forbidden.vue'),
    },
    {
      path: '/403',
      name: 'tokenExpired',
      component: () => import('../views/error/TokenExpired.vue'),
    },
    {
      path: '/404',
      name: 'notFound',
      component: () => import('../views/error/NotFound.vue'),
    },
    {
      // Root layout shell. Dynamic business routes are addRoute()'d as children under this
      // route's name (LAYOUT_ROUTE_NAME) at runtime.
      path: '/',
      name: LAYOUT_ROUTE_NAME,
      component: () => import('../layouts/AppLayout.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'catchAll',
      redirect: '/404',
    },
  ],
})

installAuthGuard(router)

export default router
