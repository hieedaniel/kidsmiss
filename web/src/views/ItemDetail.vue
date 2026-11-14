<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, frac, STATUS_TEXT } from '../api'
import CropBox from '../components/CropBox.vue'

const route = useRoute()
const router = useRouter()
const item = ref(null)
const chapters = ref([])
const error = ref('')
const okMsg = ref('')
const saving = ref(false)
const loading = ref(true)
const crop = ref(null)

const form = reactive({
  chapter: '', qtype: 'choice', points: 0, status: 'wrong',
  stem: '', optionsText: '', subsText: '', answer: '',
  student_answer: '', analysisText: '', error_cause: '',
})

const imgSrc = computed(() => {
  const f = item.value?.figures?.[0]
  return f ? `/uploads/${String(f.src).replace(/^scans\//, '')}` : ''
})

const nat = ref({ w: 0, h: 0 })
watch(
  imgSrc,
  (src) => {
    if (!src) return
    const im = new Image()
    im.onload = () => {
      nat.value = { w: im.naturalWidth, h: im.naturalHeight }
    }
    im.src = src
  },
  { immediate: true }
)

const mastery = computed(() => item.value?.mastery)
const attempts = computed(() => item.value?.attempts || [])

function lines(t) {
  return t.split('\n').map((s) => s.trim()).filter(Boolean)
}

async function load() {
  loading.value = true
  try {
    const [r, m] = await Promise.all([api.item(route.params.id), api.meta()])
    item.value = r.item
    chapters.value = m.chapters || []
    Object.assign(form, {
      chapter: r.item.chapter || '',
      qtype: r.item.qtype || 'choice',
      points: r.item.points || 0,
      status: r.item.status || 'wrong',
      stem: r.item.stem || '',
      optionsText: (r.item.options || []).join('\n'),
      subsText: (r.item.sub_items || []).join('\n'),
      answer: r.item.answer || '',
      student_answer: r.item.student_answer || '',
      analysisText: (r.item.analysis || []).join('\n'),
      error_cause: r.item.error_cause || '',
    })
    crop.value = r.item.figures?.[0]?.box || null
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function save() {
  saving.value = true
  error.value = ''
  okMsg.value = ''
  try {
    const figures = imgSrc.value
      ? [{ src: item.value.figures[0].src, box: crop.value, w: item.value.figures[0].w || 46 }]
      : []
    const r = await api.updateItem(item.value.id, {
      chapter: form.chapter,
      qtype: form.qtype,
      points: Number(form.points) || 0,
      space_mm: form.qtype === 'solve' ? 50 : 0,
      status: form.status,
      stem: form.stem,
      options: lines(form.optionsText),
      sub_items: lines(form.subsText),
      answer: form.answer,
      student_answer: form.student_answer,
      analysis: lines(form.analysisText),
      error_cause: form.error_cause,
      figures,
    })
    item.value = { ...item.value, ...r.item }
    okMsg.value = '已保存'
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function mark(result) {
  try {
    const r = await api.attempt(item.value.id, result)
    item.value.stars = r.item.stars
    item.value.status = r.item.status
    item.value.mastery = r.mastery
    form.status = r.item.status
    const a = await api.item(item.value.id)
    item.value.attempts = a.item.attempts
  } catch (e) {
    error.value = e.message
  }
}

async function remove() {
  if (!confirm('确认删除这道题？')) return
  await api.deleteItem(item.value.id)
  router.push('/items')
}
</script>

<template>
  <div class="page-head">
    <div>
      <h1 class="page-title">{{ route.params.id }}</h1>
      <p class="page-desc">改完记得保存，组卷时用的是这里的内容</p>
    </div>
    <div class="row">
      <button class="btn" @click="router.push('/items')">← 返回题库</button>
      <button class="btn btn-danger" @click="remove">删除</button>
    </div>
  </div>

  <div v-if="error" class="alert alert-error">{{ error }}</div>
  <div v-if="okMsg" class="alert alert-ok">{{ okMsg }}</div>
  <div v-if="loading" class="empty">加载中…</div>

  <div v-else-if="item" class="grid-2" style="align-items: start">
    <div class="card card-pad">
      <div class="grid-2">
        <label class="field">
          <span>章节</span>
          <select v-model="form.chapter">
            <option value="">未分类</option>
            <option v-for="c in chapters" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>
        <label class="field">
          <span>题型</span>
          <select v-model="form.qtype">
            <option value="choice">选择题</option>
            <option value="fill">填空题</option>
            <option value="solve">解答题</option>
          </select>
        </label>
      </div>

      <label class="field">
        <span>题干</span>
        <textarea v-model="form.stem" rows="3"></textarea>
      </label>

      <div class="grid-2">
        <label class="field">
          <span>子项（每行一条）</span>
          <textarea v-model="form.subsText" rows="3"></textarea>
        </label>
        <label class="field">
          <span>选项（每行一个）</span>
          <textarea v-model="form.optionsText" rows="3"></textarea>
        </label>
      </div>

      <div class="grid-2">
        <label class="field">
          <span>正确答案</span>
          <input v-model="form.answer" type="text" />
        </label>
        <label class="field">
          <span>学生答案</span>
          <input v-model="form.student_answer" type="text" />
        </label>
      </div>

      <label class="field">
        <span>解析步骤（每行一步）</span>
        <textarea v-model="form.analysisText" rows="4"></textarea>
      </label>
      <label class="field">
        <span>错因</span>
        <textarea v-model="form.error_cause" rows="2"></textarea>
      </label>

      <div class="row">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存修改' }}
        </button>
        <span class="muted small">预览：</span>
        <span v-html="frac(form.stem)" style="font-size: 13px"></span>
      </div>
    </div>

    <div>
      <div class="card card-pad" style="margin-bottom: 14px">
        <strong style="font-size: 14px">掌握情况</strong>
        <div class="row" style="margin-top: 10px">
          <span class="tag" :class="`st-${item.status}`">{{ STATUS_TEXT[item.status] }}</span>
          <span class="stars">{{ '★'.repeat(item.stars || 1) }}</span>
        </div>
        <div v-if="mastery" class="small muted" style="margin-top: 8px; line-height: 1.9">
          重做 {{ mastery.attempts }} 次，连续答对 {{ mastery.streak }} 次<br />
          上次：{{ mastery.last_at }}（{{ mastery.last_result === 'correct' ? '答对' : '答错' }}）<br />
          下次建议复习：<strong :style="{ color: mastery.overdue ? 'var(--danger)' : 'var(--primary)' }">
            {{ mastery.due_at }}
          </strong>
          {{ mastery.overdue ? '（已到期）' : '' }}
        </div>
        <div v-else class="small muted" style="margin-top: 8px">还没有重做记录</div>
        <div class="row" style="margin-top: 12px">
          <button class="btn btn-sm" @click="mark('correct')">✓ 重做对了</button>
          <button class="btn btn-sm btn-danger" @click="mark('wrong')">✗ 又错了</button>
        </div>
      </div>

      <div v-if="imgSrc" class="card card-pad" style="margin-bottom: 14px">
        <strong style="font-size: 14px">原卷配图</strong>
        <div class="small muted" style="margin: 4px 0 8px">拖一个框，把图形圈出来</div>
        <CropBox
          :src="imgSrc"
          :natural="nat"
          v-model="crop"
        />
      </div>

      <div class="card card-pad">
        <strong style="font-size: 14px">重做记录</strong>
        <div v-if="!attempts.length" class="empty" style="padding: 20px">还没有记录</div>
        <div v-else class="timeline" style="margin-top: 12px">
          <div
            v-for="a in attempts"
            :key="a.id"
            class="tl-item"
            :class="a.result === 'correct' ? 'ok' : 'bad'"
          >
            <div class="row">
              <strong>{{ a.result === 'correct' ? '答对' : '答错' }}</strong>
              <div class="spacer"></div>
              <span class="muted small">{{ a.created_at }}</span>
            </div>
            <div v-if="a.note" class="muted small">{{ a.note }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
