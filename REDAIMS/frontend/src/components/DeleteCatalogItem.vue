<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, useId } from 'vue'
const props = defineProps<{ name: string; message: string; busy: boolean; error: string }>()
const emit = defineEmits<{ confirm: []; close: [] }>()
const titleId = useId(), messageId = useId(), dialog = ref<HTMLDialogElement | null>(null), cancelButton = ref<HTMLButtonElement | null>(null)
const previousFocus = document.activeElement as HTMLElement | null
let disposed = false
function cancel() { if (!props.busy) emit('close') }
function confirm() { if (!props.busy) emit('confirm') }
onMounted(async () => {
  await nextTick()
  if (disposed) return
  dialog.value?.showModal()
  cancelButton.value?.focus({ preventScroll: true })
})
onUnmounted(() => { disposed = true; dialog.value?.close(); previousFocus?.focus({ preventScroll: true }) })
</script>
<template>
  <dialog ref="dialog" class="saved-item-dialog" :aria-labelledby="titleId" :aria-describedby="messageId" @cancel.prevent="cancel">
    <h2 :id="titleId">删除所选项目</h2>
    <p>确定删除“<strong>{{ name }}</strong>”？</p>
    <p :id="messageId">{{ message }}</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="catalog-actions">
      <button type="button" class="danger" :disabled="busy" @click="confirm">{{ busy ? '正在删除…' : '删除' }}</button>
      <button ref="cancelButton" type="button" :disabled="busy" @click="cancel">取消</button>
    </div>
  </dialog>
</template>
