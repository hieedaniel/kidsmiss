<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from './api'

const route = useRoute()
const dueCount = ref(0)

const navs = [
  { to: '/', ico: '▦', label: '概览' },
  { to: '/batch', ico: '⊞', label: '批量入库' },
  { to: '/upload', ico: '＋', label: '单张录入' },
  { to: '/items', ico: '☰', label: '错题库' },
  { to: '/paper', ico: '⎙', label: '组卷' },
  { to: '/settings', ico: '⚙', label: '设置' },
]

function isActive(to) {
  if (to === '/') return route.path === '/'
  return route.path.startsWith(to)
}

onMounted(async () => {
  try {
    const m = await api.meta()
    dueCount.value = (m.due || []).length
  } catch {
    /* 后端没起来时静默 */
  }
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">错</div>
        <div>
          <div class="brand-name">错题集</div>
          <div class="brand-sub">六年级上 · 数学</div>
        </div>
      </div>

      <router-link
        v-for="n in navs"
        :key="n.to"
        :to="n.to"
        class="nav-item"
        :class="{ active: isActive(n.to) }"
      >
        <span class="ico">{{ n.ico }}</span>
        <span>{{ n.label }}</span>
        <span v-if="n.to === '/' && dueCount" class="nav-badge">{{ dueCount }}</span>
      </router-link>

      <div class="sidebar-foot">本地自用 · 数据存在 server/data</div>
    </aside>

    <main class="main">
      <router-view />
    </main>

    <nav class="tabbar">
      <router-link
        v-for="n in navs"
        :key="n.to"
        :to="n.to"
        class="nav-item"
        :class="{ active: isActive(n.to) }"
      >
        <span class="ico">{{ n.ico }}</span>
        <span>{{ n.label }}</span>
      </router-link>
    </nav>
  </div>
</template>
