<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { analysisApi, analysisLabels, defaultLogDisplay, type AnalysisNodeSummary, type AnalysisNodeType, type AnalysisSection, type AnalysisSource, type AnalysisState, type AnalysisTarget } from '../api/analysis'
import type { CreateDiagramView, SavedDiagramView } from '../api/diagram'
import TimetableDiagram from './TimetableDiagram.vue'
import SolverLogAnalysis from './SolverLogAnalysis.vue'
import DelayAnalysis from './DelayAnalysis.vue'
const props = defineProps<{ runId: string; source?: AnalysisSource; target?: AnalysisTarget; section?: AnalysisSection; runName?: string }>()
const emit = defineEmits<{ saved: [node: AnalysisNodeSummary]; logsChanged: []; close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null), shown = ref(false)
const previousFocus = document.activeElement as HTMLElement | null
let closed = false
function close() {
  if (closed) return
  closed = true
  dialog.value?.close()
  emit('close')
}
onMounted(async () => { await nextTick(); if (!closed) { dialog.value?.showModal(); shown.value = true } })
onUnmounted(() => { closed = true; dialog.value?.close(); previousFocus?.focus() })
const initial = props.target?.node?.state
const expanded = ref<AnalysisSection[]>([...(initial?.expanded_sections || (props.target?.logId ? ['log'] : [props.section || 'diagram']))])
const visited = ref(new Set<AnalysisSection>([...expanded.value, ...(initial?.diagram || props.target?.diagram ? ['diagram' as const] : []), ...(initial?.delay ? ['delay' as const] : []), ...(initial?.log.log_id ? ['log' as const] : [])]))
const diagram = ref<InstanceType<typeof TimetableDiagram> | null>(null), log = ref<InstanceType<typeof SolverLogAnalysis> | null>(null), delay = ref<InstanceType<typeof DelayAnalysis> | null>(null)
const saving = ref(false), saveOpen = ref(false), nodeType = ref<AnalysisNodeType>(props.target?.node?.node_type || (props.target?.logId ? 'solver-log' : 'view')), name = ref(''), error = ref(''), status = ref('')
const source = computed<AnalysisSource>(() => props.source || { revision: '', dateBase: '', originalDateBase: '', changes: [], initialLine: '' })
const savedDiagram = computed<SavedDiagramView | undefined>(() => {
  if (props.target?.diagram) return props.target.diagram
  const value = initial?.diagram
  if (!value) return undefined
  return { id: props.target!.node!.id, run_id: props.runId, name: props.target!.node!.name, created_at: props.target!.node!.created_at, line_ind: value.state.line_ind, station_count: value.state.station_ids.length, train_count: value.state.train_keys.length, highlight_count: value.state.highlighted_keys.length, state: value.state, snapshot: value.snapshot }
})
const initialLog = { ...(initial?.log || defaultLogDisplay()), ...(props.target?.logId ? { log_id: props.target.logId } : {}) }
function toggle(section: AnalysisSection, event: Event) {
  const open = (event.target as HTMLDetailsElement).open
  expanded.value = open ? [...new Set([...expanded.value, section])] : expanded.value.filter(key => key !== section)
  if (open) visited.value = new Set([...visited.value, section])
}
function openSave(type: AnalysisNodeType) {
  nodeType.value = type; name.value = `${props.target?.node?.name || analysisLabels[type]} · ${new Date().toLocaleString()}`.slice(0, 200)
  saveOpen.value = true; error.value = ''; status.value = ''
}
function capture(): AnalysisState {
  const view = diagram.value ? diagram.value.capture() : initial?.diagram || (props.target?.diagram ? { name: props.target.diagram.name, state: props.target.diagram.state, snapshot: props.target.diagram.snapshot } as CreateDiagramView : null)
  return JSON.parse(JSON.stringify({ version: 1, expanded_sections: expanded.value, diagram: view, log: log.value?.capture() || initialLog, delay: delay.value ? delay.value.capture() : initial?.delay || null }))
}
async function save() {
  if (closed || saving.value || !name.value.trim()) return
  if (diagram.value?.isBusy() || log.value?.isBusy() || delay.value?.isBusy()) { error.value = '请等待已展开小节的数据读取完成后保存。'; return }
  const state = capture()
  if (nodeType.value === 'view' && !state.diagram) { error.value = '请先展开运行图分析并选择可绘制的车站和列车。'; return }
  if (nodeType.value === 'solver-log' && !state.log.log_id) { error.value = '请先展开求解日志并选择日志文件。'; return }
  if (nodeType.value === 'delay' && !state.delay) { error.value = '请先展开延误分析并读取数据。'; return }
  saving.value = true; error.value = ''
  try {
    const node = await analysisApi.save(props.runId, { node_type: nodeType.value, name: name.value.trim(), state })
    if (closed) return
    status.value = `已保存${analysisLabels[node.node_type]}：${node.name}，可从run子节点回看。`
    saveOpen.value = false; emit('saved', node)
  } catch (e) { if (!closed) error.value = String(e) }
  finally { saving.value = false }
}
</script>
<template>
  <dialog ref="dialog" class="run-analysis-dialog" aria-labelledby="run-analysis-title" @cancel.prevent="close" @close="close">
  <section class="run-analysis" aria-label="run分析工作区">
    <div class="analysis-heading"><h2 id="run-analysis-title">run分析工作区<span v-if="runName"> · {{ runName }}</span></h2><div class="catalog-actions"><button type="button" @click="close">返回时刻表</button><button @click="openSave('view')">保存当前视图</button><button @click="openSave('solver-log')">保存求解日志展示</button><button @click="openSave('delay')">保存延误分析</button></div></div>
    <p v-if="target?.node" class="category-context">{{ analysisLabels[target.node.node_type] }}：<strong>{{ target.node.name }}</strong> · {{ new Date(target.node.created_at).toLocaleString() }}</p>
    <p class="muted">三个小节可同时展开。保存节点会记录已读取小节的展示配置、展开状态和运行图/延误数据快照，供后续回看。</p>
    <form v-if="saveOpen" class="diagram-save-view" @submit.prevent="save"><label>子节点类型<select v-model="nodeType" :disabled="saving"><option v-for="(label, key) in analysisLabels" :key="key" :value="key">{{ label }}</option></select></label><label>名称<input v-model="name" required maxlength="200" :disabled="saving" /></label><button :disabled="saving || !name.trim()">{{ saving ? '正在保存…' : '保存' }}</button> <button type="button" :disabled="saving" @click="saveOpen = false">取消</button></form>
    <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
    <details class="analysis-section" :open="expanded.includes('diagram')" @toggle="toggle('diagram', $event)"><summary>1. 运行图分析（视图）</summary>
      <TimetableDiagram v-if="shown && visited.has('diagram')" ref="diagram" embedded managed object-type="run" :object-id="runId" :revision="source.revision" :date-base="source.dateBase" :original-date-base="source.originalDateBase" :changes="source.changes" :initial-line="source.initialLine" :saved-view="savedDiagram" @request-save="openSave('view')" />
    </details>
    <details class="analysis-section" :open="expanded.includes('log')" @toggle="toggle('log', $event)"><summary>2. 求解日志</summary>
      <SolverLogAnalysis v-if="shown && visited.has('log')" ref="log" :run-id="runId" :initial="initialLog" @imported="emit('logsChanged')" />
    </details>
    <details class="analysis-section" :open="expanded.includes('delay')" @toggle="toggle('delay', $event)"><summary>3. 延误分析</summary>
      <DelayAnalysis v-if="shown && visited.has('delay')" ref="delay" :run-id="runId" :initial="initial?.delay || undefined" />
    </details>
  </section>
  </dialog>
</template>
