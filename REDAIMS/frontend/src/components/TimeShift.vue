<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { post, type Change, type Train, type ValidationIssue } from '../api/baseImport'
const props = defineProps<{ objectType: 'base' | 'run'; objectId: string; revision: string; dateBase: string; changes: Change[]; trains: Train[]; initialSelected: string[] }>()
const emit = defineEmits<{ close: []; applied: [changes: Change[], warnings: ValidationIssue[]] }>()
const dialog = ref<HTMLDialogElement | null>(null), previousFocus = document.activeElement as HTMLElement | null
const selected = ref(props.initialSelected.filter(id => props.trains.some(train => train.id === id)))
const amount = ref(''), unit = ref('60'), search = ref(''), busy = ref(false), error = ref(''), issues = ref<ValidationIssue[]>([])
const seconds = computed(() => Number(amount.value) * Number(unit.value))
const valid = computed(() => selected.value.length > 0 && /^[-+]?\d+$/.test(amount.value) && Number.isSafeInteger(seconds.value) && seconds.value !== 0 && Math.abs(seconds.value) <= 2147483647)
const options = computed(() => props.trains.filter(train => `${train.train_course_id} ${train.train_base_date}`.includes(search.value)))
async function confirm() {
  if (!valid.value) return
  busy.value = true; error.value = ''; issues.value = []
  try {
    const result = await post<{ can_apply: boolean; changes: Change[]; issues: ValidationIssue[] }>(`/time-shift/${props.objectType}/${props.objectId}/preview`, { revision: props.revision, changes: props.changes, date_base: props.dateBase || undefined, train_ids: selected.value, offset_seconds: seconds.value })
    if (result.can_apply) emit('applied', result.changes, result.issues.filter(issue => issue.severity === 'warning'))
    else { issues.value = result.issues; error.value = '当前草稿或平移结果未通过校验，未应用平移。' }
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
onMounted(async () => { await nextTick(); dialog.value?.showModal(); dialog.value?.focus() })
onUnmounted(() => previousFocus?.focus())
</script>
<template><dialog ref="dialog" class="track-repair-dialog time-shift-dialog" tabindex="-1" aria-labelledby="time-shift-title" @cancel.prevent="!busy && emit('close')">
  <h2 id="time-shift-title">整车时间平移</h2><p>将所选列车整条运行线的全部到发时刻平移相同时间，包含被筛选隐藏的车站。已有空时刻保持为空，股道和 SEQ 不变。</p>
  <p class="category-context">正数表示推迟，负数表示提前；在当前草稿上继续平移。结果进入编辑草稿，仍需校验并保存。不会自动调整其他列车或检查运行可行性。</p>
  <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="busy" role="status">正在生成平移草稿…</p>
  <fieldset :disabled="busy"><div class="form-columns"><label>平移量<input v-model="amount" inputmode="numeric" placeholder="例如 5 或 -120" /></label><label>单位<select v-model="unit"><option value="60">分钟</option><option value="1">秒</option></select></label></div>
    <div class="repair-tools"><label>查找列车<input v-model="search" placeholder="车次或基准日" /></label><button @click="selected = trains.map(train => train.id)">全选列车</button><button @click="selected = []">清空选择</button><span>已选 {{ selected.length }} / {{ trains.length }} 列车</span></div>
    <div class="checkbox-options"><label v-for="train in options" :key="train.id"><input v-model="selected" type="checkbox" :value="train.id" :aria-label="`平移列车 ${train.train_course_id} ${train.train_base_date}`" />{{ train.train_course_id }} · {{ train.train_base_date }}</label></div>
    <p v-if="valid">将{{ seconds > 0 ? '推迟' : '提前' }} {{ Math.abs(seconds) }} 秒，应用于 {{ selected.length }} 列车的完整运行线。</p><p v-else class="muted">请选择列车，输入非零整数平移量并选择单位。</p>
    <ul v-if="issues.length" class="validation-list"><li v-for="(issue, i) in issues" :key="i" :class="issue.severity === 'error' ? 'validation-error' : 'validation-warning'">{{ issue.message }}</li></ul>
    <div class="editor-actions"><button :disabled="!valid" @click="confirm">生成平移草稿</button><button @click="emit('close')">取消</button></div>
  </fieldset>
</dialog></template>
