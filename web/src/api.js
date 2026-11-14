const BASE = ''

async function request(path, { method = 'GET', body } = {}) {
  const init = { method }
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  let res
  try {
    res = await fetch(BASE + path, init)
  } catch (e) {
    throw new Error('连不上后端，确认 python server/main.py 在跑')
  }
  const isJson = (res.headers.get('content-type') || '').includes('json')
  const data = isJson ? await res.json() : null
  if (!res.ok) throw new Error((data && data.error) || `请求失败 ${res.status}`)
  return data
}

export const api = {
  meta: () => request('/api/meta'),

  items: (params = {}) => {
    const q = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined) q.append(k, v)
    })
    const s = q.toString()
    return request('/api/items' + (s ? `?${s}` : ''))
  },
  item: (id) => request(`/api/items/${id}`),
  createItem: (body) => request('/api/items', { method: 'POST', body }),
  updateItem: (id, body) => request(`/api/items/${id}`, { method: 'PUT', body }),
  deleteItem: (id) => request(`/api/items/${id}`, { method: 'DELETE' }),
  attempt: (id, result, note = '') =>
    request(`/api/items/${id}/attempt`, { method: 'POST', body: { result, note } }),

  upload: (filename, data) =>
    request('/api/upload', { method: 'POST', body: { filename, data } }),
  recognize: (file, hint = '') =>
    request('/api/ai/recognize', { method: 'POST', body: { file, hint } }),

  batchStart: (body) => request('/api/batch/jobs', { method: 'POST', body }),
  batchJob: (id) => request(`/api/batch/jobs/${id}`),
  batchJobs: () => request('/api/batch/jobs'),
  batchDrop: (id) => request(`/api/batch/jobs/${id}`, { method: 'DELETE' }),

  settings: () => request('/api/settings'),
  saveSettings: (body) => request('/api/settings', { method: 'PUT', body }),
  testSettings: () => request('/api/settings/test', { method: 'POST', body: {} }),

  papers: () => request('/api/papers'),
  buildPaper: (body) => request('/api/papers', { method: 'POST', body }),
}

/** 把 [3/4] 渲染成真分数（返回 HTML，配合 v-html） */
export function frac(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\[(\d+)\s*\/\s*(\d+)\]/g, (_, a, b) => `<span class="frac"><i>${a}</i><i>${b}</i></span>`)
}

export const STATUS_TEXT = {
  wrong: '错题',
  format: '过程不规范',
  unverified: '待核对',
  mastered: '已掌握',
  teacher_error: '批改存疑',
}

export const QTYPES = [
  { v: 'choice', t: '选择题' },
  { v: 'fill', t: '填空题' },
  { v: 'solve', t: '解答题' },
]

export function fmtDate(s) {
  return s ? String(s).slice(0, 10) : ''
}

export function thumbOf(item) {
  const f = (item.figures || [])[0]
  if (f && f.src) return `/uploads/thumbs/${String(f.src).replace(/^scans\//, '').replace(/\.\w+$/, '')}.jpg`
  return ''
}
