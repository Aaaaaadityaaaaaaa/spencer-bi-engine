import { createRouter, createWebHistory } from 'vue-router'
import TableView from '../views/TableView.vue'
import ModelView from '../views/ModelView.vue'

import CanvasView from '../views/CanvasView.vue'
import QueryEngineView from '../views/QueryEngineView.vue'
import AuthView from '../views/AuthView.vue'
import SettingsView from '../views/SettingsView.vue'
import { useAuth } from '../composables/useAuth'

// Type-only augmentation so `route.meta.title` is typed everywhere.
// (Interfaces emit no runtime code, so this is safe under `erasableSyntaxOnly`.)
declare module 'vue-router' {
  interface RouteMeta {
    title: string
    // Public routes render without auth + without the app shell (TASK-027). Absent =
    // protected: the guard bounces unauthenticated visitors to /login.
    public?: boolean
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [

    {
      path: '/model',
      name: 'model',
      component: ModelView,
      meta: { title: 'Spencer BI | Model', requiresAuth: true }
    },
    { path: '/', redirect: '/table' },
    { path: '/login', name: 'login', component: AuthView, meta: { title: 'Sign in', public: true } },
    { path: '/table', name: 'table', component: TableView, meta: { title: 'Table' } },
    { path: '/canvas', name: 'canvas', component: CanvasView, meta: { title: 'Canvas' } },
    { path: '/query', name: 'query', component: QueryEngineView, meta: { title: 'Query Engine' } },
    { path: '/settings', name: 'settings', component: SettingsView, meta: { title: 'Settings', requiresAuth: true } },
  ],
})

// Auth guard (TASK-027). main.ts calls useAuth().loadFromStorage() BEFORE mount, so the
// token is already rehydrated when this runs on the first navigation.
//  - unauthenticated + protected route -> /login?redirect=<intended path>
//  - authenticated + on /login         -> /table (nothing to sign into)
router.beforeEach((to) => {
  const { isAuthenticated } = useAuth()
  if (!to.meta.public && !isAuthenticated.value) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && isAuthenticated.value) {
    return { path: '/table' }
  }
  return true
})

export default router
