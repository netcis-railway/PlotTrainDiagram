<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import type { DiagramViewSummary } from '../api/diagram'
import type { AnalysisNodeSummary, AnalysisSection } from '../api/analysis'
import RunAnalysis from './RunAnalysis.vue'
import type { TimetableActionRequest } from '../catalogActions'
import type { CatalogNode } from '../api/client'
import { request, post, objectUrl, formatPath, labels, type EditorData, type Change, type EditField, type EditValidation, type MovePreview, type TimetableEvent, type ValidationIssue } from '../api/baseImport'
import CategoryPicker from './CategoryPicker.vue'
import TimetableExport from './TimetableExport.vue'
import TimetableDiagram from './TimetableDiagram.vue'
import TrackRepair from './TrackRepair.vue'
import TimeShift from './TimeShift.vue'
import type { RepairIssue } from '../api/trackRepair'
import { availableLines, stationsOnLine, orderStations, orderTrains, originalOrder, type StationSort, type TrainSort } from '../timetableOrdering'
import { dockChannel, draftKey, editorHash, forgetTransfer, launchEditor, readTransfer, writeTransfer, type EditorSnapshot } from '../editorWindow'
const props = defineProps<{ objectType: 'base' | 'run'; objectId: string; nodes: CatalogNode[]; standalone?: boolean; transfer?: string; actionRequest?: TimetableActionRequest }>()
const emit = defineEmits<{ changed: [owner: string | null]; viewSaved: [view: DiagramViewSummary]; analysisSaved: [node: AnalysisNodeSummary]; logsChanged: []; draftChanged: [dirty: boolean] }>()
const analysisSection = ref<AnalysisSection>('diagram')
const editorRoot = ref<HTMLElement | null>(null)
const data = ref<EditorData | null>(null), error = ref(''), status = ref(''), busy = ref(false)
const draftRevision = ref(''), dateBase = ref(''), checkedBaseDate = ref(false), exportOpen = ref(false), validationPanel = ref<HTMLElement | null>(null)
const changes = ref<Record<string, Change>>({}), validation = ref<EditValidation | null>(null)
const checkedWarnings = ref(false), checkedDates = ref(false), draftMismatch = ref(false)
const stations = ref<string[]>([]), trains = ref<string[]>([]), stationSearch = ref(''), trainSearch = ref('')
const showTracks = ref(false), showSeq = ref(false), hiddenTrains = ref<string[]>([])
const selectedLine = ref('')
const stationOrder = ref<StationSort>('original'), trainSort = ref<TrainSort>('original'), sortStation = ref(''), trainOrder = ref<string[]>([])
const detached = ref(false), docking = ref(false), detachedUrl = ref('')
let childWindow: Window | null = null, childNonce = '', closeTimer: number | undefined, dockTimer: number | undefined
const shiftOpen = ref(false), shiftWarnings = ref<ValidationIssue[]>([])
const plotOpen = ref(false), repairOpen = ref(false), repairWarnings = ref<RepairIssue[]>([])
const picker = ref(false), movePreview = ref<MovePreview | null>(null), moveTarget = ref(''), moveConfirmed = ref(false)
const url = computed(() => objectUrl(props.objectType, props.objectId))
const storageKey = computed(() => draftKey(props.objectType, props.objectId))
const changeList = computed(() => Object.values(changes.value))
const dateChanged = computed(() => !!data.value && dateBase.value !== (data.value.object.date_base || ''))
const hasChanges = computed(() => changeList.value.length > 0 || dateChanged.value)
watch(hasChanges, value => emit('draftChanged', value), { immediate: true })
const lineOptions = computed(() => availableLines(data.value?.nodes || [], data.value?.display_lines))
const lineStations = computed(() => stationsOnLine(data.value?.nodes || [], selectedLine.value))
const orderedStations = computed(() => orderStations(lineStations.value, stationOrder.value, data.value?.original_order?.nodes, selectedLine.value))
const shownStations = computed(() => orderedStations.value.filter(n => stations.value.includes(n.id)))
const originalTrains = computed(() => originalOrder(data.value?.trains || [], data.value?.original_order?.trains))
const shownTrains = computed(() => originalOrder(originalTrains.value, trainOrder.value).filter(t => trains.value.includes(t.id) && !hiddenTrains.value.includes(t.id)))
const stationOptions = computed(() => orderedStations.value.filter(n => `${n.node_name_chn} ${n.node_name}`.includes(stationSearch.value)))
const selectedTrains = computed(() => originalOrder(originalTrains.value, trainOrder.value).filter(t => trains.value.includes(t.id)))
const trainOptions = computed(() => originalTrains.value.filter(t => `${t.train_course_id} ${t.train_base_date}`.includes(trainSearch.value)))
const eventMap = computed(() => new Map((data.value?.events || []).map(e => [`${e.node_id}:${e.train_id}`, e])))
const fields = computed<EditField[]>(() => ['arrival', 'departure', ...(showTracks.value ? ['track_code' as const] : []), ...(showSeq.value ? ['visit_seq' as const] : [])])
const fieldLabels: Record<EditField, string> = { arrival: '到达', departure: '出发', track_code: '股道', visit_seq: 'SEQ' }
const canSave = computed(() => !busy.value && !docking.value && validation.value?.can_save && !draftMismatch.value && hasChanges.value && (!validation.value.date_base_change || checkedBaseDate.value) && (!validation.value.issues.some(i => i.severity === 'warning') || checkedWarnings.value) && (!validation.value.train_date_changes.length || checkedDates.value))
function key(id: string, field: EditField) { return `${id}:${field}` }
function original(event: TimetableEvent, field: EditField) {
  const value = event[field]
  if (value === null) return ''
  if (typeof value === 'number') return String(value)
  const h = Math.floor(value.seconds / 3600), m = Math.floor(value.seconds % 3600 / 60), s = value.seconds % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
function value(event: TimetableEvent, field: EditField) { const item = changes.value[key(event.id, field)]; return item ? item.value ?? '' : original(event, field) }
function record(event: TimetableEvent, field: EditField, text: string) {
  if (text === original(event, field)) delete changes.value[key(event.id, field)]
  else changes.value[key(event.id, field)] = { event_id: event.id, field, value: text.trim() === '' ? null : text }
  validation.value = null; checkedWarnings.value = false; checkedDates.value = false; status.value = ''
  persist()
}
function applyDraftChanges(items: Change[]) {
  const events = new Map(data.value?.events.map(event => [event.id, event]) || [])
  const updated = { ...changes.value }
  for (const change of items) {
    const event = events.get(change.event_id)
    if (!event) continue
    if (String(change.value ?? '') === original(event, change.field)) delete updated[key(event.id, change.field)]
    else updated[key(event.id, change.field)] = change
  }
  changes.value = updated
  validation.value = null; checkedWarnings.value = false; checkedDates.value = false; checkedBaseDate.value = false
  persist(); applyTrainSort()
}
function applyTrackRepair(repairs: Change[], warnings: RepairIssue[]) {
  repairWarnings.value = warnings; shiftWarnings.value = []
  applyDraftChanges(repairs)
  showTracks.value = true; repairOpen.value = false
  status.value = repairs.length ? `已生成 ${repairs.length} 条股道分配${warnings.length ? `，有 ${warnings.length} 条修复告警` : ''}，请核对后校验并保存。` : '本次没有生成股道修改，请查看修复告警；已有非冲突股道保持原值。'
}
function applyTimeShift(items: Change[], warnings: ValidationIssue[]) {
  shiftWarnings.value = warnings; repairWarnings.value = []
  applyDraftChanges(items); shiftOpen.value = false
  status.value = `已平移 ${items.length} 个到发时刻（包含隐藏车站），请校验并保存。`
}
function snapshot(): EditorSnapshot {
  return { revision: draftMismatch.value ? draftRevision.value : data.value?.revision || '', dateBase: dateBase.value, changes: changes.value,
    view: { selectedLine: selectedLine.value, stations: stations.value, trains: trains.value, hiddenTrains: hiddenTrains.value, showTracks: showTracks.value, showSeq: showSeq.value, stationOrder: stationOrder.value, trainSort: trainSort.value, sortStation: sortStation.value } }
}
function persist() {
  if (!data.value || detached.value) return false
  try {
    const state = snapshot()
    sessionStorage.setItem(storageKey.value, JSON.stringify(state))
    if (props.standalone && props.transfer) writeTransfer(props.transfer, { kind: props.objectType, id: props.objectId }, state)
    return true
  } catch { error.value = '浏览器无法暂存草稿，请在离开页面前保存修改。'; return false }
}
function restore(saved: EditorSnapshot | null) {
  if (!saved || !data.value) return
  changes.value = saved.changes || {}; draftRevision.value = saved.revision
  dateBase.value = saved.dateBase ?? data.value.object.date_base ?? ''
  draftMismatch.value = hasChanges.value && saved.revision !== data.value.revision
  if (saved.view) {
    selectedLine.value = lineOptions.value.some(line => String(line.line_ind) === saved.view!.selectedLine) ? saved.view.selectedLine! : ''
    stations.value = saved.view.stations.filter(id => lineStations.value.some(n => n.id === id))
    trains.value = saved.view.trains.filter(id => data.value!.trains.some(t => t.id === id))
    hiddenTrains.value = saved.view.hiddenTrains.filter(id => trains.value.includes(id))
    showTracks.value = saved.view.showTracks; showSeq.value = saved.view.showSeq
    stationOrder.value = ['down','up'].includes(saved.view.stationOrder || '') ? saved.view.stationOrder! : 'original'
    trainSort.value = ['arrival','departure'].includes(saved.view.trainSort || '') ? saved.view.trainSort! : 'original'
    sortStation.value = stations.value.includes(saved.view.sortStation || '') ? saved.view.sortStation! : ''
    if (!sortStation.value) trainSort.value = 'original' 
  }
  if (hasChanges.value) status.value = '已恢复未保存修改，请校验后保存。'
}
function chooseLine(line: string) {
  selectedLine.value = line
  stations.value = lineStations.value.map(node => node.id)
  stationSearch.value = ''
}
function toggleTrain(id: string, visible: boolean) {
  hiddenTrains.value = visible ? hiddenTrains.value.filter(value => value !== id) : [...hiddenTrains.value, id]
}
async function resumeEmbedded(force = false) {
  if (!force && childWindow && !childWindow.closed) { childWindow.focus(); return }
  const saved = childNonce ? readTransfer(childNonce, { kind: props.objectType, id: props.objectId }) : null
  if (saved) sessionStorage.setItem(storageKey.value, JSON.stringify(saved))
  detached.value = false
  if (closeTimer) window.clearInterval(closeTimer)
  if (childNonce) forgetTransfer(childNonce)
  childWindow = null; childNonce = ''
  await load()
}
async function recoverHere() {
  // Every child input is checkpointed before this explicit return.
  try { childWindow?.close() } catch { /* some browser policies disallow closing a child */ }
  await resumeEmbedded(true)
}
function popout() {
  if (!data.value) return
  try {
    persist()
    const opened = launchEditor({ kind: props.objectType, id: props.objectId }, snapshot())
    childWindow = opened.child; childNonce = opened.nonce; detached.value = true
    const address = new URL(window.location.href); address.hash = editorHash('timetable', { kind: props.objectType, id: props.objectId, transfer: childNonce }); detachedUrl.value = address.href
    closeTimer = window.setInterval(() => { if (childWindow?.closed) void resumeEmbedded() }, 700)
  } catch (e) { error.value = String(e) }
}
function dockHere() {
  const target = { kind: props.objectType, id: props.objectId, transfer: props.transfer }
  window.location.hash = editorHash('workspace', target)
}
function dock() {
  if (!persist()) return
  docking.value = true
  if (props.transfer && window.opener && !window.opener.closed) {
    window.opener.postMessage({ channel: dockChannel, action: 'dock', target: { kind: props.objectType, id: props.objectId, transfer: props.transfer } }, window.location.origin)
    dockTimer = window.setTimeout(dockHere, 1500)
  } else dockHere()
}
function onDocked(event: MessageEvent) {
  if (event.origin !== window.location.origin || event.source !== window.opener || event.data?.channel !== dockChannel || event.data.action !== 'docked' || event.data.transfer !== props.transfer) return
  if (dockTimer) window.clearTimeout(dockTimer)
  window.close()
  status.value = '已嵌回主界面，可关闭此标签页。'
}
window.addEventListener('message', onDocked)
onUnmounted(() => {
  window.removeEventListener('message', onDocked)
  if (closeTimer) window.clearInterval(closeTimer)
  if (dockTimer) window.clearTimeout(dockTimer)
})
let restoring = false
watch(trains, () => { hiddenTrains.value = hiddenTrains.value.filter(id => trains.value.includes(id)) }, { flush: 'sync' })
watch([selectedLine, stations, trains, hiddenTrains, showTracks, showSeq, stationOrder, trainSort, sortStation], () => { if (!restoring) persist() }, { deep: true })

let handledAction = 0
watch([() => props.actionRequest, data, busy, detached], async () => {
  const request = props.actionRequest
  if (!request || request.sequence === handledAction || request.objectId !== props.objectId || request.kind !== props.objectType || request.action === 'delete' || !data.value || busy.value) return
  handledAction = request.sequence
  if (detached.value) { childWindow?.focus(); return }
  await nextTick()
  if (props.actionRequest !== request) return
  editorRoot.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  editorRoot.value?.focus({ preventScroll: true })
  if (request.action === 'diagram' || request.action === 'delay') {
    analysisSection.value = request.action === 'delay' ? 'delay' : 'diagram'
    if (draftMismatch.value) { error.value = '请先核对并处理旧版本草稿，再查看运行图。'; return }
    plotOpen.value = true
  }
}, { immediate: true })
let loadGeneration = 0
async function load() {
  const generation = ++loadGeneration
  repairWarnings.value = []; shiftWarnings.value = []; shiftOpen.value = false; repairOpen.value = false
  busy.value = true; data.value = null; validation.value = null; error.value = ''; movePreview.value = null
  try {
    const result = await request<EditorData>(`${url.value}/tables`)
    if (generation !== loadGeneration) return
    restoring = true
    data.value = result; dateBase.value = result.object.date_base || ''; stations.value = result.nodes.map(n => n.id); trains.value = originalOrder(result.trains, result.original_order?.trains).slice(0, 4).map(t => t.id)
    changes.value = {}; draftMismatch.value = false; selectedLine.value = ''; stationOrder.value = 'original'; trainSort.value = 'original'; sortStation.value = ''
    try {
      const shared = props.standalone && props.transfer ? readTransfer(props.transfer, { kind: props.objectType, id: props.objectId }) : null
      restore(shared || JSON.parse(sessionStorage.getItem(storageKey.value) || 'null'))
    } catch { error.value = '未能恢复浏览器草稿。' }
    finally { restoring = false }
    persist()
  } catch (e) { if (generation === loadGeneration) error.value = String(e) }
  finally { if (generation === loadGeneration) busy.value = false }
}
async function validate() {
  if (!data.value || !hasChanges.value) return
  busy.value = true; error.value = ''; validation.value = null
  try { validation.value = await post<EditValidation>(`${url.value}/events/validate`, { revision: data.value.revision, changes: changeList.value, date_base: dateBase.value || undefined }); checkedWarnings.value = false; checkedDates.value = false; checkedBaseDate.value = false }
  catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function save() {
  if (!data.value || !hasChanges.value || busy.value || docking.value || draftMismatch.value) return
  if (!validation.value) await validate()
  if (!validation.value || !canSave.value) { await nextTick(); validationPanel.value?.scrollIntoView({ block: 'center' }); return }
  busy.value = true; error.value = ''
  try {
    data.value = await post<EditorData>(`${url.value}/events/edit`, { revision: data.value.revision, changes: changeList.value, date_base: dateBase.value || undefined, date_base_confirmed: checkedBaseDate.value, validation_token: validation.value.validation_token, warnings_confirmed: checkedWarnings.value, train_dates_confirmed: checkedDates.value })
    dateBase.value = data.value.object.date_base || ''; changes.value = {}; persist(); validation.value = null; status.value = '修改已保存到工作状态，未自动归档。'; emit('changed', data.value.object.owner_category_id)
  } catch (e) { error.value = String(e); validation.value = null } finally { busy.value = false }
}
function openMove() { if (hasChanges.value) { error.value = '请先保存修改，或点击“放弃本次修改”，再调整所属类别。'; return }; picker.value = true; movePreview.value = null }
async function selectTarget(target: string) {
  picker.value = false; moveTarget.value = target; moveConfirmed.value = false; busy.value = true; error.value = ''
  try { movePreview.value = await post<MovePreview>(`${url.value}/move-preview`, { target_category_id: target }) }
  catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function move() {
  if (!movePreview.value || !moveConfirmed.value) return
  busy.value = true; error.value = ''
  try { await post(`${url.value}/move`, { target_category_id: moveTarget.value, confirmed: true, preview_token: movePreview.value.preview_token }); await load(); emit('changed', data.value?.object.owner_category_id || null) }
  catch (e) { error.value = String(e) } finally { busy.value = false }
}
function discard() { if (!confirm('放弃当前全部未保存修改？')) return; changes.value = {}; dateBase.value = data.value?.object.date_base || ''; persist(); validation.value = null; draftMismatch.value = false; void load() }
function issueField(issue: ValidationIssue) {
  return issue.field === 'SEQ' ? 'visit_seq' : issue.field === '_G' ? 'track_code' : issue.field
}
function issueLabel(issue: ValidationIssue) {
  const e = data.value?.events.find(e => e.id === issue.event_id)
  if (!e) return issue.field || ''
  const station = data.value?.nodes.find(n => n.id === e.node_id)?.node_name_chn || e.node_name
  return `${station} · ${e.train_course_id} · ${fieldLabels[issueField(issue) as EditField] || issue.field || ''}`
}
function invalid(id: string, field: EditField) {
  return validation.value?.issues.some(i => i.severity === 'error' && i.event_id === id && issueField(i) === field) || false
}
function locate(issue: ValidationIssue) {
  const e = data.value?.events.find(e => e.id === issue.event_id)
  if (!e) return
  if (!lineStations.value.some(node => node.id === e.node_id)) selectedLine.value = ''
  if (!stations.value.includes(e.node_id)) stations.value.push(e.node_id)
  if (!trains.value.includes(e.train_id)) trains.value.push(e.train_id)
  toggleTrain(e.train_id, true)
  const field = issueField(issue)
  if (field === 'track_code') showTracks.value = true
  if (field === 'visit_seq') showSeq.value = true
  setTimeout(() => document.getElementById(`cell-${e.id}-${field}`)?.focus(), 0)
}
function applyTrainSort() {
  trainOrder.value = orderTrains(data.value?.trains || [], data.value?.events || [], sortStation.value,
    trainSort.value, changes.value, dateBase.value, data.value?.original_order?.trains,
    data.value?.route_nodes || data.value?.nodes || [], selectedLine.value).map(t => t.id)
}
function chooseTrainSort(field: 'arrival' | 'departure', station: string) {
  trainSort.value = station ? field : 'original'; sortStation.value = station; applyTrainSort()
}
function afterCellEdit(field: EditField) {
  if (trainSort.value !== 'original' && (field === 'arrival' || field === 'departure')) applyTrainSort()
}
function restoreOrder() {
  stationOrder.value = 'original'; trainSort.value = 'original'; sortStation.value = ''; applyTrainSort()
  status.value = data.value?.original_order?.notice || '已恢复原Excel的车站行序和列车列序。'
}
watch([data, trainSort, sortStation, selectedLine], applyTrainSort)
watch(stations, () => { if (!stations.value.includes(sortStation.value)) { trainSort.value = 'original'; sortStation.value = ''; applyTrainSort() } }, { flush: 'sync' })
function trainDate(day: string) {
  if (!data.value?.object.date_base || !dateBase.value) return day
  const delta = Date.parse(`${dateBase.value}T00:00:00Z`) - Date.parse(`${data.value.object.date_base}T00:00:00Z`)
  try { return new Date(Date.parse(`${day}T00:00:00Z`) + delta).toISOString().slice(0, 10) } catch { return day }
}
watch(dateBase, () => { validation.value = null; checkedBaseDate.value = false; checkedDates.value = false; checkedWarnings.value = false; applyTrainSort(); if (!restoring) persist() }, { flush: 'sync' })
watch(() => [props.objectType, props.objectId], load, { immediate: true })
</script>
<template><div ref="editorRoot" class="timetable-editor" tabindex="-1">
  <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
  <details v-if="repairWarnings.length" class="validation-warning"><summary>股道修复提示（{{ repairWarnings.length }}）</summary><ul><li v-for="(issue, i) in repairWarnings" :key="i">{{ issue.train_course_id }} · {{ issue.node_name_chn }}：{{ issue.message }}</li></ul></details>
  <details v-if="shiftWarnings.length" class="validation-warning"><summary>整车平移提示（{{ shiftWarnings.length }}）</summary><ul><li v-for="(issue, i) in shiftWarnings" :key="i">{{ issue.message }}</li></ul></details>
  <p v-if="busy" role="status">正在处理…</p>
  <div v-if="detached" class="category-context" role="status"><p>此时刻表已在独立标签页中编辑。点击该页的“Dock · 嵌回主界面”返回；关闭独立页也会恢复当前编辑器。</p><button @click="resumeEmbedded()">前往独立编辑页</button> <button @click="recoverHere">恢复到当前界面</button> <a :href="detachedUrl" target="_blank">独立编辑页链接</a></div>
  <template v-if="data && !detached">
    <RunAnalysis v-if="plotOpen && objectType === 'run'" :key="analysisSection" :run-id="objectId" :run-name="data.object.name" :section="analysisSection" :source="{ revision: data.revision, dateBase, originalDateBase: data.object.date_base || '', changes: changeList, initialLine: selectedLine }" @close="plotOpen = false; analysisSection = 'diagram'" @saved="emit('analysisSaved', $event)" @logs-changed="emit('logsChanged')" />
    <div class="editor-heading"><div><h3>{{ objectType === 'base' ? '基本图' : 'run' }}时刻表：{{ data.object.name }}</h3><p>{{ data.object.baseTT_no || `run_${data.object.run_no}` }} · 基准日 {{ data.object.date_base || '尚无正式时刻数据' }}</p>
      <p><strong>直属类别：</strong>{{ data.object.classification_path.length ? `${labels[data.object.classification_path.at(-1)!.kind]} ${data.object.classification_path.at(-1)!.name}` : '未分组' }}</p><p class="muted">{{ formatPath(data.object.classification_path) }}</p></div>
      <div class="editor-window-actions"><button :disabled="busy || docking || draftMismatch" @click="analysisSection = 'diagram'; plotOpen = true">查看运行图</button><button :disabled="busy || docking" @click="openMove">编辑所属类别</button>
      <button v-if="standalone" :disabled="busy || docking" @click="dock">{{ docking ? '正在嵌回…' : 'Dock · 嵌回主界面' }}</button>
      <button v-else :disabled="busy" @click="popout">在新标签页中编辑</button>
      <button :disabled="busy || docking || draftMismatch || !data.events.length" @click="shiftOpen = true">整车时间平移</button>
      <button :disabled="busy || docking || draftMismatch || !data.events.length" @click="repairOpen = true">修复股道信息</button>
      <button :disabled="busy || docking || hasChanges || draftMismatch" @click="exportOpen = true">{{ objectType === 'base' ? '导出基本图和线路数据' : '导出' }}</button></div></div>
    <div class="editor-date"><label>运行基准日<input v-model="dateBase" type="date" min="2020-01-01" max="9999-12-31" :disabled="busy || docking || !data.object.date_base" /></label>
      <p class="muted">修改基准日后，保存会更新全部到发日期和列车基准日，保留时分秒与跨日偏移。导出前请先保存修改。</p></div>
    <TimetableDiagram v-if="plotOpen && objectType === 'base'" :object-type="objectType" :object-id="objectId" :revision="data.revision" :date-base="dateBase" :original-date-base="data.object.date_base || ''" :changes="changeList" :initial-line="selectedLine" @view-saved="emit('viewSaved', $event)" @close="plotOpen = false" />
    <TimeShift v-if="shiftOpen" :object-type="objectType" :object-id="objectId" :revision="data.revision" :changes="changeList" :date-base="dateBase" :trains="data.trains" :initial-selected="trains" @close="shiftOpen = false" @applied="applyTimeShift" />
    <TrackRepair v-if="repairOpen" :object-type="objectType" :object-id="objectId" :revision="data.revision" :changes="changeList" :date-base="dateBase" @close="repairOpen = false" @applied="applyTrackRepair" />
    <TimetableExport v-if="exportOpen" :url="url" :revision="data.revision" :object-type="objectType" @backup-updated="emit('changed', data.object.owner_category_id)" @close="exportOpen = false" />
    <CategoryPicker v-if="picker" :nodes="nodes" :current="data.object.owner_category_id" :batch-only="objectType === 'run'" @close="picker = false" @choose="selectTarget" />
    <div v-if="movePreview" class="category-context"><h3>所属类别修改预览</h3><p>{{ formatPath(movePreview.source_path) }} → {{ formatPath(movePreview.target_path) }}</p>
      <p v-if="!movePreview.can_move" class="error">目标已占用、位置相同或存在校验问题，不能移动。</p><p v-for="(issue,i) in movePreview.issues" :key="i" class="error">{{ issue.message }}</p>
      <details><summary>来源发生变化的对象（{{ movePreview.impact.length }}）</summary><ul><li v-for="entry in movePreview.impact" :key="entry.kind + entry.id">{{ entry.name }}：{{ entry.before.name || '无基本图' }} → {{ entry.after.name || '无基本图' }}</li></ul></details>
      <label class="confirmation"><input v-model="moveConfirmed" type="checkbox" />已核对原、新位置与影响</label><button :disabled="busy || !moveConfirmed || !movePreview.can_move" @click="move">确认修改所属类别</button> <button @click="movePreview = null">取消</button></div>
    <div v-if="draftMismatch" class="validation-warning">恢复的草稿基于旧版本。请核对单元格的原值与当前输入。<button @click="draftMismatch = false; persist()">已核对，使用当前版本重新校验</button></div>
    <div class="editor-filters"><div class="editor-line-filter"><label>线路选择<select :value="selectedLine" :disabled="busy || docking" @change="chooseLine(($event.target as HTMLSelectElement).value)"><option value="">所有线路</option><option v-for="line in lineOptions" :key="line.line_ind" :value="String(line.line_ind)">{{ line.line_name_chn || line.line_code || '线路' }}（{{ line.line_ind }}）</option></select></label></div><details><summary>车站选择（{{ stations.length }} / {{ lineStations.length }}）</summary><input v-model="stationSearch" placeholder="搜索车站" /><button @click="stations = lineStations.map(n => n.id)">全选</button> <button @click="stations = []">清空</button><p class="muted">仅列出当前线路范围的车站，可进一步勾选。</p><div class="checkbox-options"><label v-for="n in stationOptions" :key="n.id"><input v-model="stations" type="checkbox" :value="n.id" />{{ n.node_name_chn }} · {{ n.node_name }}</label></div></details>
      <details><summary>列车选择（{{ trains.length }}）</summary><input v-model="trainSearch" placeholder="搜索车次或基准日" /><button @click="trains = data!.trains.map(t => t.id)">全选</button> <button @click="trains = []">清空</button><div class="checkbox-options"><label v-for="t in trainOptions" :key="t.id"><input v-model="trains" type="checkbox" :value="t.id" />{{ t.train_course_id }} · {{ t.train_base_date }}</label></div></details></div>
    <div class="editor-toolbar"><span>待保存单元格 {{ changeList.length }} 项（包含被筛选隐藏的修改）{{ dateChanged ? '；另有运行基准日修改' : '' }}</span><div><button :disabled="busy || docking || !hasChanges || draftMismatch" @click="validate">校验</button> <button :disabled="busy || docking || !hasChanges || draftMismatch" @click="save">保存</button></div></div>
    <details class="train-visibility"><summary>列车显示控制（显示 {{ shownTrains.length }} / 初选 {{ selectedTrains.length }}）</summary>
      <p class="muted">仅列出“列车选择”中的初选列车。取消勾选只隐藏列车，待保存修改仍保留。</p>
      <div class="editor-actions"><button :disabled="!selectedTrains.length" @click="hiddenTrains = []">全部显示</button><button :disabled="!selectedTrains.length" @click="hiddenTrains = trains.slice()">全部隐藏</button></div>
      <div class="table-wrap train-visibility-table"><table v-if="selectedTrains.length" aria-label="初选列车显示控制"><thead><tr><th>显示</th><th>车次号</th><th>日期</th></tr></thead><tbody>
        <tr v-for="train in selectedTrains" :key="train.id"><td><input type="checkbox" :aria-label="`显示列车 ${train.train_course_id} ${train.train_base_date}`" :checked="!hiddenTrains.includes(train.id)" @change="toggleTrain(train.id, ($event.target as HTMLInputElement).checked)" /></td><td>{{ train.train_course_id }}</td><td>{{ train.train_base_date }}</td></tr>
      </tbody></table><p v-else>请先在“列车选择”中勾选候选列车。</p></div>
    </details>
    <div class="editor-field-controls"><label class="confirmation"><input v-model="showTracks" type="checkbox" />显示股道</label><label class="confirmation"><input v-model="showSeq" type="checkbox" />显示SEQ</label></div>
    <div class="editor-sort-controls" aria-label="时刻表显示排序">
      <label title="单条线路按NODE_IND排序；所有线路先按LINE_IND再按NODE_IND排序，共用车站按最小LINE_IND归组且只显示一次。缺少编号的站点排在最后。">车站排序<select v-model="stationOrder" :disabled="busy || docking"><option value="original">原始顺序</option><option value="down">下行排序</option><option value="up">上行排序</option></select></label>
      <label>列车到达排序<select :value="trainSort === 'arrival' ? sortStation : ''" :disabled="busy || docking || !shownStations.length" @change="chooseTrainSort('arrival', ($event.target as HTMLSelectElement).value)"><option value="">原始列序</option><option v-for="node in shownStations" :key="node.id" :value="node.id">{{ node.node_name_chn }}</option></select></label>
      <label>列车出发排序<select :value="trainSort === 'departure' ? sortStation : ''" :disabled="busy || docking || !shownStations.length" @change="chooseTrainSort('departure', ($event.target as HTMLSelectElement).value)"><option value="">原始列序</option><option v-for="node in shownStations" :key="node.id" :value="node.id">{{ node.node_name_chn }}</option></select></label>
      <button :disabled="busy || docking" @click="restoreOrder">恢复原始顺序</button>
    </div><p class="muted">到达和出发排序以最后一次选择为准。依次采用所选站目标时刻、该站另一时刻、同线路最近可用站时刻（按NODE_SEQ_OF_LINE检索），按时间插入；均无时刻则置后。</p><p class="muted">点击单元格编辑。跨日可输入 25:10:00 或完整日期时刻；“未经过”不能编辑。输入后需重新校验。</p>
    <fieldset :disabled="busy || docking" class="editor-grid-fieldset"><div class="table-wrap editor-table" tabindex="0" role="region" aria-label="时刻表编辑网格，首列和前三行固定"><table v-if="shownStations.length && shownTrains.length"><thead><tr><th rowspan="3" scope="col" class="station-corner">车站</th><th v-for="t in shownTrains" :key="t.id" :colspan="fields.length">{{ t.train_course_id }}</th></tr><tr><th v-for="t in shownTrains" :key="t.id" :colspan="fields.length">{{ trainDate(t.train_base_date) }}</th></tr><tr><template v-for="t in shownTrains" :key="t.id"><th v-for="f in fields" :key="f">{{ fieldLabels[f] }}</th></template></tr></thead><tbody>
      <tr v-for="station in shownStations" :key="station.id"><th scope="row">{{ station.node_name_chn }}</th><template v-for="train in shownTrains" :key="train.id"><template v-if="eventMap.get(`${station.id}:${train.id}`)"><td v-for="field in fields" :key="field" :class="{ 'edited-cell': !!changes[key(eventMap.get(`${station.id}:${train.id}`)!.id, field)], 'validation-error': invalid(eventMap.get(`${station.id}:${train.id}`)!.id, field) }"><input :class="{ 'time-field': field === 'arrival' || field === 'departure' }" :id="`cell-${eventMap.get(`${station.id}:${train.id}`)!.id}-${field}`" :aria-invalid="invalid(eventMap.get(`${station.id}:${train.id}`)!.id, field)" :aria-label="`${station.node_name_chn} ${train.train_course_id} ${fieldLabels[field]}`" :title="`原值：${original(eventMap.get(`${station.id}:${train.id}`)!, field) || '空'}`" :value="value(eventMap.get(`${station.id}:${train.id}`)!, field)" @input="record(eventMap.get(`${station.id}:${train.id}`)!, field, ($event.target as HTMLInputElement).value)" @blur="afterCellEdit(field)" /></td></template><td v-else :colspan="fields.length" class="muted">未经过</td></template></tr>
    </tbody></table><p v-else class="empty-state">{{ selectedLine && !lineStations.length ? '当前对象没有该线路的车站，请选择其他线路。' : '请选择车站和列车；没有正式时刻数据的 run 暂无可编辑单元格。' }}</p></div></fieldset>
    <div v-if="validation" ref="validationPanel"><p :class="validation.can_save ? 'muted' : 'error'" role="status">{{ validation.can_save ? '无阻断错误，请核对警告后保存。' : '校验未通过，请修正后复检。' }}</p><div class="validation-list"><button v-for="(issue,i) in validation.issues" :key="i" :class="issue.severity === 'error' ? 'validation-error' : 'validation-warning'" @click="locate(issue)">{{ issue.severity === 'error' ? '错误' : '警告' }} · {{ issueLabel(issue) }}：{{ issue.message }}</button></div>
      <label v-if="validation.date_base_change" class="confirmation"><input v-model="checkedBaseDate" type="checkbox" />确认运行基准日 {{ validation.date_base_change.before }} → {{ validation.date_base_change.after }}，并更新全部到发日期</label>
      <label v-if="validation.issues.some(i => i.severity === 'warning')" class="confirmation"><input v-model="checkedWarnings" type="checkbox" />已核对并接受警告</label>
      <template v-if="validation.train_date_changes.length"><p v-for="t in validation.train_date_changes" :key="t.train_course_id">{{ t.train_course_id }} 基准日：{{ t.before }} → {{ t.after }}</p><label class="confirmation"><input v-model="checkedDates" type="checkbox" />确认上述列车基准日变化</label></template>
    </div><button v-if="hasChanges" :disabled="busy" @click="discard">放弃本次修改</button>
  </template>
</div></template>
