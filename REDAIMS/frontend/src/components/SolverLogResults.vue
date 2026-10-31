<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { analysisApi, type SolverLogSummary, type SolverResultSource } from '../api/analysis'
const props = defineProps<{ runId: string; logId: string; initial?: SolverLogSummary }>()
const emit = defineEmits<{ saved: [value: SolverLogSummary] }>()
const current = ref<SolverLogSummary | null>(null), objective = ref(''), seconds = ref('')
const loading = ref(false), busy = ref(false), error = ref(''), status = ref('')
const labels: Record<SolverResultSource, string> = { 'solver-log': '求解日志', manual: '人工填写', unavailable: '未获取' }
let generation = 0
function adopt(value: SolverLogSummary) { current.value = value; objective.value = value.best_objective == null ? '' : String(value.best_objective); seconds.value = value.solve_seconds == null ? '' : String(value.solve_seconds) }
const numeric = (value: string) => value.trim() === '' ? null : Number(value)
const dirty = computed(() => !!current.value && (numeric(objective.value) !== (current.value.best_objective ?? null) || numeric(seconds.value) !== (current.value.solve_seconds ?? null)))
async function load() {
  const version = ++generation, run = props.runId, id = props.logId
  current.value = null; error.value = ''; status.value = ''; loading.value = true; busy.value = false
  try {
    const value = props.initial?.id === id ? props.initial : await analysisApi.logMetadata(run, id)
    if (version === generation) adopt(value)
  } catch (e) { if (version === generation) error.value = String(e) }
  finally { if (version === generation) loading.value = false }
}
async function save() {
  if (!current.value || busy.value || loading.value || !dirty.value) return
  const body: { best_objective?: number | null; solve_seconds?: number | null } = {}
  error.value = ''; status.value = ''
  for (const [key, text, previous] of [['best_objective', objective.value, current.value.best_objective], ['solve_seconds', seconds.value, current.value.solve_seconds]] as const) {
    const value = text.trim() === '' ? null : Number(text)
    if (value !== null && (!Number.isFinite(value) || (key === 'solve_seconds' && value < 0))) { error.value = key === 'solve_seconds' ? '求解时间必须为非负的有限数值（秒）。' : '目标函数最优值必须为有限数值。'; return }
    if (value !== (previous ?? null)) body[key] = value
  }
  if (!Object.keys(body).length) return
  const version = generation, run = props.runId, id = props.logId
  busy.value = true
  try {
    const value = await analysisApi.updateLogResults(run, id, body)
    if (version !== generation) return
    adopt(value); status.value = '已保存求解结果，修改字段的来源已标记为人工填写。'; emit('saved', value)
  } catch (e) { if (version === generation) error.value = String(e) }
  finally { if (version === generation) busy.value = false }
}
watch(() => [props.runId, props.logId], load, { immediate: true })
onUnmounted(() => { generation++; current.value = null })
</script>
<template>
  <form class="solver-log-results" aria-label="求解结果属性" @submit.prevent="save">
    <h4>求解结果</h4>
    <p v-if="loading" role="status">正在读取求解结果…</p>
    <template v-if="current">
      <div class="solver-result-fields">
        <label title="取日志最终解的目标值；尚未证明最优时，为当前最好可行解的目标值。">目标函数最优值<input :value="objective" type="number" step="any" :disabled="busy" @input="objective = ($event.target as HTMLInputElement).value" /><small>来源：{{ labels[current.objective_source || 'unavailable'] }}</small></label>
        <label>求解时间（秒）<input :value="seconds" type="number" step="any" min="0" :disabled="busy" @input="seconds = ($event.target as HTMLInputElement).value" /><small>来源：{{ labels[current.time_source || 'unavailable'] }}</small></label>
        <button type="submit" :disabled="busy || !dirty">{{ busy ? '正在保存…' : '保存求解结果' }}</button>
      </div>
      <p v-for="warning in current.result_warnings || []" :key="warning" class="solver-result-warning" role="status">{{ warning }}</p>
    </template>
    <p v-if="error" class="error" role="alert">{{ error }} <button v-if="!current" type="button" @click="load">重试</button></p>
    <p v-if="status" role="status">{{ status }}</p>
  </form>
</template>
