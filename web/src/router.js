import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'home', component: () => import('./views/Home.vue') },
  { path: '/upload', name: 'upload', component: () => import('./views/Upload.vue') },
  { path: '/items', name: 'items', component: () => import('./views/Items.vue') },
  { path: '/items/:id', name: 'item', component: () => import('./views/ItemDetail.vue') },
  { path: '/paper', name: 'paper', component: () => import('./views/Paper.vue') },
  { path: '/settings', name: 'settings', component: () => import('./views/Settings.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export default createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})
