<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'

const form = reactive({
  llm_base: '',
  llm_key: '',
  llm_model: '',
  llm_prompt: '',
  chapter_list: '',
})
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const error = ref('')
const okMsg = ref('')

onMounted(async () => {
  try {
    const { settings } = await api.settings()
    Object.assign(form, settings)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})

async function save() {
  saving.value = true
  error.value = ''
  okMsg.value = ''
  try {
    const { settings } = await api.saveSettings({ ...form })
    Object.assign(form, settings)
    okMsg.value = '已保存'
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  error.value = ''
  okMsg.value = ''
  try {
    const r = await api.testSettings()
    okMsg.value = `连通正常，模型 ${r.model} 回了「${r.reply}」`
  } catch (e) {
    error.value = e.message
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="page-head">
    <div>
      <h1 class="page-title">设置</h1>
      <p class="page-desc">大模型接口、章节字典都在这儿改，改完立即生效</p>
    </div>
  </div>

  <div v-if="error" class="alert alert-error">{{ error }}</div>
  <div v-if="okMsg" class="alert alert-ok">{{ okMsg }}</div>
  <div v-if="loading" class="empty">加载中…</div>

  <div v-else class="grid-2" style="align-items: start">
    <div class="card card-pad">
      <strong style="font-size: 14px">大模型（多模态识别）</strong>
      <p class="small muted" style="margin: 4px 0 14px">
        走 OpenAI 兼容协议，换服务商只改地址和模型即可。Key 存在本地 SQLite，不出这台机器。
      </p>

      <label class="field">
        <span>接口地址（Base URL）</span>
        <input v-model="form.llm_base" type="text" placeholder="https://api.vectorengine.ai/v1" />
      </label>
      <label class="field">
        <span>API Key</span>
        <input v-model="form.llm_key" type="password" placeholder="sk-..." autocomplete="off" />
      </label>
      <label class="field">
        <span>模型名</span>
        <input v-model="form.llm_model" type="text" placeholder="gpt-4o / gemini-2.0-flash / qwen-vl-max" />
      </label>
      <label class="field">
        <span>自定义提示词（留空用内置模板）</span>
        <textarea v-model="form.llm_prompt" rows="4" placeholder="留空即可"></textarea>
      </label>

      <div class="row">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
        <button class="btn" :disabled="testing" @click="test">
          <span v-if="testing" class="spinner" style="border-color: #ccc; border-top-color: #666"></span>
          {{ testing ? '测试中…' : '测试连通' }}
        </button>
      </div>
    </div>

    <div>
      <div class="card card-pad" style="margin-bottom: 14px">
        <strong style="font-size: 14px">章节字典</strong>
        <p class="small muted" style="margin: 4px 0 10px">
          用英文逗号分隔，识别和筛选时的下拉框都读这里
        </p>
        <label class="field">
          <textarea v-model="form.chapter_list" rows="4" placeholder="分数乘法,分数除法,位置与方向,比,圆,百分数"></textarea>
        </label>
        <button class="btn" :disabled="saving" @click="save">保存章节</button>
      </div>

      <div class="card card-pad">
        <strong style="font-size: 14px">数据在哪</strong>
        <div class="small muted" style="line-height: 2; margin-top: 6px">
          题库：<code>server/data/cuoti.db</code><br />
          原图：<code>server/data/uploads/</code><br />
          卷子：<code>server/data/papers/</code><br />
          想备份，直接拷整个 <code>server/data</code> 目录。
        </div>
      </div>
    </div>
  </div>
</template>
