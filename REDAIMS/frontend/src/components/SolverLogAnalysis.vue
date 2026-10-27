<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { analysisApi, defaultLogDisplay, type LogDisplay, type SolverLogSummary } from '../api/analysis'
import { solverLogVisualizer } from '../solverLogVisualization'
import SolverLogImport from './SolverLogImport.vue'
const props = defineProps<{ runId: string; initial?: LogDisplay }>()
const emit = defineEmits<{ imported: [] }>()
const state = ref<LogDisplay>(JSON.parse(JSON.stringify(props.initial || defaultLogDisplay())))
const logs = ref<SolverLogSummary[]>([]), text = ref(''), filename = ref(''), error = ref(''), busy = ref(false), importOpen = ref(false)
const viewer = ref<HTMLElement | null>(null)
let generation = 0, closed = false
const lines = computed(() => text.value.split(/\r?\n/))
const filtered = computed(() => lines.value.map((text, i) => ({ text, number: i + 1 })).filter(line => !state.value.search || line.text.toLowerCase().includes(state.value.search.toLowerCase())))
async function load(restore = false) {
  const version = ++generation
  text.value = ''; filename.value = ''; error.value = ''
  if (!state.value.log_id) { busy.value = false; return }
  busy.value = true
  try {
    const result = await analysisApi.logText(props.runId, state.value.log_id, state.value.encoding)
    if (closed || version !== generation) return
    text.value = result.text; filename.value = result.filename
    await nextTick()
    if (viewer.value) { viewer.value.scrollTop = restore ? state.value.scroll_top : 0; viewer.value.scrollLeft = restore ? state.value.scroll_left : 0 }
  } catch (e) { if (!closed && version === generation) error.value = String(e) }
  finally { if (!closed && version === generation) busy.value = false }
}
async function refreshLogs() {
  try { const result = await analysisApi.runLogs(props.runId); if (!closed) logs.value = result }
  catch (e) { if (!closed) error.value = String(e) }
}
async function afterImport() { emit('imported'); await refreshLogs() }
function capture(): LogDisplay {
  return JSON.parse(JSON.stringify({ ...state.value, scroll_top: viewer.value?.scrollTop ?? state.value.scroll_top, scroll_left: viewer.value?.scrollLeft ?? state.value.scroll_left }))
}
defineExpose({ capture, isBusy: () => busy.value })
onMounted(async () => { await Promise.all([refreshLogs(), load(true)]) })
onUnmounted(() => { closed = true; generation++ })
</script>
<template>
  <div class="analysis-controls"><label>求解日志<select v-model="state.log_id" :disabled="busy" @change="load()"><option value="">请选择日志文件</option><option v-for="log in logs" :key="log.id" :value="log.id">{{ log.filename }}</option></select></label>
    <button @click="importOpen = true">导入TXT日志</button>
    <label>文件编码<select v-model="state.encoding" :disabled="busy" @change="load()"><option value="utf-8">UTF-8</option><option value="gb18030">GB18030 / GBK</option></select></label>
    <label>搜索日志<input v-model="state.search" placeholder="筛选包含文本的行" /></label>
    <label class="confirmation"><input v-model="state.wrap" type="checkbox" />自动换行</label>
  </div>
  <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="busy" role="status">正在读取日志…</p>
  <template v-if="filename"><p>{{ filename }} · {{ filtered.length }} / {{ lines.length }}行</p>
    <div ref="viewer" class="analysis-log-text" :class="{ wrap: state.wrap }" tabindex="0" aria-label="求解日志文本">
      <div v-for="line in filtered" :key="line.number"><span class="log-line-number">{{ line.number }}</span><span>{{ line.text || ' ' }}</span></div>
    </div>
    <h4>求解日志可视化</h4>
    <component :is="solverLogVisualizer" v-if="solverLogVisualizer" :text="text" :filename="filename" :state="state.visualization_state" @update:state="state.visualization_state = $event" />
    <p v-else class="empty-state">已预留求解日志可视化接口，后续接入专用作图代码。</p>
  </template><p v-else-if="!busy" class="muted">选择已导入的TXT文本日志，或导入新的日志文件。</p>
  <SolverLogImport v-if="importOpen" :run-id="runId" :run-name="runId" @close="importOpen = false" @imported="afterImport" />
</template>
