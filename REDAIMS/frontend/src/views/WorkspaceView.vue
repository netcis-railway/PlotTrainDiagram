<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import RunAnalysis from '../components/RunAnalysis.vue'
import ExperimentManager from '../components/ExperimentManager.vue'
import { experimentApi, type Experiment } from '../api/experiments'
import { analysisApi, analysisLabels, type AnalysisNodeSummary, type SavedAnalysisNode, type SolverLogSummary } from '../api/analysis'
import { diagramApi, type DiagramViewSummary, type SavedDiagramView } from '../api/diagram'
import CatalogContextMenu from '../components/CatalogContextMenu.vue'
import SolverLogImport from '../components/SolverLogImport.vue'
import { catalogActions, type CatalogActionId, type TimetableActionRequest } from '../catalogActions'
import ImportPreview from '../components/ImportPreview.vue'
import CatalogSplitter from '../components/CatalogSplitter.vue'
import BaseDiagramInfo from '../components/BaseDiagramInfo.vue'
import { baseReferenceId, viewReferenceId, analysisReferenceId, logReferenceId, experimentEntityId, experimentTreeNodes, type CatalogTreeNode } from '../types/catalogTree'
import CategoryTree from '../components/CategoryTree.vue'
import BaseImport from '../components/BaseImport.vue'
import LegacyBaseMigration from '../components/LegacyBaseMigration.vue'
import RunDetails from '../components/RunDetails.vue'
import RunImport from '../components/RunImport.vue'
import { baseApi, type BaseTimetable, type Resolution } from '../api/baseImport'
import DeleteCategory from '../components/DeleteCategory.vue'
import { deletionApi, type UngroupedRun } from '../api/client'
import { api, type CatalogNode, type Kind } from '../api/client'

const props = defineProps<{ view: 'catalog' | 'import' | 'run-import'; editorTarget?: import('../editorWindow').EditorTarget }>()
const editorKey = computed(() => props.editorTarget?.transfer || '')
const emit = defineEmits<{ openImport: []; openRunImport: []; showCatalog: [id: string] }>()
const bases = ref<BaseTimetable[]>([])
const resolution = ref<Resolution | null>(null)
const tabs = [
  { id: 'view', title: '查看编辑' }, { id: 'new', title: '新建' },
  { id: 'delete', title: '删除' }, { id: 'base', title: '基本图' },
  { id: 'experiments', title: 'Experiment 实验' },
] as const
type Tab = typeof tabs[number]['id']
const activeTab = ref<Tab>('view')
function restoreWidth() {
  try {
    const width = Number(localStorage.getItem('redaims.catalog-width') || 280)
    return Number.isFinite(width) ? Math.max(180, Math.min(520, width)) : 280
  } catch { return 280 }
}
const sidebarWidth = ref(restoreWidth())
watch(sidebarWidth, width => {
  try { localStorage.setItem('redaims.catalog-width', String(width)) } catch { /* in-memory fallback */ }
})
function tabKeydown(event: KeyboardEvent, index: number) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
  switchTab(tabs[next]!.id)
  const target = event.currentTarget as HTMLElement
  target.parentElement?.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus()
}

type CreationKind = Kind | 'run'
function switchTab(tab: Tab) {
  closeContextMenu(); actionRequest.value = undefined
  if (tab !== 'experiments') { selectedExperimentId.value = ''; experimentSelection.value = '' }
  activeTab.value = tab
}
function selectExperiment(id: string) {
  if (!id) { selectedExperimentId.value = ''; experimentSelection.value = ''; activeTab.value = 'experiments'; return }
  const entry = treeNodes.value.find(n => n.id === experimentEntityId(id))
  if (entry) select(entry)
}
function afterExperimentChanged(value: Experiment | null, sourceId: string, reveal: boolean) {
  experimentListVersion++
  experiments.value = experiments.value.filter(e => e.id !== (value?.id || sourceId))
  if (value) experiments.value.push(value)
  if (reveal) selectExperiment(value?.id || '')
}
function replaceExperiments(items: Experiment[]) {
  experiments.value = items
  if (selectedExperimentId.value && !items.some(e => e.id === selectedExperimentId.value)) { selectedExperimentId.value = ''; experimentSelection.value = '' }
  if (experimentSelection.value && !treeNodes.value.some(n => n.id === experimentSelection.value)) experimentSelection.value = selectedExperimentId.value ? experimentEntityId(selectedExperimentId.value) : ''
}
function openExperimentRun(id: string) {
  const entry = treeNodes.value.find(n => n.id === id)
  if (entry) select(entry)
}
const labels: Record<CreationKind, string> = { user: '研究员', network: '路网', scenario: '场景', case: '案例', algorithm: '算法', batch: '批次', run: 'run' }
const parents: Record<CreationKind, Kind | null> = { user: null, network: 'user', scenario: 'network', case: 'scenario', algorithm: 'case', batch: 'algorithm', run: 'batch' }
const nodes = ref<CatalogNode[]>([])
const ungrouped = ref<UngroupedRun[]>([])
const selected = ref('')
const selectedBaseId = ref('')
const experiments = ref<Experiment[]>([]), selectedExperimentId = ref(''), experimentSelection = ref('')
let experimentListVersion = 0
const savedViews = ref<DiagramViewSummary[]>([]), selectedViewId = ref(''), openedView = ref<SavedDiagramView | null>(null), viewLoading = ref(false)
const analysisNodes = ref<AnalysisNodeSummary[]>([]), solverLogs = ref<SolverLogSummary[]>([])
const selectedAnalysisId = ref(''), selectedLogId = ref(''), openedAnalysis = ref<SavedAnalysisNode | null>(null), openedLogId = ref('')
const selectedAnalysis = computed(() => analysisNodes.value.find(node => node.id === selectedAnalysisId.value))
const selectedLog = computed(() => solverLogs.value.find(log => log.id === selectedLogId.value))
const isAnalysisChild = computed(() => !!(selectedViewId.value || selectedAnalysisId.value || selectedLogId.value))
let viewGeneration = 0, viewListVersion = 0
const contextMenu = ref<{ x: number; y: number; nodeId: string } | null>(null)
const logRunId = ref('')
const actionRequest = ref<TimetableActionRequest>()
let actionSequence = 0
const kind = ref<CreationKind>('user')
const parentId = ref('')
const name = ref('')
const notes = ref('')
const draftNotes = ref('')
const draftName = ref('')
const status = ref('正在连接')
const error = ref('')
const busy = ref(false)
const current = computed(() => nodes.value.find(n => n.id === selected.value) || (ungrouped.value.some(r => r.id === selected.value) ? { id: selected.value, kind: 'run' as const, parent_id: null, name: ungrouped.value.find(r => r.id === selected.value)!.name, notes: '' } : undefined))
const selectedDiagramView = computed(() => savedViews.value.find(view => view.id === selectedViewId.value))
const selectedBase = computed(() => bases.value.find(base => base.id === selectedBaseId.value))
const currentBaseId = computed(() => selectedBaseId.value || (resolution.value?.requested_category_id === (current.value?.kind === 'run' ? current.value.parent_id : selected.value) ? resolution.value.effective.base_tt_id || '' : ''))
const treeNodes = computed<CatalogTreeNode[]>(() => {
  const items: CatalogTreeNode[] = bases.value.map(base => ({
    id: baseReferenceId(base.owner_category_id, base.id), parent_id: base.owner_category_id,
    name: `基本图：${base.name}`, kind: 'run', notes: '',
    baseReference: { scopeId: base.owner_category_id, runId: base.id, inherited: false },
  }))
  const viewItems: CatalogTreeNode[] = savedViews.value.map(view => ({
    id: viewReferenceId(view.run_id, view.id), parent_id: view.run_id, name: `视图：${view.name}`, kind: 'run', notes: '',
    viewReference: { runId: view.run_id, viewId: view.id },
  }))
  const analysisItems: CatalogTreeNode[] = analysisNodes.value.map(node => ({
    id: analysisReferenceId(node.run_id, node.id), parent_id: node.run_id, name: `${analysisLabels[node.node_type]}：${node.name}`, kind: 'run', notes: '',
    analysisReference: { runId: node.run_id, nodeId: node.id, nodeType: node.node_type },
  }))
  const logItems: CatalogTreeNode[] = solverLogs.value.map(log => ({
    id: logReferenceId(log.run_id, log.id), parent_id: log.run_id, name: `求解日志：${log.filename}`, kind: 'run', notes: '',
    logReference: { runId: log.run_id, logId: log.id },
  }))
  const ungroupedItems: CatalogTreeNode[] = ungrouped.value.map(run => ({ id: run.id, kind: 'run', parent_id: null, name: `未分组run：${run.name}`, notes: '' }))
  return [...items, ...nodes.value, ...ungroupedItems, ...viewItems, ...logItems, ...analysisItems,
    ...experimentTreeNodes(experiments.value, new Set([...nodes.value.filter(n => n.kind === 'run').map(n => n.id), ...ungrouped.value.map(r => r.id)]))]
})
const selectedTreeId = computed(() => experimentSelection.value || (selectedBaseId.value ? baseReferenceId(selected.value, selectedBaseId.value) : selectedViewId.value ? viewReferenceId(selected.value, selectedViewId.value) : selectedAnalysisId.value ? analysisReferenceId(selected.value, selectedAnalysisId.value) : selectedLogId.value ? logReferenceId(selected.value, selectedLogId.value) : selected.value))
const selectedEntry = computed(() => treeNodes.value.find(node => node.id === selectedTreeId.value) || current.value)
const actions = computed(() => catalogActions(selectedEntry.value, !!currentBaseId.value).map(action => ({ ...action, disabled: !!action.disabled || busy.value })))
function closeContextMenu() { contextMenu.value = null }
function openContextMenu(node: CatalogTreeNode, event: MouseEvent | KeyboardEvent) {
  select(node, false)
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const mouse = 'clientX' in event && (event.clientX !== 0 || event.clientY !== 0)
  contextMenu.value = { nodeId: node.id, x: mouse ? event.clientX : bounds.left + 24, y: mouse ? event.clientY : bounds.bottom }
}
function performAction(id: CatalogActionId) {
  const action = actions.value.find(item => item.id === id)
  if (!action || action.disabled || busy.value || !current.value) return
  closeContextMenu()
  if (id === 'open-experiment') { activeTab.value = 'experiments'; return }
  if (id === 'open-analysis' && selectedAnalysis.value) { void openAnalysisNode(selectedAnalysis.value); return }
  if (id === 'open-log' && selectedLog.value) { openedLogId.value = selectedLog.value.id; return }
  if (id === 'open-view' && selectedDiagramView.value) { void openSavedView(selectedDiagramView.value); return }
  if (id === 'import-base') { emit('openImport'); return }
  if (id === 'import-run') { emit('openRunImport'); return }
  if (id === 'import-log') { logRunId.value = current.value.id; return }
  const kind = id === 'edit-run' || id === 'run-diagram' || id === 'delay-analysis' ? 'run' : 'base'
  const objectId = kind === 'run' ? current.value.id : currentBaseId.value
  if (!objectId) return
  activeTab.value = kind === 'base' && !selectedBaseId.value ? 'base' : 'view'
  actionRequest.value = { sequence: ++actionSequence, kind, objectId, action: id === 'delay-analysis' ? 'delay' : id === 'delete-base' ? 'delete' : id.endsWith('diagram') ? 'diagram' : 'edit' }
}
watch(() => props.view, closeContextMenu)
watch(selectedTreeId, closeContextMenu, { flush: 'sync' })
function treePath(id: string): string {
  const entry = treeNodes.value.find(node => node.id === id)
  if (entry?.experimentReference) {
    const reference = entry.experimentReference
    const experiment = experiments.value.find(e => e.id === reference.experimentId)
    return `${categoryPath(entry.parent_id!)} → 实验：${experiment?.name || ''}${reference.virtual ? `（引用，实体存放：${categoryPath(reference.ownerId)}）` : ''}`
  }
  if (entry?.analysisReference || entry?.logReference) return `${categoryPath(entry.parent_id!)} → ${entry.name}`
  const view = entry?.viewReference
  if (view) return `${categoryPath(view.runId)} → 视图：${savedViews.value.find(item => item.id === view.viewId)?.name || ''}`
  const item = treeNodes.value.find(n => n.id === id)?.baseReference
  if (!item) return categoryPath(id)
  return `${categoryPath(item.scopeId)} → 基本图：${bases.value.find(b => b.id === item.runId)?.name || ''}`
}
function categoryPath(id: string): string {
  const parts: string[] = []
  const visited = new Set<string>()
  let node = nodes.value.find(item => item.id === id)
  if (!node) { const run = ungrouped.value.find(item => item.id === id); return run ? `未分组run：${run.name}` : '' }
  while (node && !visited.has(node.id)) {
    visited.add(node.id)
    parts.unshift(`${labels[node.kind]}：${node.name}`)
    node = nodes.value.find(item => item.id === node?.parent_id)
  }
  return parts.join(' → ')
}
const currentPath = computed(() => current.value ? categoryPath(current.value.id) : '尚未选择分类')
const creationParentNodes = computed(() => {
  const chain: CatalogNode[] = []
  const visited = new Set<string>()
  let node = parents[kind.value] ? nodes.value.find(item => item.id === parentId.value) : undefined
  while (node && !visited.has(node.id)) {
    visited.add(node.id)
    chain.unshift(node)
    node = nodes.value.find(item => item.id === node?.parent_id)
  }
  return chain
})
const creationParentPath = computed(() => !parents[kind.value]
  ? '根目录（新建研究员）'
  : parentId.value ? categoryPath(parentId.value) : '请先选择上级分类')
const parentOptions = computed(() => nodes.value.filter(n => n.kind === parents[kind.value]))
let resolutionVersion = 0
async function refreshResolution() {
  const version = ++resolutionVersion
  resolution.value = null
  const node = current.value
  const id = node?.kind === 'run' ? node.parent_id : node?.id
  if (!id) return
  try {
    const value = await baseApi.resolution(id)
    if (version === resolutionVersion) {
      if (node?.kind === 'run') { value.local_base = null; if (value.effective.base_tt_id) value.effective.mode = 'inherited' }
      resolution.value = value
    }
  } catch (e) { if (version === resolutionVersion) error.value = String(e) }
}
watch(selected, refreshResolution, { flush: 'sync' })
async function refresh() {
  const viewsVersion = ++viewListVersion
  const experimentsVersion = ++experimentListVersion
  try {
    const [, catalog, ordinaryRuns, baseItems, ungroupedRuns, viewItems, analysisItems, logItems, experimentItems] = await Promise.all([
      api.health(), api.catalog(), baseApi.runs(), baseApi.bases(), deletionApi.ungrouped(), diagramApi.views(), analysisApi.nodes(), analysisApi.logs(), experimentApi.list(),
    ])
    nodes.value = [...catalog, ...ordinaryRuns.filter(r => r.batch_id).map(r => ({
      id: r.id, parent_id: r.batch_id, name: `${r.name} / run_${r.run_no}`, kind: 'run' as const, notes: '',
    }))]
    bases.value = baseItems; ungrouped.value = ungroupedRuns
    if (experimentsVersion === experimentListVersion) replaceExperiments(experimentItems)
    if (viewsVersion === viewListVersion) { savedViews.value = viewItems; analysisNodes.value = analysisItems; solverLogs.value = logItems }
    if ((selectedViewId.value && !savedViews.value.some(view => view.id === selectedViewId.value)) || (selectedAnalysisId.value && !analysisNodes.value.some(node => node.id === selectedAnalysisId.value)) || (selectedLogId.value && !solverLogs.value.some(log => log.id === selectedLogId.value))) {
      viewGeneration++; selectedViewId.value = ''; selectedAnalysisId.value = ''; selectedLogId.value = ''; openedAnalysis.value = null; openedView.value = null; openedLogId.value = ''; viewLoading.value = false
    }
    if (selectedBaseId.value && !baseItems.some(base => base.id === selectedBaseId.value && base.owner_category_id === selected.value)) selectedBaseId.value = ''
    closeContextMenu()
    if (selected.value && !current.value) { selected.value = ''; parentId.value = ''; kind.value = 'user' }
    status.value = '服务已连接'; error.value = ''; await refreshResolution()
  } catch (e) { status.value = '连接失败'; error.value = String(e) }
}
async function refreshSavedViews() {
  const version = ++viewListVersion
  const experimentsVersion = ++experimentListVersion
  try { const [result, analyses, logs, experimentItems] = await Promise.all([diagramApi.views(), analysisApi.nodes(), analysisApi.logs(), experimentApi.list()]); if (version === viewListVersion) { savedViews.value = result; analysisNodes.value = analyses; solverLogs.value = logs }; if (experimentsVersion === experimentListVersion) replaceExperiments(experimentItems) }
  catch { /* The explicit workspace refresh reports connection failures. */ }
}
function afterViewSaved(view: DiagramViewSummary) {
  viewListVersion++
  savedViews.value = [...savedViews.value.filter(item => item.id !== view.id), view]
  status.value = `已保存运行图视图：${view.name}`
}
function afterAnalysisSaved(node: AnalysisNodeSummary) {
  viewListVersion++; analysisNodes.value = [...analysisNodes.value.filter(item => item.id !== node.id), node]
  status.value = `已保存${analysisLabels[node.node_type]}：${node.name}`
}
async function afterLogImported() { status.value = '已保存求解日志'; await refreshSavedViews() }
function closeAnalysisWindow() {
  viewGeneration++; viewLoading.value = false; openedAnalysis.value = null; openedView.value = null; openedLogId.value = ''
  selectedAnalysisId.value = ''; selectedViewId.value = ''; selectedLogId.value = ''
}
async function openAnalysisNode(node: AnalysisNodeSummary) {
  const version = ++viewGeneration
  viewLoading.value = true; error.value = ''
  try { const result = await analysisApi.node(node.run_id, node.id); if (version === viewGeneration) openedAnalysis.value = result }
  catch (e) { if (version === viewGeneration) error.value = String(e) }
  finally { if (version === viewGeneration) viewLoading.value = false }
}
async function openSavedView(view: DiagramViewSummary) {
  const version = ++viewGeneration
  viewLoading.value = true; error.value = ''
  try {
    const result = await diagramApi.view(view.run_id, view.id)
    if (version === viewGeneration) openedView.value = result
  } catch (e) { if (version === viewGeneration) error.value = String(e) }
  finally { if (version === viewGeneration) viewLoading.value = false }
}
async function afterRunImported(id: string) {
  await refresh()
  const run = nodes.value.find(node => node.id === id)
  if (run) select(run)
  activeTab.value = 'view'; status.value = 'run 导入成功，可查阅和编辑时刻表'
  emit('showCatalog', id)
}
async function afterDataChanged(owner: string | null) {
  const wasBase = activeTab.value === 'base' || !!selectedBaseId.value
  const baseId = selectedBaseId.value
  actionRequest.value = undefined
  await refresh()
  if (wasBase && owner) {
    selected.value = owner
    selectedBaseId.value = bases.value.some(base => base.id === baseId && base.owner_category_id === owner) ? baseId : ''
    await refreshResolution()
  }
}
async function createNode() {
  if (kind.value === 'run') return
  busy.value = true; error.value = ''
  try {
    const node = await api.create({ kind: kind.value, parent_id: parents[kind.value] ? parentId.value : null, name: name.value, notes: notes.value })
    nodes.value.push(node); select(node); name.value = ''; notes.value = ''; activeTab.value = 'view'; await refreshResolution()
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
function setCurrent(node: CatalogNode) {
  selectedExperimentId.value = ''; experimentSelection.value = ''
  viewGeneration++; viewLoading.value = false; openedView.value = null; selectedViewId.value = ''
  selectedAnalysisId.value = ''; selectedLogId.value = ''; openedAnalysis.value = null; openedLogId.value = ''
  actionRequest.value = undefined; selectedBaseId.value = ''; selected.value = node.id
  draftName.value = node.name; draftNotes.value = node.notes
}
function select(entry: CatalogTreeNode, openView = true) {
  closeContextMenu()
  if (entry.experimentReference) {
    const reference = entry.experimentReference
    const parent = treeNodes.value.find(n => n.id === entry.parent_id)
    if (!parent) return
    select(parent, false); selectedExperimentId.value = reference.experimentId; experimentSelection.value = entry.id
    activeTab.value = 'experiments'; return
  }
  const node = entry.analysisReference || entry.logReference ? treeNodes.value.find(item => item.id === entry.parent_id) : entry.viewReference ? treeNodes.value.find(item => item.id === entry.viewReference!.runId) : entry.baseReference ? nodes.value.find(n => n.id === entry.baseReference!.scopeId) : entry
  if (!node) return
  setCurrent(node)
  selectedBaseId.value = entry.baseReference?.runId || ''
  selectedViewId.value = entry.viewReference?.viewId || ''
  selectedAnalysisId.value = entry.analysisReference?.nodeId || ''; selectedLogId.value = entry.logReference?.logId || ''
  if (openView && selectedAnalysis.value) void openAnalysisNode(selectedAnalysis.value)
  if (openView && selectedLog.value) openedLogId.value = selectedLog.value.id
  if (openView && selectedDiagramView.value) void openSavedView(selectedDiagramView.value)
  activeTab.value = 'view'

  const children: Record<CreationKind, CreationKind> = {
    user: 'network', network: 'scenario', scenario: 'case', case: 'algorithm',
    algorithm: 'batch', batch: 'run', run: 'run',
  }
  kind.value = children[node.kind]
  parentId.value = node.kind === 'run' ? node.parent_id || '' : node.id
}
function selectParent() {
  const parent = nodes.value.find(node => node.id === parentId.value)
  if (parent) setCurrent(parent)
}
function changeKind() {
  // Reuse the matching ancestor of the selected node, without changing creation type.
  let ancestor = current.value
  const expected = parents[kind.value]
  while (ancestor && ancestor.kind !== expected) {
    ancestor = nodes.value.find(node => node.id === ancestor?.parent_id)
  }
  parentId.value = ancestor?.id ?? ''
  if (ancestor) setCurrent(ancestor)
}
async function saveCategory() {
  if (busy.value || !current.value || current.value.kind === 'run' || selectedBaseId.value || isAnalysisChild.value || experimentSelection.value) return
  const newName = draftName.value.trim()
  if (!newName) { error.value = '类别名称不能为空'; return }
  busy.value = true; error.value = ''
  const targetId = current.value.id
  const changes = { name: newName, notes: draftNotes.value }
  try {
    const saved = await api.update(targetId, changes)
    nodes.value = nodes.value.map(node => node.id === targetId ? { ...node, ...saved } : node)
    if (selectedTreeId.value === targetId) {
      draftName.value = saved.name; draftNotes.value = saved.notes
      status.value = `已保存类别：${saved.name}`
    }
    await refreshResolution()
  }
  catch (e) { if (selectedTreeId.value === targetId) error.value = String(e) } finally { busy.value = false }
}
async function afterDelete() { selectedAnalysisId.value = ''; selectedLogId.value = ''; openedAnalysis.value = null; openedLogId.value = ''; selectedViewId.value = ''; selectedBaseId.value = ''; selected.value = ''; parentId.value = ''; kind.value = 'user'; activeTab.value = 'view'; await refresh() }
let targetVersion = 0
async function openRequestedEditor() {
  const version = ++targetVersion
  const target = props.editorTarget
  if (!target) return
  closeContextMenu(); selectedViewId.value = ''; selectedAnalysisId.value = ''; selectedLogId.value = ''; openedAnalysis.value = null; openedLogId.value = ''; openedView.value = null; actionRequest.value = undefined
  await refresh()
  if (version !== targetVersion) return
  if (target.kind === 'base') {
    const base = bases.value.find(b => b.id === target.id)
    if (!base) { error.value = '拟嵌回的基本图已不存在'; return }
    selected.value = base.owner_category_id; selectedBaseId.value = base.id
    activeTab.value = 'view'
    await refreshResolution()
  } else {
    if (!nodes.value.some(n => n.id === target.id && n.kind === 'run') && !ungrouped.value.some(r => r.id === target.id)) { error.value = '拟嵌回的 run 已不存在'; return }
    selectedBaseId.value = ''; selected.value = target.id; activeTab.value = 'view'
  }
}
watch(() => props.editorTarget, openRequestedEditor)
onMounted(() => { window.addEventListener('focus', refreshSavedViews); if (props.editorTarget) void openRequestedEditor(); else void refresh() })
onUnmounted(() => { viewGeneration++; viewListVersion++; window.removeEventListener('focus', refreshSavedViews) })
</script>

<template>

  <CatalogContextMenu v-if="contextMenu" :key="contextMenu.nodeId" :actions="actions" :name="selectedEntry?.name || ''" :x="contextMenu.x" :y="contextMenu.y" @action="performAction" @close="closeContextMenu" />
  <SolverLogImport v-if="logRunId" :key="logRunId" :run-id="logRunId" :run-name="nodes.find(node => node.id === logRunId)?.name || logRunId" @close="logRunId = ''" @imported="afterLogImported" />
  <div class="workspace-status"><span>工作区</span><span role="status">{{ status }}</span></div>
  <main class="workspace" :class="{ 'import-workspace': view !== 'catalog' }" :style="{ '--catalog-width': `${sidebarWidth}px` }">
    <aside v-show="view === 'catalog'" id="catalog-navigation" class="category-sidebar">
      <div class="category-sidebar-heading"><h2>项目分类</h2><button @click="refresh" :disabled="busy">刷新</button></div>
      <button type="button" @click="selectExperiment('')">新建 Experiment 实验</button>
      <p v-if="!nodes.length">尚无分类，请点击“新建”创建研究员。</p>
      <CategoryTree :nodes="treeNodes" :selected="selectedTreeId" :labels="labels" :path="treePath" context-menu @select="select" @contextmenu="openContextMenu" />
    </aside>
    <CatalogSplitter v-show="view === 'catalog'" v-model="sidebarWidth" />
    <section>
      <p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="viewLoading" role="status">正在读取保存视图…</p>
      <div v-if="view === 'catalog'" class="catalog-editor">
        <div class="catalog-tabs" role="tablist" aria-label="分类管理操作">
          <button v-for="(tab, index) in tabs" :id="`catalog-tab-${tab.id}`" :key="tab.id" type="button" role="tab"
            :aria-selected="activeTab === tab.id" :aria-controls="`catalog-panel-${tab.id}`" :tabindex="activeTab === tab.id ? 0 : -1"
            :class="{ active: activeTab === tab.id }" @click="switchTab(tab.id)" @keydown="tabKeydown($event, index)">{{ tab.title }}</button>
        </div>
        <article v-if="activeTab === 'view'" id="catalog-panel-view" role="tabpanel" aria-labelledby="catalog-tab-view" tabindex="0">
          <template v-if="current">
            <h2>查看编辑：{{ selectedAnalysis ? analysisLabels[selectedAnalysis.node_type] + ' ' + selectedAnalysis.name : selectedLog ? '求解日志 ' + selectedLog.filename : selectedDiagramView ? '视图 ' + selectedDiagramView.name : selectedBase ? '基本图 ' + selectedBase.name : labels[current.kind] + ' ' + current.name }}</h2>
            <p class="category-context"><strong>完整分类路径：</strong>{{ selectedBase || isAnalysisChild ? treePath(selectedTreeId) : currentPath }}</p>
            <div class="catalog-actions" role="group" aria-label="所选条目操作"><strong>操作</strong><button v-for="action in actions" :key="action.id" type="button" :disabled="busy || action.disabled" :title="action.title" :class="{ danger: action.danger }" @click="performAction(action.id)">{{ action.label }}</button></div>
            <form v-if="!selectedBase && !isAnalysisChild && current.kind !== 'run'" aria-label="编辑分类" @submit.prevent="saveCategory">
              <label>类别名称<input v-model="draftName" required maxlength="200" :disabled="busy" /></label>
              <label>分类备注<textarea v-model="draftNotes" maxlength="20000" :disabled="busy" /></label><button :disabled="busy || !draftName.trim()">{{ busy ? '正在保存…' : '保存修改' }}</button>
            </form>
            <BaseDiagramInfo v-if="selectedBase" :key="selectedBase.id + editorKey" :base-id="selectedBase.id" :scope-path="currentPath" :resolution="resolution" :nodes="nodes" :action-request="actionRequest" @changed="afterDataChanged" />
            <template v-else-if="current.kind === 'run'">
              <RunDetails :key="current.id + editorKey" :run-id="current.id" :nodes="nodes" :action-request="actionRequest" @view-saved="afterViewSaved" @analysis-saved="afterAnalysisSaved" @logs-changed="refreshSavedViews" @changed="afterDataChanged" />
              <RunAnalysis v-if="openedAnalysis || openedView || openedLogId" :key="openedAnalysis?.id || openedView?.id || openedLogId" :run-id="current.id" :run-name="current.name" @close="closeAnalysisWindow" :target="{ node: openedAnalysis || undefined, diagram: openedView || undefined, logId: openedLogId || undefined }" @saved="afterAnalysisSaved" @logs-changed="refreshSavedViews" />
            </template>
            <div v-else class="category-context"><p>当前有效基本图：{{ resolution?.effective.name || '无' }} <span v-if="resolution?.effective.base_tt_id">（{{ resolution.effective.mode === 'physical' ? '本级存储' : '回溯上级' }}）</span></p></div>
          </template>
          <div v-else class="empty-state"><h2>查看编辑</h2><p>从左侧选择分类查看和编辑，或创建新的分类。</p><button @click="activeTab = 'new'">新建分类</button></div>
          <details class="ungrouped-runs"><summary>未分组 run（{{ ungrouped.length }}）</summary><p v-if="!ungrouped.length">暂无未分组 run。</p><ul><li v-for="run in ungrouped" :key="run.id">{{ run.name }} / {{ run.run_no }} · 原归属：{{ run.origin_path.map(n => n.name).join(' → ') }}</li></ul></details>
        </article>
      <article v-if="activeTab === 'new'" id="catalog-panel-new" role="tabpanel" aria-labelledby="catalog-tab-new" tabindex="0"><h2>新建分类：{{ labels[kind] }}</h2><p>按研究员 → 路网 → 场景 → 案例 → 算法 → 批次 → run 组织运行方案。当前新建级别：<strong>{{ labels[kind] }}</strong>。</p>
        <div class="category-context" aria-live="polite">
          <p><strong>当前选中分类路径：</strong>{{ currentPath }}</p>
          <p><strong>新分类归属路径：</strong>{{ creationParentPath }}</p>
        </div>
        <form @submit.prevent="createNode">
          <div v-if="parents[kind]" class="parent-selector">
            <label for="creation-parent">上级类别</label>
            <div v-if="creationParentNodes.length" class="parent-path-table-wrap">
              <table class="parent-path-table" aria-label="上级分类完整路径">
                <thead><tr><th v-for="node in creationParentNodes" :key="node.id" scope="col">{{ labels[node.kind] }}</th></tr></thead>
                <tbody><tr><td v-for="node in creationParentNodes" :key="node.id">{{ node.name }}</td></tr></tbody>
              </table>
            </div>
            <p v-else class="muted">请先选择上级分类</p>
            <select id="creation-parent" v-model="parentId" required @change="selectParent"><option disabled value="">请选择上级分类</option><option v-for="node in parentOptions" :key="node.id" :value="node.id">{{ node.name }}</option></select>
          </div>
          <label>新建类别 类型<select v-model="kind" @change="changeKind"><option v-for="(label, key) in labels" :key="key" :value="key">{{ label }}</option></select></label>
          <p v-if="kind === 'run'" class="muted" role="status">run 通过导入 Excel 时刻表创建，并归属上面选定的批次；基本图仍独立管理。</p>
          <button v-if="kind === 'run'" type="button" :disabled="!parentId" @click="emit('openRunImport')">导入 run 时刻表</button>
          <template v-if="kind !== 'run'"><label>名称<input v-model="name" required maxlength="200" /></label>
          <label>备注<textarea v-model="notes" maxlength="20000" /></label>
          <button :disabled="busy || !name.trim()">{{ busy ? '正在保存…' : '创建分类' }}</button></template>
        </form>
      </article>
        <article v-if="activeTab === 'delete'" id="catalog-panel-delete" role="tabpanel" aria-labelledby="catalog-tab-delete" tabindex="0">
          <DeleteCategory v-if="current && current.kind !== 'run'" :key="current.id" :node="current" :nodes="nodes" @deleted="afterDelete" />
          <template v-else><h2>删除分类</h2><p class="empty-state">{{ current?.kind === 'run' ? '当前选中的是 run。请选中所属批次或上级分类，再预览删除范围和 run 处理方式。' : '请从左侧选择要删除的分类。' }}</p></template>
        </article>
        <article v-if="activeTab === 'base'" id="catalog-panel-base" role="tabpanel" aria-labelledby="catalog-tab-base" tabindex="0">
          <div v-if="current" class="catalog-actions" role="group" aria-label="所选条目操作"><strong>操作</strong><button v-for="action in actions" :key="action.id" type="button" :disabled="busy || action.disabled" :title="action.title" :class="{ danger: action.danger }" @click="performAction(action.id)">{{ action.label }}</button></div>
          <BaseDiagramInfo v-if="current" :key="currentBaseId + editorKey" :base-id="currentBaseId" :scope-path="currentPath" :resolution="resolution" :nodes="nodes" :action-request="actionRequest" @changed="afterDataChanged" />
          <template v-else><h2>基本图</h2><p class="empty-state">请从左侧选择分类或基本图条目。</p></template>
        </article>
        <article v-if="activeTab === 'experiments'" id="catalog-panel-experiments" role="tabpanel" aria-labelledby="catalog-tab-experiments" tabindex="0">
          <ExperimentManager :nodes="nodes" :experiments="experiments" :experiment-id="selectedExperimentId" :initial-owner-id="current?.kind === 'run' ? current.parent_id || '' : current?.id || ''" @changed="afterExperimentChanged" @select="selectExperiment" @open-run="openExperimentRun" @logs-changed="refreshSavedViews" />
        </article>
      </div>
      <LegacyBaseMigration v-if="view !== 'run-import'" :nodes="nodes" @migrated="refresh" />
      <RunImport v-if="view === 'run-import'" :nodes="nodes" :initial-batch-id="current?.kind === 'run' ? current.parent_id || '' : current?.kind === 'batch' ? current.id : ''" @imported="afterRunImported" />
      <div v-show="view === 'import'"><BaseImport :nodes="nodes" :initial-category-id="current?.kind === 'run' ? current.parent_id || '' : current?.id || ''" @imported="refresh" /><details><summary>独立的 Excel 结构预览</summary><ImportPreview /></details></div>
    </section>
  </main>
</template>
