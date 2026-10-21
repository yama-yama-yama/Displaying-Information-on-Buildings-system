import { createRouter, createWebHistory } from 'vue-router'
import HomeContent from '../components/HomeContent.vue'
import DebugView from '../views/DebugView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeContent,
    },
    {
      path: '/debug',
      name: 'debug',
      component: DebugView,
    },
  ],
})

export default router
