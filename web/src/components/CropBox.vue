<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  src: { type: String, required: true },
  natural: { type: Object, default: () => ({ w: 0, h: 0 }) },
  modelValue: { type: Array, default: null }, // [x1,y1,x2,y2] 原图坐标
})
const emit = defineEmits(['update:modelValue'])

const wrap = ref(null)
const drag = ref(null)

const box = computed(() => props.modelValue)

function toNatural(e) {
  const rect = wrap.value.getBoundingClientRect()
  const scale = rect.width / (props.natural.w || rect.width)
  return {
    x: Math.round(Math.max(0, Math.min(rect.width, e.clientX - rect.left)) * scale),
    y: Math.round(Math.max(0, Math.min(rect.height, e.clientY - rect.top)) * scale),
    scale,
    rect,
  }
}

function onDown(e) {
  if (!props.natural.w) return
  const p = toNatural(e)
  drag.value = { x0: p.x, y0: p.y }
  emit('update:modelValue', [p.x, p.y, p.x, p.y])
  e.preventDefault()
}

function onMove(e) {
  if (!drag.value) return
  const p = toNatural(e)
  const [x0, y0] = [drag.value.x0, drag.value.y0]
  emit('update:modelValue', [
    Math.min(x0, p.x),
    Math.min(y0, p.y),
    Math.max(x0, p.x),
    Math.max(y0, p.y),
  ])
}

function onUp() {
  drag.value = null
}

function clear() {
  emit('update:modelValue', null)
}

/** 把原图坐标换算成百分比，用于 CSS 定位 */
const style = computed(() => {
  if (!box.value || !props.natural.w || !props.natural.h) return { display: 'none' }
  const [x1, y1, x2, y2] = box.value
  return {
    left: (x1 / props.natural.w) * 100 + '%',
    top: (y1 / props.natural.h) * 100 + '%',
    width: ((x2 - x1) / props.natural.w) * 100 + '%',
    height: ((y2 - y1) / props.natural.h) * 100 + '%',
  }
})

const size = computed(() => {
  if (!box.value) return ''
  const [x1, y1, x2, y2] = box.value
  return `${Math.abs(x2 - x1)} × ${Math.abs(y2 - y1)} px`
})
</script>

<template>
  <div>
    <div
      ref="wrap"
      class="crop-wrap"
      @mousedown="onDown"
      @mousemove="onMove"
      @mouseup="onUp"
      @mouseleave="onUp"
    >
      <img :src="src" alt="" draggable="false" />
      <div class="crop-rect" :style="style"></div>
      <div v-if="!box" class="crop-hint">按住鼠标拖一个框，框住题目里的图形</div>
    </div>
    <div class="row small muted" style="margin-top: 6px">
      <span>{{ box ? size : '未选择配图区域' }}</span>
      <div class="spacer"></div>
      <button v-if="box" class="btn btn-sm" type="button" @click="clear">清除</button>
    </div>
  </div>
</template>

<style scoped>
.crop-wrap {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  user-select: none;
  cursor: crosshair;
  background: #fff;
  line-height: 0;
}
.crop-wrap img {
  width: 100%;
  display: block;
  pointer-events: none;
}
.crop-rect {
  position: absolute;
  border: 2px solid var(--primary);
  background: rgba(44, 110, 73, 0.12);
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.28);
  pointer-events: none;
}
.crop-hint {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 12px;
  line-height: 1.5;
  padding: 5px 10px;
  border-radius: 6px;
  pointer-events: none;
  white-space: nowrap;
}
</style>
