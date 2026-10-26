<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { request } from '../api/baseImport'
interface Train { id: string; sheet: string; train_course_id: string; missing_seq: boolean; missing_g: boolean; visits: number; first_row: number | null; last_row: number | null }
const props = defineProps<{ jobId: string; filename: string }>()
const emit = defineEmits<{ close: []; repaired: [file: File, warnings: number] }>()
const dialog = ref<HTMLDialogElement | null>(null), busy = ref(false), error = ref('')
const trains = ref<Train[]>([]), selected = ref<string[]>([]), stamp = ref('')
const eligible = computed(() => trains.value.filter(train => train.missing_seq && train.visits > 0))
const previousFocus = document.activeElement as HTMLElement | null
const url = `/ingest/jobs/${props.jobId}/sequence-repair`
async function load() {
  busy.value = true
  try {
    const context = await request<{ repair_token: string; trains: Train[] }>(`${url}/context`)
    stamp.value = context.repair_token; trains.value = context.trains
    selected.value = eligible.value.map(train => train.id)
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function confirm() {
  if (!selected.value.length) return
  busy.value = true; error.value = ''
  try {
    const response = await fetch(`/api/v1${url}/apply`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repair_token: stamp.value, train_ids: selected.value }) })
    if (!response.ok) { const value = await response.json(); throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail)) }
    emit('repaired', new File([await response.blob()], props.filename, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }), 0)
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
onMounted(async () => { await nextTick(); dialog.value?.showModal(); await load(); dialog.value?.focus(); dialog.value?.scrollTo(0, 0) })
onUnmounted(() => previousFocus?.focus())
</script>
<template><dialog ref="dialog" class="track-repair-dialog sequence-repair-dialog" tabindex="-1" @cancel.prevent="!busy && emit('close')" aria-labelledby="sequence-repair-title">
  <h2 id="sequence-repair-title">修复SEQ信息</h2>
  <p>只补所选列车缺少的 _SEQ 列。按原 Excel 行号从小到大，有到达或出发时刻的行依次填入 1、2、3…，空白行跳过；SEQ 连续。</p>
  <p class="category-context">已有 SEQ 列及编号保持不变。若同时缺少 _G，先修复 SEQ，再修复股道。确认后自动重新预检，仍需核对并确认导入。</p>
  <p v-if="busy" role="status">正在处理…</p><p v-if="error" class="error" role="alert">{{ error }}</p>
  <fieldset :disabled="busy"><div class="repair-tools"><button :disabled="!eligible.length" @click="selected = eligible.map(train => train.id)">全选缺列列车</button><button @click="selected = []">清空选择</button><span>已选 {{ selected.length }} 列车</span></div>
    <div class="table-wrap repair-matrix"><table aria-label="SEQ修复列车选择"><thead><tr><th>列车</th><th>表单</th><th>有时刻的访问</th><th>处理</th></tr></thead><tbody><tr v-for="train in trains" :key="train.id"><th><label class="confirmation"><input v-model="selected" type="checkbox" :value="train.id" :disabled="!train.missing_seq || !train.visits" :aria-label="`修复SEQ ${train.sheet} ${train.train_course_id}`" />{{ train.train_course_id }}</label></th><td>{{ train.sheet }}</td><td>{{ train.visits }} 条<span v-if="train.first_row"> · 源行 {{ train.first_row }}—{{ train.last_row }}</span></td><td>{{ !train.missing_seq ? '已有SEQ，保留' : !train.visits ? '没有到发时刻，不能生成' : `补列，生成1—${train.visits}` }}</td></tr></tbody></table></div>
    <p v-if="!busy && !error && !eligible.length" class="muted">没有可修复的缺失 SEQ 列。已有列中的空值、重复或断号仍需核对原文件。</p>
    <div class="editor-actions"><button :disabled="!selected.length" @click="confirm">确认修复SEQ</button><button @click="emit('close')">取消</button></div>
  </fieldset>
</dialog></template>
