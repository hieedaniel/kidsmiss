<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, frac } from '../api'
import CropBox from '../components/CropBox.vue'

const router = useRouter()
const fileInput = ref(null)
const uploading = ref(false)
const recognizing = ref(false)
const saving = ref(false)
const error = ref('')
const okMsg = ref('')

const image = ref(null) // { file, url, width, height }
const crop = ref(null) // [x1,y1,x2,y2]
const chapters = ref([])

const form = reactive({
  chapter: '',
  qtype: 'choice',
  points: 0,
  stem: '',
  optionsText: '',
  subsText: '',
  answer: '',
  student_answer: '',
  analysisText: '',
  error_cause: '',
})

const preview = computed(() => {
  const parts = []
  if (form.stem) parts.push(frac(form.stem))
  return parts.join('')
})

onMounted(async () => {
  try {
    const m = await api.meta()
    chapters.value = m.chapters || []
  } catch (e) {
    error.value = e.message
  }
})

function pick() {
  fileInput.value?.click()
}

async function onFile(e) {
  const f = e.target.files?.[0]
  if (!f) return
  error.value = ''
  uploading.value = true
  try {
    const base64 = await new Promise((res, rej) => {
      const r = new FileReader()
      r.onload = () => res(r.result)
      r.onerror = rej
      r.readAsDataURL(f)
    })
    const r = await api.upload(f.name, base64)
    image.value = { ...r, filename: f.name }
    crop.value = null
  } catch (e2) {
    error.value = e2.message
  } finally {
    uploading.value = false
  }
}

async function recognize() {
  if (!image.value) return
  error.value = ''
  okMsg.value = ''
  recognizing.value = true
  try {
    const { draft } = await api.recognize(image.value.file)
    form.chapter = draft.chapter || form.chapter
    form.qtype = draft.qtype || form.qtype
    form.points = draft.points || form.points
    form.stem = draft.stem || ''
    form.optionsText = (draft.options || []).join('\n')
    form.subsText = (draft.sub_items || []).join('\n')
    form.answer = draft.answer || ''
    form.student_answer = draft.student_answer || ''
    form.analysisText = (draft.analysis || []).join('\n')
    form.error_cause = draft.error_cause || ''
    okMsg.value = '识别完成，请务必核对答案和错因'
  } catch (e) {
    error.value = e.message
  } finally {
    recognizing.value = false
  }
}

function lines(text) {
  return text
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
}

async function save() {
  if (!image.value) return (error.value = '先上传一张照片')
  if (!form.stem.trim()) return (error.value = '题干不能为空')
  error.value = ''
  saving.value = true
  try {
    const figures = []
    if (crop.value && image.value.width) {
      figures.push({ src: image.value.file, box: crop.value, w: 46 })
    }
    await api.createItem({
      subject: '数学',
      grade: '六年级上册',
      chapter: form.chapter,
      qtype: form.qtype,
      points: Number(form.points) || 0,
      space_mm: form.qtype === 'solve' ? 50 : 0,
      stem: form.stem.trim(),
      options: lines(form.optionsText),
      sub_items: lines(form.subsText),
      answer: form.answer.trim() || '?',
      student_answer: form.student_answer.trim(),
      analysis: lines(form.analysisText),
      error_cause: form.error_cause.trim(),
      figures,
      status: form.answer.trim() ? 'wrong' : 'unverified',
      stars: 1,
      exam: '手动录入',
      exam_date: new Date().toISOString().slice(0, 10),
    })
    router.push('/items')
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

function reset() {
  image.value = null
  crop.value = null
  Object.assign(form, {
    chapter: '', qtype: 'choice', points: 0, stem: '',
    optionsText: '', subsText: '', answer: '', student_answer: '',
    analysisText: '', error_cause: '',
  })
  okMsg.value = ''
  error.value = ''
}
</script>

<template>
  <div class="page-head">
    <div>
      <h1 class="page-title">拍照上传</h1>
      <p class="page-desc">拍一张 → 识别 → 核对 → 入库</p>
    </div>
    <button class="btn" @click="reset">重来</button>
  </div>

  <div v-if="error" class="alert alert-error">{{ error }}</div>
  <div v-if="okMsg" class="alert alert-ok">{{ okMsg }}</div>

  <div class="grid-2" style="align-items: start">
    <!-- 左：图片 -->
    <div class="card card-pad">
      <input ref="fileInput" type="file" accept="image/*" capture="environment" hidden @change="onFile" />

      <div v-if="!image" class="dropzone" @click="pick">
        <div class="big">📷</div>
        <div style="font-weight: 600; margin-top: 6px">
          {{ uploading ? '上传中…' : '点这里拍照或选图' }}
        </div>
        <div class="small muted" style="margin-top: 4px">正上方俯拍，四角入框，别用闪光灯</div>
      </div>

      <template v-else>
        <CropBox
          :src="image.url"
          :natural="{ w: image.width, h: image.height }"
          v-model="crop"
        />
        <div class="small muted" style="margin-top: 6px">
          几何题记得框一下图形，排版时会把它单独贴进卷子；不框就用整张原图。
        </div>
        <div class="row" style="margin-top: 10px">
          <button class="btn btn-primary" :disabled="recognizing" @click="recognize">
            <span v-if="recognizing" class="spinner"></span>
            {{ recognizing ? '识别中…' : 'AI 识别这道题' }}
          </button>
          <button class="btn" @click="pick">换一张</button>
        </div>
      </template>
    </div>

    <!-- 右：表单 -->
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
        <span>题干（分数写 [3/4]，填空处写（　　））</span>
        <textarea v-model="form.stem" rows="3" placeholder="例题：有一根铁丝，第一次用去它的一半多 1 米…"></textarea>
      </label>

      <details style="margin-bottom: 12px">
        <summary class="small muted" style="cursor: pointer; margin-bottom: 8px">
          子项 / 选项 / 解析（选择题填这里）
        </summary>
        <label class="field">
          <span>子项 ①②③④（每行一条，没有就空着）</span>
          <textarea v-model="form.subsText" rows="2"></textarea>
        </label>
        <label class="field">
          <span>选项（每行一个，含 A. 前缀）</span>
          <textarea v-model="form.optionsText" rows="3" placeholder="A. 在一条直线上&#10;B. 不在一条直线上"></textarea>
        </label>
        <label class="field">
          <span>解析步骤（每行一步）</span>
          <textarea v-model="form.analysisText" rows="3"></textarea>
        </label>
      </details>

      <div class="grid-2">
        <label class="field">
          <span>正确答案</span>
          <input v-model="form.answer" type="text" placeholder="A / 44 米" />
        </label>
        <label class="field">
          <span>学生答案</span>
          <input v-model="form.student_answer" type="text" placeholder="B / 未作答" />
        </label>
      </div>

      <label class="field">
        <span>错因（具体到思维动作，别写"粗心"）</span>
        <textarea v-model="form.error_cause" rows="2"></textarea>
      </label>

      <div class="row">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存到错题库' }}
        </button>
        <router-link to="/items" class="btn">取消</router-link>
      </div>
    </div>
  </div>
</template>
