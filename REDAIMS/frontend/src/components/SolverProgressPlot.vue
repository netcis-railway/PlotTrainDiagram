<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { analysisApi, type LogDisplay, type SolverPlot, type SolverPlotter } from '../api/analysis'
const props = defineProps<{ runId: string; logId: string; encoding: LogDisplay['encoding']; solverType: string; defaultPlotter: string | null; plotters: SolverPlotter[]; state: Record<string, unknown> }>()
const emit = defineEmits<{ 'update:state': [state: Record<string, unknown>] }>()
const plotter = ref(''), result = ref<SolverPlot | null>(null), busy = ref(false), error = ref('')
const zoom = ref(typeof props.state.zoom === 'number' && props.state.zoom >= 50 && props.state.zoom <= 200 ? props.state.zoom : 100)
const choices = computed(() => props.plotters.filter(p => p.solver_type === props.solverType))
const selected = computed(() => choices.value.find(p => p.id === plotter.value))
const image = computed(() => result.value ? `data:image/png;base64,${result.value.image_base64}` : '')
const summaryLabels: Record<string, string> = { rows: '进度行数', heuristic_rows: '启发式改进行数', branch_and_bound_rows: 'B&B节点改进行数', root_obj: '根节点松弛目标值', final_obj: '最终目标值', final_bound: '最终界', total_time: '求解时间（秒）' }
let generation = 0, closed = false
function persist() { emit('update:state', { ...props.state, plotter_id: plotter.value, zoom: zoom.value }) }
async function render() {
  const version = ++generation
  result.value = null; error.value = ''; busy.value = false
  if (!props.logId || !selected.value?.available || closed) return
  busy.value = true; persist()
  try {
    const value = await analysisApi.plotLog(props.runId, props.logId, props.encoding, plotter.value)
    if (!closed && version === generation) result.value = value
  } catch (e) { if (!closed && version === generation) error.value = String(e) }
  finally { if (!closed && version === generation) busy.value = false }
}
watch(() => [props.runId, props.logId, props.encoding, props.solverType, props.defaultPlotter, props.plotters.map(p => p.id + p.available).join(',')], () => {
  const saved = typeof props.state.plotter_id === 'string' ? props.state.plotter_id : ''
  plotter.value = choices.value.some(p => p.id === saved) ? saved : props.defaultPlotter || choices.value[0]?.id || ''
  void render()
}, { immediate: true })
onUnmounted(() => { closed = true; generation++ })
</script>
<template>
  <div class="solver-progress-plot">
    <div v-if="choices.length" class="analysis-controls"><label>日志作图函数<select v-model="plotter" @change="render"><option v-for="choice in choices" :key="choice.id" :value="choice.id">{{ choice.label }}{{ choice.available ? '' : '（脚本未就绪）' }}</option></select></label><button type="button" :disabled="busy || !selected?.available" @click="render">重新绘图</button><label v-if="result">图片缩放<input v-model.number="zoom" type="range" min="50" max="200" step="10" @input="persist" /></label><a v-if="result" :href="image" :download="result.image_name">下载PNG</a></div>
    <p v-else class="muted">{{ solverType === 'unknown' ? '尚未识别求解器类型，可在上方手动指定或重新识别。' : '该求解器尚未配置日志作图函数。' }}</p>
    <p v-if="selected && !selected.available" class="error">配置的作图脚本尚未就绪。</p>
    <p v-if="busy" role="status">正在生成求解日志图形…</p><p v-if="error" class="error" role="alert">{{ error }}</p>
    <template v-if="result"><div class="solver-progress-image"><img :src="image" :alt="result.label" :style="{ width: `${zoom}%` }" /></div><dl class="solver-progress-summary"><template v-for="(value, key) in result.summary" :key="key"><dt>{{ summaryLabels[key] || key }}</dt><dd>{{ value ?? '—' }}</dd></template></dl></template>
  </div>
</template>
