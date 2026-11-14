<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, frac, fmtDate } from '../api'

const route = useRoute()
const items = ref([])
const chapters = ref([])
const picked = ref(new Set())
const papers = ref([])
const loading = ref(true)
const building = ref(false)
const error = ref('')
const result = ref(null)

const filters = reactive({ chapter: '', status: '', stars: '', q: '' })
const opts = reactive({ round: 1, mode: 'blank', title: '' })

const pickedItems = computed(() => items.value.filter((i) => picked.value.has(i.id)))
const totalPoints = computed(() =>
  pickedItems.value.reduce((s, i) => s + (i.points || 0), 0)
)

async function loadItems() {
  loading.value = true
  try {
    const r = await api.items({ ...filters })
    items.value = r.items || []
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function loadPapers() {
  try {
    const r = await api.papers()
    papers.value = r.papers || []
  } catch { /* ignore */ }
}

onMounted(async () => {
  if (route.query.ids) {
    String(route.query.ids).split(',').filter(Boolean).forEach((id) => picked.value.add(id))
  }
  try {
    const m = await api.meta()
    chapters.value = m.chapters || []
  } catch (e) {
    error.value = e.message
  }
  await Promise.all([loadItems(), loadPapers()])
})

function toggle(id) {
  if (picked.value.has(id)) picked.value.delete(id)
  else picked.value.add(id)
}

const allPicked = computed(() =>
  items.value.length > 0 && items.value.every((i) => picked.value.has(i.id))
)

function toggleAll() {
  if (allPicked.value) picked.value.clear()
  else items.value.forEach((i) => picked.value.add(i.id))
}

async function build() {
  if (!pickedItems.value.length) return (error.value = '先勾选要出卷的题')
  building.value = true
  error.value = ''
  result.value = null
  try {
    const ids = pickedItems.value.map((i) => i.id)
    const modes = opts.mode === 'both' ? ['blank', 'review'] : [opts.mode]
    const out = []
    for (const m of modes) {
      const res = await api.buildPaper({
        item_ids: ids,
        mode: m,
        round: Number(opts.round) || 1,
        title: opts.title || undefined,
      })
      out.push({ ...res, mode: m })
    }
    result.value = out
    await loadPapers()
  } catch (e) {
    error.value = e.message
  } finally {
    building.value = false
  }
}
</script>

<template>
  <div class="page-head">
    <div>
      <h1 class="page-title">组卷</h1>
      <p class="page-desc">筛题 → 勾选 → 生成 A4 卷子（空白卷给孩子，复盘页自己看）</p>
    </div>
  </div>

  <div v-if="error" class="alert alert-error">{{ error }}</div>

  <div v-if="result" class="alert alert-ok">
    生成成功：
    <a
      v-for="r in result"
      :key="r.id"
      :href="`/api/papers/${r.id}/file`"
      target="_blank"
      style="margin-right: 14px; font-weight: 600; text-decoration: underline"
    >
      {{ r.id }}. {{ r.mode === 'review' ? '复盘页' : '空白卷' }} PDF
    </a>
  </div>

  <div class="grid-2" style="align-items: start">
    <div class="card">
      <div class="card-pad" style="border-bottom: 1px solid var(--line)">
        <div class="row">
          <select v-model="filters.chapter" style="width: 130px" @change="loadItems">
            <option value="">全部章节</option>
            <option v-for="c in chapters" :key="c" :value="c">{{ c }}</option>
          </select>
          <select v-model="filters.status" style="width: 120px" @change="loadItems">
            <option value="">全部状态</option>
            <option value="wrong">错题</option>
            <option value="unverified">待核对</option>
            <option value="mastered">已掌握</option>
          </select>
          <select v-model="filters.stars" style="width: 110px" @change="loadItems">
            <option value="">不限星级</option>
            <option value="2">★★ 及以上</option>
            <option value="3">★★★</option>
          </select>
          <div class="spacer"></div>
          <button class="btn btn-sm" @click="toggleAll">
            {{ allPicked ? '取消全选' : '全选' }}
          </button>
        </div>
      </div>

      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!items.length" class="empty">没有符合条件的题</div>
      <div
        v-for="it in items"
        :key="it.id"
        class="item-row"
        style="cursor: pointer"
        @click="toggle(it.id)"
      >
        <input
          type="checkbox"
          :checked="picked.has(it.id)"
          style="width: auto; margin-top: 4px"
          @click.stop
          @change="toggle(it.id)"
        />
        <div class="item-main">
          <div class="item-stem" v-html="frac(it.stem)"></div>
          <div class="item-meta">
            <span class="tag chapter">{{ it.chapter || '未分类' }}</span>
            <span class="stars">{{ '★'.repeat(it.stars || 1) }}</span>
            <span class="muted small">{{ it.id }}</span>
          </div>
        </div>
      </div>
    </div>

    <div>
      <div class="card card-pad" style="margin-bottom: 14px">
        <div class="row" style="margin-bottom: 10px">
          <strong style="font-size: 14px">出卷设置</strong>
          <div class="spacer"></div>
          <span class="tag">已选 {{ pickedItems.length }} 题 · {{ totalPoints }} 分</span>
        </div>

        <div class="grid-2">
          <label class="field">
            <span>轮次</span>
            <select v-model="opts.round">
              <option :value="1">第 1 轮</option>
              <option :value="2">第 2 轮</option>
              <option :value="3">第 3 轮</option>
            </select>
          </label>
          <label class="field">
            <span>生成什么</span>
            <select v-model="opts.mode">
              <option value="blank">只有空白卷</option>
              <option value="review">只有复盘页</option>
              <option value="both">两份都要</option>
            </select>
          </label>
        </div>

        <label class="field">
          <span>卷子标题（不填自动生成）</span>
          <input v-model="opts.title" type="text" :placeholder="`错题重做卷（第 ${opts.round} 轮）`" />
        </label>

        <button class="btn btn-primary btn-block" :disabled="building" @click="build">
          <span v-if="building" class="spinner"></span>
          {{ building ? '生成中…' : '生成卷子' }}
        </button>
      </div>

      <div class="card card-pad">
        <strong style="font-size: 14px">历史卷子</strong>
        <div v-if="!papers.length" class="empty" style="padding: 18px">还没生成过</div>
        <div v-for="p in papers.slice(0, 12)" :key="p.id" class="small" style="padding: 7px 0; border-bottom: 1px solid var(--line)">
          <div class="row">
            <a :href="`/api/papers/${p.id}/file`" target="_blank" style="color: var(--primary); font-weight: 600">
              #{{ p.id }} {{ p.mode === 'blank' ? '空白卷' : '复盘页' }}
            </a>
            <span class="muted">{{ p.count }} 题</span>
            <div class="spacer"></div>
            <span class="muted">{{ fmtDate(p.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
