<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import type { CatalogAction, CatalogActionId } from '../catalogActions'
const props = defineProps<{ actions: CatalogAction[]; name: string; x: number; y: number }>()
const emit = defineEmits<{ action: [id: CatalogActionId]; close: [] }>()
const menu = ref<HTMLElement | null>(null)
const left = ref(props.x), top = ref(props.y)
const previousFocus = document.activeElement as HTMLElement | null
function items() { return Array.from(menu.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || []) }
function keydown(event: KeyboardEvent) {
  const buttons = items()
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
      : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
    buttons[next]?.focus()
  } else if (event.key === 'Escape') {
    event.preventDefault(); emit('close'); previousFocus?.focus()
  } else if (event.key === 'Tab') emit('close')
}
function outside(event: PointerEvent) { if (!menu.value?.contains(event.target as Node)) emit('close') }
function dismiss() { emit('close') }
function focusout(event: FocusEvent) { if (!menu.value?.contains(event.relatedTarget as Node | null)) emit('close') }
onMounted(async () => {
  await nextTick()
  const bounds = menu.value?.getBoundingClientRect()
  if (bounds) {
    left.value = Math.max(8, Math.min(props.x, window.innerWidth - bounds.width - 8))
    top.value = Math.max(8, Math.min(props.y, window.innerHeight - bounds.height - 8))
  }
  ;(items()[0] || menu.value)?.focus()
  document.addEventListener('pointerdown', outside, true)
  document.addEventListener('scroll', dismiss, true)
  window.addEventListener('resize', dismiss)
  window.addEventListener('blur', dismiss)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', outside, true)
  document.removeEventListener('scroll', dismiss, true)
  window.removeEventListener('resize', dismiss)
  window.removeEventListener('blur', dismiss)
})
</script>
<template>
  <Teleport to="body">
    <div ref="menu" class="catalog-context-menu" role="menu" tabindex="-1" :aria-label="name + ' 快捷操作'"
      :style="{ left: left + 'px', top: top + 'px' }" @keydown="keydown" @focusout="focusout" @contextmenu.prevent>
      <button v-for="action in actions" :key="action.id" type="button" role="menuitem" :disabled="action.disabled"
        :class="{ 'menu-danger': action.danger }" :title="action.title" @click="emit('action', action.id)">{{ action.label }}</button>
    </div>
  </Teleport>
</template>
