import { createRouter, createWebHistory } from 'vue-router'
import TableView from '../views/TableView.vue'
import CanvasView from '../views/CanvasView.vue'
import QueryEngineView from '../views/QueryEngineView.vue'

// Type-only augmentation so `route.meta.title` is typed everywhere.
// (Interfaces emit no runtime code, so this is safe under `erasableSyntaxOnly`.)
declare module 'vue-router' {
  interface RouteMeta {
    title: string
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/table' },
    { path: '/table', name: 'table', component: TableView, meta: { title: 'Table' } },
    { path: '/canvas', name: 'canvas', component: CanvasView, meta: { title: 'Canvas' } },
    { path: '/query', name: 'query', component: QueryEngineView, meta: { title: 'Query Engine' } },
  ],
})

export default router
