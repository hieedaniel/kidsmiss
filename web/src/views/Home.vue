<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, frac, fmtDate } from '../api'

const router = useRouter()
const meta = ref(null)
const recent = ref([])
const loading = ref(true)

const stats = computed(() => meta.value?.stats || { total: 0, active: 0, mastered: 0, by_chapter: [] })
const due = computed(() => meta.value?.due || [])
const maxChapter = computed(() =>
  Math.max(1, ...(stats.value.by_chapter || []).map((c) => c.n))
)

onMounted(async () => {
  try {
    meta.value = await api.meta()
    const r = await api.items({ sort: 'new' })
    recent.value = (r.items || []).slice(0, 5)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page-head">
    <div>
      <h1 class="page-title">概览</h1>
      <p class="page-desc">错题不是收着看的，是要按节奏重做的</p>
    </div>
    <router-link to="/upload" class="btn btn-primary">＋ 拍照上传</router-link>
  </div>

  <div v-if="loading" class="empty">加载中…</div>

  <template v-else>
    <div class="stat-grid" style="margin-bottom: 16px">
      <div class="stat">
        <div class="k">题库总数</div>
        <div class="v">{{ stats.total }}<small>题</small></div>
      </div>
      <div class="stat accent">
        <div class="k">待掌握</div>
        <div class="v">{{ stats.active }}<small>题</small></div>
      </div>
      <div class="stat good">
        <div class="k">已掌握</div>
        <div class="v">{{ stats.mastered }}<small>题</small></div>
      </div>
      <div class="stat" :class="{ accent: due.length > 0 }">
        <div class="k">今天该复习</div>
        <div class="v">{{ due.length }}<small>题</small></div>
      </div>
    </div>

    <div class="grid-2" style="align-items: start">
      <div class="card card-pad">
        <div class="row" style="margin-bottom: 10px">
          <strong style="font-size: 14px">该复习了</strong>
          <span class="tag">{{ due.length }} 题</span>
          <div class="spacer"></div>
          <router-link to="/paper" class="small muted">去组卷 →</router-link>
        </div>
        <div v-if="!due.length" class="empty" style="padding: 24px">
          暂时没有到期的题，去拍照录新错题吧
        </div>
        <div v-else class="timeline">
          <div v-for="d in due" :key="d.item_id" class="tl-item bad">
            <div class="row">
              <router-link :to="`/items/${d.item_id}`" style="font-weight: 600">
                {{ d.item_id }}
              </router-link>
              <span class="tag">错 {{ d.attempts }} 次</span>
              <div class="spacer"></div>
              <span class="muted small">应复习 {{ d.due_at }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card card-pad">
        <div class="row" style="margin-bottom: 12px">
          <strong style="font-size: 14px">章节分布</strong>
        </div>
        <div v-if="!stats.by_chapter.length" class="empty" style="padding: 24px">
          还没有按章节归类
        </div>
        <div v-for="c in stats.by_chapter" :key="c.chapter" class="bar-row">
          <div class="bar-label">{{ c.chapter }}</div>
          <div class="bar-track">
            <div class="bar-fill" :style="{ width: (c.n / maxChapter) * 100 + '%' }"></div>
          </div>
          <div class="bar-num">{{ c.n }}</div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top: 16px">
      <div class="card-pad" style="padding-bottom: 6px">
        <strong style="font-size: 14px">最近录入</strong>
      </div>
      <div v-if="!recent.length" class="empty">还没有题目，去上传第一张卷子</div>
      <div
        v-for="it in recent"
        :key="it.id"
        class="item-row"
        style="cursor: pointer"
        @click="router.push(`/items/${it.id}`)"
      >
        <div class="item-main">
          <div class="item-stem" v-html="frac(it.stem)"></div>
          <div class="item-meta">
            <span class="tag chapter">{{ it.chapter || '未分类' }}</span>
            <span class="tag">★ {{ it.stars }}</span>
            <span class="muted small">{{ fmtDate(it.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </template>
</template>
