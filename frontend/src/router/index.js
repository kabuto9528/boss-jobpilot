import { createRouter, createWebHistory } from 'vue-router'
import AdminLayout from '../layouts/AdminLayout.vue'
import Dashboard from '../views/Dashboard.vue'
import Jobs from '../views/Jobs.vue'
import Applications from '../views/Applications.vue'
import Tasks from '../views/Tasks.vue'
import Settings from '../views/Settings.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AdminLayout,
      redirect: '/dashboard',
      children: [
        { path: 'dashboard', name: 'dashboard', component: Dashboard, meta: { title: '总览' } },
        { path: 'jobs', name: 'jobs', component: Jobs, meta: { title: '职位管理' } },
        { path: 'applications', name: 'applications', component: Applications, meta: { title: '投递记录' } },
        { path: 'tasks', name: 'tasks', component: Tasks, meta: { title: '任务中心' } },
        { path: 'settings', name: 'settings', component: Settings, meta: { title: '系统设置' } },
      ],
    },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

export default router
