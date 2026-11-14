<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, fmtDate, frac, STATUS_TEXT } from '../api'

const router = useRouter()
const items = ref([])
const chapters = ref([])
const loading = ref(true)
const error = ref('')
const busyId = ref('')

const filters = reactive({
  chapter: '',
  status: '',
  stars: '',
  q: '',
  sort: 'new',
})

const grouped = computed(() => {
  const out = {}
  items.value.forEach((it) => {
    const k = it.chapter || '未分类'
    ;(out[k] = out[k] || []).push(it)
  })
  return out
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const r = await api.items({ ...filters })
    items.value = r.items || []
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    const m = await api.meta()
    chapters.value = m.chapters || []
  } catch (e) {
    error.value = e.message
  }
  await load()
})

watch(() => ({ ...filters }), load, { deep: true })

async function mark(it, result) {
  busyId.value = it.id
  try {
    const r = await api.attempt(it.id, result)
    it.stars = r.item.stars
    it.status = r.item.status
    it.mastery = r.mastery
  } catch (e) {
    error.value = e.message
  } finally {
    busyId.value = ''
  }
}

async function remove(it) {
  if (!confirm(`删除「${it.id}」？重做记录也会一起删掉。`)) return
  try {
    await api.deleteItem(it.id)
    items.value = items.value.filter((x) => x.id !== it.id)
  } catch (e) {
    error.value = e.message
  }
}

function buildWith(list) {
  const ids = list.map((x) => x.id).join(',')
  router.push(`/paper?ids=${ids}`)
}
</script>

<template>
  <div class="page-head">
    <div>
      <h1 class="page-title">错题库</h1>
      <p class="page-desc">共 {{ items.length }} 题 · 按章节分组查看</p>
    </div>
    <div class="row">
      <button class="btn" @click="buildWith(items)">用当前筛选组卷</button>
      <router-link to="/upload" class="btn btn-primary">＋ 新增</router-link>
    </div>
  </div>

  <div v-if="error" class="alert alert-error">{{ error }}</div>

  <div class="card card-pad" style="margin-bottom: 14px">
    <div class="row filter-row">
      <select v-model="filters.chapter" style="width: 140px">
        <option value="">全部章节</option>
        <option v-for="c in chapters" :key="c" :value="c">{{ c }}</option>
      </select>
      <select v-model="filters.status" style="width: 130px">
        <option value="">全部状态</option>
        <option value="wrong">错题</option>
        <option value="unverified">待核对</option>
        <option value="format">过程不规范</option>
        <option value="mastered">已掌握</option>
      </select>
      <select v-model="filters.stars" style="width: 110px">
        <option value="">全部星级</option>
        <option value="1">★ 及以上</option>
        <option value="2">★★ 及以上</option>
        <option value="3">★★★</option>
      </select>
      <select v-model="filters.sort" style="width: 130px">
        <option value="new">最新录入</option>
        <option value="old">最早录入</option>
        <option value="stars">错得多优先</option>
        <option value="chapter">按章节</option>
      </select>
      <input v-model="filters.q" type="text" placeholder="搜题干 / 知识点" style="flex: 1; min-width: 140px" />
    </div>
  </div>

  <div v-if="loading" class="empty">加载中…</div>
  <div v-else-if="!items.length" class="card empty">
    没有符合条件的题。换个筛选条件，或者去 <router-link to="/upload" style="color: var(--primary)">上传</router-link> 一道。
  </div>

  <template v-else>
    <div v-for="(list, ch) in grouped" :key="ch" class="card" style="margin-bottom: 14px">
      <div class="card-pad" style="padding: 10px 16px; border-bottom: 1px solid var(--line)">
        <div class="row">
          <strong style="font-size: 13.5px">{{ ch }}</strong>
          <span class="tag">{{ list.length }} 题</span>
          <div class="spacer"></div>
          <button class="btn btn-sm" @click="buildWith(list)">本章组卷</button>
        </div>
      </div>

      <div v-for="it in list" :key="it.id" class="item-row">
        <img
          v-if="it.figures && it.figures.length"
          class="item-thumb"
          :src="`/uploads/${String(it.figures[0].src).replace(/^scans\//, '')}`"
          alt=""
          loading="lazy"
        />
        <div class="item-main">
          <div class="item-stem" v-html="frac(it.stem)"></div>
          <div class="item-meta">
            <span class="tag" :class="`st-${it.status}`">{{ STATUS_TEXT[it.status] || it.status }}</span>
            <span class="stars">{{ '★'.repeat(it.stars || 1) }}</span>
            <span class="tag">{{ it.qtype === 'solve' ? '解答' : it.qtype === 'fill' ? '填空' : '选择' }}</span>
            <span v-if="it.mastery && it.mastery.attempts" class="muted small">
              重做 {{ it.mastery.attempts }} 次
              <template v-if="it.mastery.overdue"> · 该复习了</template>
            </span>
            <span class="muted small">{{ fmtDate(it.created_at) }}</span>
          </div>
        </div>
        <div class="row actions">
          <button
            class="btn btn-sm"
            :disabled="busyId === it.id"
            title="重做对了"
            @click="mark(it, 'correct')"
          >✓ 对</button>
          <button
            class="btn btn-sm btn-danger"
            :disabled="busyId === it.id"
            title="又错了"
            @click="mark(it, 'wrong')"
          >✗ 错</button>
          <button class="btn btn-sm" @click="router.push(`/items/${it.id}`)">详情</button>
          <button class="btn btn-sm btn-danger" @click="remove(it)">删</button>
        </div>
      </div>
    </div>
  </template>
</template>
