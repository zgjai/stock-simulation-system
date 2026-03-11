import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/setup'
  },
  {
    path: '/setup',
    name: 'Setup',
    component: () => import('@/views/BacktestSetup.vue'),
    meta: { title: '回测设置' }
  },
  {
    path: '/backtest',
    name: 'Backtest',
    component: () => import('@/views/BacktestMain.vue'),
    meta: { title: '回测进行中' }
  },
  {
    path: '/history',
    name: 'History',
    component: () => import('@/views/BacktestHistory.vue'),
    meta: { title: '历史记录' }
  },
  {
    path: '/history/:sessionId',
    name: 'HistoryDetail',
    component: () => import('@/views/HistoryDetail.vue'),
    meta: { title: '回测详情' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  document.title = (to.meta.title as string) || 'A股主观回测系统'
  next()
})

export default router
