<script setup>
import { computed, onUnmounted, reactive, ref } from 'vue'
import { api } from '../api'

const fileInput = ref(null)
const error = ref('')
const pics = ref([])           // 本地队列：{ key, name, thumb, file, state, stage, count, figs, dups, error }
const task = ref(null)         // 后端任务快照
const starting = ref(false)
const dragOver = ref(false)
const opt = reactive({ exam: '批量导入', hint: '' })

const MAX_FILES = 30
let timer = null
let seq = 0

const canStart = computed(
  () => pics.value.length > 0 && pics.value.every((p) => p.file) && !task.value
)
const busy = computed(() => pics.value.some((p) => p.state === 'uploading'))
const progress = computed(() => {
  const t = task.value
  if (!t) return 0
  return Math.round((t.done / Math.max(1, t.total)) * 100)
})
const summary = computed(() => {
  const t = task.value
  if (!t) return ''
  const parts = [`入库 ${t.saved} 题`]
  if (t.unverified) parts.push(`其中 ${t.unverified} 题待你核对`)
  if (t.skipped) parts.push(`跳过重复 ${t.skipped} 题`)
  if (t.failed) parts.push(`${t.failed} 张图失败`)
  return parts.join('，')
})

/* ---------------- 选图与上传 ---------------- */
function pick() {
  fileInput.value?.click()
}

function addFiles(list) {
  error.value = ''
  const room = MAX_FILES - pics.value.length
  if (room <= 0) return (error.value = `一次最多 ${MAX_FILES} 张，先处理完这批`)
  const files = Array.from(list || []).filter((f) => f.type.startsWith('image/'))
  if (!files.length) return (error.value = '只支持图片文件')
  for (const f of files.slice(0, room)) {
    const row = reactive({
      key: ++seq, name: f.name, thumb: '', file: '',
      state: 'uploading', stage: '上传中', count: 0, figs: [], dups: [], error: '',
    })
    pics.value.push(row)
    uploadOne(f, row)
  }
}

async function uploadOne(f, row) {
  try {
    const dataUrl = await new Promise((res, rej) => {
      const r = new FileReader()
      r.onload = () => res(r.result)
      r.onerror = rej
      r.readAsDataURL(f)
    })
    const r = await api.upload(f.name, dataUrl)
    row.thumb = r.thumb
    row.file = r.file
    row.state = 'ready'
    row.stage = `${r.width}×${r.height}`
  } catch (e) {
    row.state = 'failed'
    row.stage = '上传失败'
    row.error = e.message
    error.value = e.message
  }
}

function onFile(e) {
  addFiles(e.target.files)
  e.target.value = ''
}

function onDrop(e) {
  dragOver.value = false
  addFiles(e.dataTransfer?.files)
}

function removeAt(i) {
  pics.value.splice(i, 1)
}

function reset() {
  stopPoll()
  pics.value = []
  task.value = null
  error.value = ''
}

/* ---------------- 启动批量任务 ---------------- */
async function start() {
  if (!canStart.value) return
  error.value = ''
  starting.value = true
  try {
    const { job } = await api.batchStart({
      files: pics.value.map((p) => p.file),
      exam: opt.exam || '批量导入',
      hint: opt.hint,
    })
    task.value = job
    pics.value.forEach((p) => {
      p.state = 'pending'
      p.stage = '排队中'
    })
    poll(job.id)
  } catch (e) {
    error.value = e.message
  } finally {
    starting.value = false
  }
}

async function poll(id) {
  stopPoll()
  try {
    const { job } = await api.batchJob(id)
    task.value = job
    job.files.forEach((f, i) => {
      const p = pics.value[i]
      if (!p) return
      p.state = f.status
      p.stage = f.stage
      p.count = f.count
      p.figs = f.figs || []
      p.dups = f.dups || []
      p.error = f.error
      p.savedIds = f.saved_ids || []
    })
    if (job.status !== 'done') timer = setTimeout(() => poll(id), 1200)
  } catch (e) {
    error.value = e.message
  }
}

function stopPoll() {
  if (timer) clearTimeout(timer)
  timer = null
}

onUnmounted(stopPoll)

/* ---------------- 展示 ---------------- */
const STATE_TEXT = {
  uploading: '上传中',
  ready: '待识别',
  pending: '排队中',
  running: '识别中',
  done: '完成',
  failed: '失败',
}
function stateClass(s) {
  if (s === 'done') return 'tag st-mastered'
  if (s === 'failed') return 'tag st-wrong'
  if (s === 'running') return 'tag st-unverified'
  return 'tag chapter'
}

const figIds = computed(() => {
  const t = task.value
  if (!t) return []
  return t.files.flatMap((f) => f.figs || [])
})
</script>

<template>
  <div class="page-head">
    <div>
      <h1 class="page-title">批量入库</h1>
      <p class="page-desc">整页拍下来一次传多张，AI 挑出错题、自动去重、直接进库</p>
    </div>
    <div class="row">
      <router-link to="/upload" class="btn">单张精细录入</router-link>
      <button v-if="pics.length" class="btn" @click="reset">重来</button>
    </div>
  </div>

  <div v-if="error" class="alert alert-error">
    {{ error }}
    <router-link v-if="error.includes('Key')" to="/settings" style="margin-left: 6px">去设置</router-link>
  </div>

  <!-- 选图 -->
  <div class="card card-pad" style="margin-bottom: 14px">
    <input ref="fileInput" type="file" accept="image/*" multiple hidden @change="onFile" />

    <div
      v-if="!pics.length"
      class="dropzone"
      :class="{ over: dragOver }"
      @click="pick"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
    >
      <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
           style="color: #9aa39c" aria-hidden="true">
        <path d="M4 17V7a2 2 0 0 1 2-2h3l1.2-1.6A1.6 1.6 0 0 1 11.5 2.7h1A1.6 1.6 0 0 1 13.8 3.4L15 5h3a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
        <path d="M9 5h6" />
        <circle cx="12" cy="12" r="3.2" />
        <path d="M18 19.5h4M20 17.5v4" />
      </svg>
      <div style="font-weight: 600; margin-top: 8px">点击选择，或把照片拖进来</div>
      <div class="small muted" style="margin-top: 4px">
        可一次选多张（最多 30 张）· 每张可以是一整页试卷 · 正上方俯拍，四角入框
      </div>
    </div>

    <template v-else>
      <div class="pile">
        <div v-for="(p, i) in pics" :key="p.key" class="pile-item">
          <img v-if="p.thumb" :src="p.thumb" alt="" />
          <div v-else class="pile-ph">
            <span v-if="p.state === 'uploading'" class="spinner"></span>
            <span v-else class="small muted">无预览</span>
          </div>
          <button v-if="!task" class="pile-x" title="移除" @click="removeAt(i)">×</button>
          <div class="pile-foot">
            <span :class="stateClass(p.state)">{{ STATE_TEXT[p.state] || p.state }}</span>
            <span v-if="p.count" class="small muted">{{ p.count }} 题</span>
          </div>
          <div v-if="p.dups.length" class="small muted pile-tip">跳过重复 {{ p.dups.length }}</div>
          <div
            v-else-if="p.stage && !['ready', 'pending', 'running'].includes(p.state)"
            class="small muted pile-tip"
          >{{ p.stage }}</div>
          <div v-if="p.error" class="small pile-err">{{ p.error }}</div>
        </div>
      </div>

      <div v-if="!task" class="row" style="margin-top: 12px">
        <button class="btn btn-primary" :disabled="!canStart || starting" @click="start">
          <span v-if="starting" class="spinner"></span>
          {{ starting ? '启动中…' : `开始批量入库（${pics.length} 张）` }}
        </button>
        <button class="btn" :disabled="busy" @click="pick">继续添加</button>
        <span v-if="busy" class="small muted">正在上传…</span>
      </div>

      <details v-if="!task" style="margin-top: 10px">
        <summary class="small muted" style="cursor: pointer">这次卷子叫什么、有什么要注意的（可选）</summary>
        <div class="grid-2" style="margin-top: 10px">
          <label class="field">
            <span>来源名称（记在每道题上）</span>
            <input v-model="opt.exam" type="text" placeholder="期中卷 / 第三单元测" />
          </label>
          <label class="field">
            <span>补充提示（喂给模型）</span>
            <input v-model="opt.hint" type="text" placeholder="六年级上册期末，只收打叉的题" />
          </label>
        </div>
      </details>
    </template>
  </div>

  <!-- 进度 -->
  <div v-if="task" class="card card-pad">
    <div class="row" style="justify-content: space-between; margin-bottom: 10px">
      <div style="font-weight: 600">
        {{ task.status === 'done' ? '处理完成' : '正在识别…' }}
      </div>
      <div class="small muted">{{ task.done }} / {{ task.total }} 张</div>
    </div>
    <div class="bar-track" style="margin-bottom: 12px">
      <div class="bar-fill" :style="{ width: progress + '%' }"></div>
    </div>

    <div v-if="task.status === 'done'" class="alert alert-ok">
      本次{{ summary }}<template v-if="task.items">，识别出 {{ task.items }} 道错题</template>。
      <template v-if="task.skipped">重复的题没再入库，避免题库里出现同一道题两遍。</template>
      <template v-if="task.unverified">
        标了「待核对」的，是答案和孩子的笔迹一致、或模型没算出答案的题，需要你瞄一眼再决定留不留。
      </template>
    </div>

    <div v-if="figIds.length" class="alert alert-warn">
      有 {{ figIds.length }} 道题带图形，图形还没贴进卷子。点题号去详情页框一下原图，组卷时才会印出来：
      <span class="row" style="display: inline-flex; gap: 6px; flex-wrap: wrap; margin-top: 4px">
        <router-link v-for="id in figIds" :key="id" :to="`/items/${id}`" class="btn btn-sm">{{ id }}</router-link>
      </span>
    </div>

    <div class="row" style="margin-top: 12px">
      <router-link to="/items" class="btn btn-primary">去错题库核对</router-link>
      <router-link to="/paper" class="btn">按章节组卷</router-link>
      <button class="btn" @click="reset">再传一批</button>
    </div>
  </div>
</template>

<style scoped>
.dropzone.over {
  border-color: var(--primary);
  background: var(--primary-weak);
}
.pile {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: 10px;
}
.pile-item {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface-2);
  min-width: 0;
}
.pile-item img {
  display: block;
  width: 100%;
  height: 104px;
  object-fit: cover;
  background: #fff;
}
.pile-ph {
  height: 104px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pile-x {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 22px;
  height: 22px;
  line-height: 1;
  border: 0;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 15px;
  cursor: pointer;
  padding: 0;
}
.pile-x:hover {
  background: rgba(0, 0, 0, 0.75);
}
.pile-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  padding: 6px 8px 0;
}
.pile-tip {
  padding: 2px 8px 7px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pile-err {
  padding: 0 8px 8px;
  color: var(--danger);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
