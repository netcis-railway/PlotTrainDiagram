<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { analysisApi, analysisLabels, defaultLogDisplay, type AnalysisNodeSummary, type AnalysisNodeType, type AnalysisSection, type AnalysisSource, type AnalysisState, type AnalysisTarget, type RunMetadata, type SectionNotes, type SolverLogSummary, type SavedItemMetadata as ItemMetadata } from '../api/analysis'
import { diagramApi, type CreateDiagramView, type SavedDiagramView, type DiagramViewSummary } from '../api/diagram'
import type { Experiment } from '../api/experiments'
import TimetableDiagram from './TimetableDiagram.vue'
import SolverLogAnalysis from './SolverLogAnalysis.vue'
import DelayAnalysis from './DelayAnalysis.vue'
import MetricAnalysis from './MetricAnalysis.vue'
import SavedItemDialog from './SavedItemDialog.vue'
import SavedItemMetadata from './SavedItemMetadata.vue'
import AnalysisSectionNotes from './AnalysisSectionNotes.vue'
import type { DelaySnapshot, SavedMetrics } from '../api/analysis'
const props = defineProps<{ runId: string; source?: AnalysisSource; target?: AnalysisTarget; section?: AnalysisSection; runName?: string; experiment?: Experiment; startView?: 'workspace'|'metrics'; canShift?: boolean }>()
const emit = defineEmits<{ saved: [node: AnalysisNodeSummary]; viewUpdated: [view: DiagramViewSummary]; runUpdated: [value: RunMetadata]; logsChanged: []; close: []; timeShift: [] }>()
const members = computed(() => [...(props.experiment?.members || [])].sort((a, b) => a.run_no - b.run_no || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)))
const logRunId = ref(members.value[0]?.id || props.runId), delayRunId = ref(members.value[0]?.id || props.runId)
const logMember = computed(() => members.value.find(member => member.id === logRunId.value))
const delayMember = computed(() => members.value.find(member => member.id === delayRunId.value))
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
const metricsOpen = ref(props.startView==='metrics' || (!!initial?.metrics && (props.target?.node?.node_type==='metrics' || initial.active_view === 'metrics'))), metricsVisited = ref(props.startView==='metrics' || !!initial?.metrics)
const metricRunId = ref(props.runId), metrics = ref<InstanceType<typeof MetricAnalysis> | null>(null)
const metricInitial = shallowRef<SavedMetrics | undefined>(initial?.metrics || undefined), metricSeed = shallowRef<DelaySnapshot>()
const metricRunName = computed(() => members.value.find(member => member.id === metricRunId.value)?.name || props.runName)
const metricCache = new Map<string, SavedMetrics>()
let workspaceScroll = 0, metricsFocus: HTMLElement | null = null
function cancel() { if (metricsOpen.value) { if (metrics.value) metrics.value.cancel(); else void returnMetrics() } else close() }
async function openMetrics() {
  const id = delayRunId.value
  if (metricRunId.value !== id) {
    const previous = metrics.value?.capture()
    if (previous) metricCache.set(metricRunId.value, previous)
    metricInitial.value = metricCache.get(id)
    metricRunId.value = id
  }
  const seed = delay.value?.capture()?.snapshot || (!props.experiment ? initial?.delay?.snapshot : undefined)
  metricSeed.value = seed?.object.id === id ? seed : undefined
  workspaceScroll = dialog.value?.scrollTop || 0
  metricsFocus = document.activeElement as HTMLElement | null
  metricsVisited.value = true; metricsOpen.value = true
  await nextTick()
  if (dialog.value) dialog.value.scrollTop = 0
  metrics.value?.focus()
}
async function returnMetrics() {
  metricsOpen.value = false
  await nextTick()
  if (dialog.value) dialog.value.scrollTop = workspaceScroll
  metricsFocus?.focus()
}
const expanded = ref<AnalysisSection[]>([...(initial?.expanded_sections || (props.startView==='metrics'?[]:props.target?.logId ? ['log'] : [props.section || 'diagram']))])
const visited = ref(new Set<AnalysisSection>([...expanded.value, ...(initial?.diagram || props.target?.diagram ? ['diagram' as const] : []), ...(initial?.delay ? ['delay' as const] : []), ...(initial?.log.log_id ? ['log' as const] : [])]))
const diagram = ref<InstanceType<typeof TimetableDiagram> | null>(null), log = ref<InstanceType<typeof SolverLogAnalysis> | null>(null), delay = ref<InstanceType<typeof DelayAnalysis> | null>(null)
const saving = ref(false), saveOpen = ref(false), nodeType = ref<AnalysisNodeType>(props.target?.node?.node_type || (props.target?.logId ? 'solver-log' : 'view')), name = ref(''), notes = ref(''), error = ref(''), status = ref('')
const savedItem = computed(() => props.target?.node || props.target?.diagram)
const sectionNotes = ref<SectionNotes>({ ...savedItem.value?.section_notes })
function sectionNodeSaved(value: AnalysisNodeSummary) { sectionNotes.value = { ...value.section_notes }; emit('saved', value) }
function sectionLogSaved(value: SolverLogSummary) { sectionNotes.value = { ...value.section_notes }; emit('logsChanged') }
function sectionViewSaved(value: DiagramViewSummary) { sectionNotes.value = { ...value.section_notes }; emit('viewUpdated', value) }
const metadataName = ref(savedItem.value?.name || ''), metadataNotes = ref(savedItem.value?.notes || '')
const metadataBusy = ref(false), metadataError = ref(''), metadataStatus = ref('')
const savedTypeLabel = computed(() => props.target?.node ? analysisLabels[props.target.node.node_type] : '视图')
async function updateMetadata() {
  if (closed || metadataBusy.value || !metadataName.value.trim() || !savedItem.value) return
  const body = { name: metadataName.value.trim(), notes: metadataNotes.value }
  metadataBusy.value = true; metadataError.value = ''; metadataStatus.value = ''
  try {
    if (props.target?.node) {
      const node = await analysisApi.update(props.runId, props.target.node.id, body)
      if (closed) return
      emit('saved', node)
    } else if (props.target?.diagram) {
      const view = await diagramApi.updateView(props.runId, props.target.diagram.id, body)
      if (closed) return
      emit('viewUpdated', view)
    }
    metadataName.value = body.name
    metadataStatus.value = '名称和备注已保存。'
  } catch (e) { if (!closed) metadataError.value = String(e) }
  finally { metadataBusy.value = false }
}
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
  if (props.experiment) return
  if (metricsOpen.value) type = 'metrics'
  nodeType.value = type; name.value = `${(props.target?.node?.node_type===type ? props.target.node.name : analysisLabels[type])} · ${new Date().toLocaleString()}`.slice(0, 200)
  notes.value = savedItem.value?.notes || ''
  saveOpen.value = true; error.value = ''; status.value = ''
}
function capture(): AnalysisState {
  const view = diagram.value ? diagram.value.capture() : initial?.diagram || (props.target?.diagram ? { name: props.target.diagram.name, state: props.target.diagram.state, snapshot: props.target.diagram.snapshot } as CreateDiagramView : null)
  return JSON.parse(JSON.stringify({ version: 1, expanded_sections: expanded.value, diagram: view, log: log.value?.capture() || initialLog, delay: delay.value ? delay.value.capture() : initial?.delay || null, metrics: metrics.value?.capture() || initial?.metrics || null, active_view: metricsOpen.value ? 'metrics' : 'workspace' }))
}
function submitSave(metadata: ItemMetadata) { name.value = metadata.name; notes.value = metadata.notes; void save() }
async function save() {
  if (props.experiment) return
  if (closed || saving.value || !name.value.trim()) return
  if (diagram.value?.isBusy() || log.value?.isBusy() || delay.value?.isBusy() || metrics.value?.isBusy()) { error.value = '请等待已展开小节的数据读取完成后保存。'; return }
  const state = capture()
  if (metricsOpen.value) nodeType.value = 'metrics'
  if (nodeType.value === 'view' && !state.diagram) { error.value = '请先展开运行图分析并选择可绘制的车站和列车。'; return }
  if (nodeType.value === 'solver-log' && !state.log.log_id) { error.value = '请先展开求解日志并选择日志文件。'; return }
  if (nodeType.value === 'delay' && !state.delay) { error.value = '请先展开延误预览并读取数据。'; return }
  if (nodeType.value === 'metrics' && !state.metrics) { error.value = '请先进入指标分析并读取数据。'; return }
  saving.value = true; error.value = ''
  try {
    const node = await analysisApi.save(props.runId, { node_type: nodeType.value, name: name.value.trim(), notes: notes.value, section_notes: sectionNotes.value, state })
    if (closed) return
    status.value = `已保存${analysisLabels[node.node_type]}：${node.name}，可从run子节点回看。`
    saveOpen.value = false; emit('saved', node)
  } catch (e) { if (!closed) error.value = String(e) }
  finally { saving.value = false }
}
</script>
<template>
  <dialog ref="dialog" class="run-analysis-dialog" :aria-labelledby="metricsOpen ? 'metric-analysis-title' : 'run-analysis-title'" @cancel.prevent="cancel" @close="close">
  <section class="run-analysis" aria-label="运行图分析工作区">
    <div v-show="!metricsOpen" class="analysis-workspace-content">
    <div class="analysis-heading run-analysis-heading">
      <div class="catalog-actions" role="group" aria-label="运行图分析操作">
        <button type="button" @click="close">{{ experiment ? '返回实验管理' : '返回时刻表' }}</button>
        <button type="button" @click="openMetrics">指标分析</button>
        <template v-if="!experiment">
          <button type="button" :disabled="!canShift" @click="emit('timeShift')">整车时间平移</button>
          <button type="button" @click="openSave('view')">保存当前视图</button>
          <button type="button" @click="openSave('solver-log')">保存求解日志展示</button>
          <button type="button" @click="openSave('delay')">保存延误预览</button>
        </template>
      </div>
      <h2 id="run-analysis-title">{{ experiment ? '实验数据分析' : '运行图分析工作区' }}<span v-if="experiment"> · {{ experiment.name }}</span><span v-else-if="runName"> · run: {{ runName }}</span></h2>
    </div>
    <p v-if="experiment" class="muted">三个小节可同时展开。运行图用不同颜色叠加实验成员；求解日志和延误预览可分别选择成员run。</p>
    <p v-else class="muted">三个小节可同时展开。保存节点会记录已读取小节的展示配置、展开状态和运行图/延误数据快照，供后续回看。</p>
    <SavedItemMetadata v-if="savedItem" v-model:name="metadataName" v-model:notes="metadataNotes" :type-label="savedTypeLabel" :busy="metadataBusy" :error="metadataError" :status="metadataStatus" @save="updateMetadata" />
    <p v-if="error && !saveOpen" class="error" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
    <details class="analysis-section" :open="expanded.includes('diagram')" @toggle="toggle('diagram', $event)"><summary>1. 运行图分析（视图）</summary>
      <AnalysisSectionNotes v-if="!experiment && shown && visited.has('diagram')" :run-id="runId" section="diagram" :target-id="savedItem?.id || target?.logId" :target-kind="target?.node ? 'node' : target?.diagram ? 'view' : target?.logId ? 'log' : undefined" :initial="sectionNotes.diagram" @run-updated="emit('runUpdated', $event)" @saved="sectionNodeSaved" @view-updated="sectionViewSaved" @log-updated="sectionLogSaved" />
      <TimetableDiagram v-if="shown && visited.has('diagram')" ref="diagram" embedded managed object-type="run" :object-id="runId" :experiment-id="experiment?.id" :revision="source.revision" :date-base="source.dateBase" :original-date-base="source.originalDateBase" :changes="source.changes" :initial-line="source.initialLine" :saved-view="savedDiagram" @request-save="openSave('view')" />
    </details>
    <details class="analysis-section" :open="expanded.includes('log')" @toggle="toggle('log', $event)"><summary>2. 求解日志</summary>
      <AnalysisSectionNotes v-if="!experiment && shown && visited.has('log')" :run-id="runId" section="log" :target-id="savedItem?.id || target?.logId" :target-kind="target?.node ? 'node' : target?.diagram ? 'view' : target?.logId ? 'log' : undefined" :initial="sectionNotes.log" @run-updated="emit('runUpdated', $event)" @saved="sectionNodeSaved" @view-updated="sectionViewSaved" @log-updated="sectionLogSaved" />
      <div v-if="experiment" class="analysis-run-picker" role="group" aria-label="求解日志run选择">
        <label>求解日志所属run<select v-model="logRunId" aria-label="选择求解日志run"><option v-for="member in members" :key="member.id" :value="member.id" :title="member.classification_path.map(n => n.name).join(' → ')">run_{{ member.run_no }} · {{ member.name }} · {{ member.classification_path.map(n => n.name).join(' → ') }}</option></select></label>
        <p v-if="logMember"><strong>当前显示：</strong>run_{{ logMember.run_no }} · {{ logMember.name }}<span class="analysis-run-path">完整分类路径：{{ logMember.classification_path.map(n => n.name).join(' → ') }}</span></p>
      </div>
      <SolverLogAnalysis v-if="shown && visited.has('log')" :key="logRunId" ref="log" :run-id="logRunId" :initial="experiment ? undefined : initialLog" @imported="emit('logsChanged')" />
    </details>
    <details class="analysis-section" :open="expanded.includes('delay')" @toggle="toggle('delay', $event)"><summary>3. 延误预览</summary>
      <AnalysisSectionNotes v-if="!experiment && shown && visited.has('delay')" :run-id="runId" section="delay" :target-id="savedItem?.id || target?.logId" :target-kind="target?.node ? 'node' : target?.diagram ? 'view' : target?.logId ? 'log' : undefined" :initial="sectionNotes.delay" @run-updated="emit('runUpdated', $event)" @saved="sectionNodeSaved" @view-updated="sectionViewSaved" @log-updated="sectionLogSaved" />
      <div class="catalog-actions"><button type="button" @click="openMetrics">指标分析</button></div>
      <div v-if="experiment" class="analysis-run-picker" role="group" aria-label="延误预览run选择">
        <label>延误预览所属run<select v-model="delayRunId" aria-label="选择延误预览run"><option v-for="member in members" :key="member.id" :value="member.id" :title="member.classification_path.map(n => n.name).join(' → ')">run_{{ member.run_no }} · {{ member.name }} · {{ member.classification_path.map(n => n.name).join(' → ') }}</option></select></label>
        <p v-if="delayMember"><strong>当前分析：</strong>run_{{ delayMember.run_no }} · {{ delayMember.name }}<span class="analysis-run-path">完整分类路径：{{ delayMember.classification_path.map(n => n.name).join(' → ') }}</span></p>
      </div>
      <DelayAnalysis v-if="shown && visited.has('delay')" :key="delayRunId" ref="delay" :run-id="delayRunId" :initial="initial?.delay || undefined" />
    </details>
    </div>
    <MetricAnalysis v-if="shown && metricsVisited" v-show="metricsOpen" :key="metricRunId" ref="metrics" :run-id="metricRunId" :run-name="metricRunName" :initial="metricInitial" :seed="metricSeed" :allow-save="!experiment" @back="returnMetrics" @save="openSave('metrics')">
      <template #save>
        <SavedItemMetadata v-if="savedItem" v-model:name="metadataName" v-model:notes="metadataNotes" :type-label="savedTypeLabel" :busy="metadataBusy" :error="metadataError" :status="metadataStatus" @save="updateMetadata" />
        <p v-if="error && !saveOpen" class="error" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
      </template>
    </MetricAnalysis>
    <SavedItemDialog v-if="saveOpen" :type-label="analysisLabels[nodeType]" :initial-name="name" :initial-notes="notes" :busy="saving" :error="error" @submit="submitSave" @close="saveOpen = false" />
  </section>
  </dialog>
</template>
