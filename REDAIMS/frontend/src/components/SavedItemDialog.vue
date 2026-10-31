<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, useId } from 'vue'
const props = defineProps<{ typeLabel: string; initialName: string; initialNotes?: string; busy: boolean; error: string }>()
const emit = defineEmits<{ submit: [metadata: { name: string; notes: string }]; close: [] }>()
const titleId = useId(), dialog = ref<HTMLDialogElement | null>(null), nameInput = ref<HTMLInputElement | null>(null)
const name = ref(props.initialName), notes = ref(props.initialNotes || '')
const previousFocus = document.activeElement as HTMLElement | null
let disposed = false
function cancel() { if (!props.busy) emit('close') }
function submit() { if (!props.busy && name.value.trim()) emit('submit', { name: name.value.trim(), notes: notes.value }) }
onMounted(async () => {
  await nextTick()
  if (disposed) return
  dialog.value?.showModal()
  nameInput.value?.focus({ preventScroll: true })
  nameInput.value?.select()
})
onUnmounted(() => {
  disposed = true
  dialog.value?.close()
  previousFocus?.focus({ preventScroll: true })
})
</script>
<template>
  <dialog ref="dialog" class="saved-item-dialog" :aria-labelledby="titleId" @cancel.prevent="cancel">
    <form @submit.prevent="submit">
      <h2 :id="titleId">保存{{ typeLabel }}</h2>
      <label>子节点类型<input :value="typeLabel" readonly /></label>
      <label>名称<input ref="nameInput" v-model="name" required maxlength="200" :disabled="busy" /></label>
      <label>备注<textarea v-model="notes" rows="4" maxlength="20000" :disabled="busy" /></label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="catalog-actions">
        <button type="submit" :disabled="busy || !name.trim()">{{ busy ? '正在保存…' : '保存' }}</button>
        <button type="button" :disabled="busy" @click="cancel">取消</button>
      </div>
    </form>
  </dialog>
</template>
