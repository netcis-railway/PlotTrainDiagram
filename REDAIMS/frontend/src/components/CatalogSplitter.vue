<script setup lang="ts">
import { computed, ref } from 'vue'
const props = defineProps<{ modelValue: number }>()
const emit = defineEmits<{ 'update:modelValue': [width: number] }>()
const handle = ref<HTMLElement | null>(null)
const drag = ref<{ id: number; x: number; width: number } | null>(null)
const minimum = 180
const maximum = ref(520)
const resizing = computed(() => drag.value !== null)
function measure() {
  const workspaceWidth = handle.value?.parentElement?.getBoundingClientRect().width || 1200
  maximum.value = Math.max(minimum, Math.min(520, Math.floor(workspaceWidth * .45)))
}
function update(width: number) {
  emit('update:modelValue', Math.max(minimum, Math.min(maximum.value, Math.round(width))))
}
function start(event: PointerEvent) {
  if (event.button !== 0 || !handle.value) return
  event.preventDefault(); measure()
  const width = handle.value.previousElementSibling?.getBoundingClientRect().width || props.modelValue
  drag.value = { id: event.pointerId, x: event.clientX, width }
  handle.value.setPointerCapture(event.pointerId)
  handle.value.focus()
}
function move(event: PointerEvent) {
  if (drag.value?.id === event.pointerId) update(drag.value.width + event.clientX - drag.value.x)
}
function stop(event: PointerEvent) {
  if (drag.value?.id !== event.pointerId) return
  drag.value = null
  if (handle.value?.hasPointerCapture(event.pointerId)) handle.value.releasePointerCapture(event.pointerId)
}
function keydown(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault(); measure()
  const width = handle.value?.previousElementSibling?.getBoundingClientRect().width || props.modelValue
  update(event.key === 'Home' ? minimum : event.key === 'End' ? maximum.value : width + (event.key === 'ArrowRight' ? 16 : -16))
}
</script>
<template>
  <div ref="handle" class="catalog-splitter" :class="{ resizing }" role="separator" tabindex="0"
    aria-label="调整项目分类导航栏宽度" aria-controls="catalog-navigation" aria-orientation="vertical"
    :aria-valuemin="minimum" :aria-valuemax="maximum" :aria-valuenow="Math.min(modelValue, maximum)" :aria-valuetext="`${Math.min(modelValue, maximum)} 像素`"
    title="拖动调整宽度；方向键微调；双击恢复默认宽度"
    @pointerdown="start" @pointermove="move" @pointerup="stop" @pointercancel="stop" @lostpointercapture="drag = null"
    @keydown="keydown" @dblclick="measure(); update(280)" />
</template>
