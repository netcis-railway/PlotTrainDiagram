<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { request } from '../api/baseImport'
const props = defineProps<{ runId: string; runName: string }>()
const emit = defineEmits<{ close: []; imported: [filename: string] }>()
interface SolverLog { id: string; filename: string; size_bytes: number; created_at: string }
const dialog = ref<HTMLDialogElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const logs = ref<SolverLog[]>([]), file = ref<File | null>(null)
const loading = ref(true), busy = ref(false), error = ref(''), status = ref('')
const previousFocus = document.activeElement as HTMLElement | null
const controller = new AbortController()
let closed = false
const url = '/runs/' + encodeURIComponent(props.runId) + '/solver-logs'
function choose(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] || null; error.value = ''; status.value = '' }
function close() { closed = true; controller.abort(); emit('close') }
async function save() {
  const selected = file.value
  if (!selected || busy.value || closed) return
  if (!selected.size || selected.size > 32 * 1024 * 1024) { error.value = '请选择非空且不超过 32 MB 的日志文件。'; return }
  busy.value = true; error.value = ''; status.value = ''
  try {
    const saved = await request<SolverLog>(url + '?filename=' + encodeURIComponent(selected.name), {
      method: 'POST', body: selected, headers: { 'Content-Type': 'application/octet-stream' }, signal: controller.signal,
    })
    if (closed) return
    logs.value = [saved, ...logs.value.filter(log => log.id !== saved.id)]
    file.value = null
    if (input.value) input.value.value = ''
    status.value = '已保存求解日志：' + saved.filename
    emit('imported', saved.filename)
  } catch (e) { if (!closed) error.value = String(e) }
  finally { if (!closed) busy.value = false }
}
onMounted(async () => {
  await nextTick(); if (closed) return; dialog.value?.showModal()
  try { const result = await request<SolverLog[]>(url, { signal: controller.signal }); if (!closed) logs.value = [...logs.value, ...result.filter(log => !logs.value.some(saved => saved.id === log.id))] }
  catch (e) { if (!closed) error.value = String(e) }
  finally { if (!closed) loading.value = false }
})
onUnmounted(() => { closed = true; controller.abort(); previousFocus?.focus() })
</script>
<template>
  <dialog ref="dialog" class="category-picker solver-log-dialog" aria-labelledby="solver-log-title" @cancel.prevent="close">
    <h2 id="solver-log-title">导入求解日志</h2><p><strong>run：</strong>{{ runName }}</p>
    <p>选择此 run 的求解日志文件，保存后可在下方下载原始文件。</p>
    <form @submit.prevent="save">
      <label>日志文件<input ref="input" type="file" accept=".txt,.log,text/plain" :disabled="busy" @change="choose" /></label>
      <p v-if="file" class="muted">{{ file.name }} · {{ (file.size / 1024).toFixed(1) }} KB</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
      <div class="catalog-actions"><button type="submit" :disabled="busy || loading || !file">{{ busy ? '正在保存…' : '保存日志' }}</button><button type="button" @click="close">{{ status ? '关闭' : '取消' }}</button></div>
    </form>
    <h3>已导入日志</h3><p v-if="loading" role="status">正在读取…</p>
    <ul v-else-if="logs.length" class="solver-log-list"><li v-for="log in logs" :key="log.id"><a :href="'/api/v1' + url + '/' + encodeURIComponent(log.id) + '/download'">{{ log.filename }}</a><small>{{ (log.size_bytes / 1024).toFixed(1) }} KB · {{ log.created_at.replace('T', ' ') }}</small></li></ul>
    <p v-else class="muted">尚未导入求解日志。</p>
  </dialog>
</template>
