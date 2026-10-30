<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId } from 'vue'
import { formatPath, type Change } from '../api/baseImport'
import { diagramApi, type PlotContext, type PlotData, type PlotSeries, type PlotIssue, type SavedDiagramView, type DiagramViewSummary, type CreateDiagramView, type TrainSourceDisplay } from '../api/diagram'
import { fitViewport, localTime, timeLabel, timeRange, zoomViewport, type Viewport } from '../diagramGeometry'
import { orderPlotTrains } from '../diagramTrainOrdering'
import DiagramCanvas from './DiagramCanvas.vue'
import DiagramTrainDetails from './DiagramTrainDetails.vue'
const props = defineProps<{ objectType: 'base' | 'run'; objectId: string; revision: string; dateBase: string; originalDateBase: string; changes: Change[]; initialLine: string; savedView?: SavedDiagramView; embedded?: boolean; managed?: boolean; experimentId?: string }>()
const emit = defineEmits<{ close: []; viewSaved: [view: DiagramViewSummary]; requestSave: [] }>()
const dialog = ref<HTMLDialogElement | null>(null), previousFocus = document.activeElement as HTMLElement | null
const context = ref<PlotContext | null>(null), data = ref<PlotData | null>(null), busy = ref(false), error = ref('')
const line = ref(''), overlay = ref(false), reverse = ref(false), stationIds = ref<string[]>([]), trainIds = ref<string[]>([]), selected = ref<string[]>([])
const sourceDisplay = ref<Record<string, TrainSourceDisplay>>({}), controlId = useId()
interface TrainSource { key: string; objectType: 'base' | 'run'; label: string; name: string; runNo: number; keys: string[]; available: boolean; color?: string }
function sourceKey(series: PlotSeries) { return `${series.object_type}:${series.object_id}` }
function sourceMode(key: string) { return sourceDisplay.value[key]?.mode || 'selected' }
function sourceEnabled(source: TrainSource) { return source.objectType === 'base' && props.objectType === 'run' ? overlay.value : sourceDisplay.value[source.key]?.enabled !== false }
function setSourceEnabled(source: TrainSource, enabled: boolean) {
  sourceDisplay.value = { ...sourceDisplay.value, [source.key]: { enabled, mode: sourceMode(source.key) } }
  if (source.objectType === 'base' && props.objectType === 'run') overlay.value = enabled
}
function setSourceMode(source: TrainSource, mode: TrainSourceDisplay['mode']) {
  sourceDisplay.value = { ...sourceDisplay.value, [source.key]: { enabled: sourceEnabled(source), mode } }
}
function selectSource(source: TrainSource, all: boolean) {
  const keys = new Set(source.keys)
  trainIds.value = all ? [...new Set([...trainIds.value, ...source.keys])] : trainIds.value.filter(key => !keys.has(key))
}
function showHighlightedTrains() {
  const available = new Set(data.value?.series.map(series => series.key) || [])
  trainIds.value = selected.value.filter(key => available.has(key))
  for (const source of trainSources.value) setSourceMode(source, 'selected')
}
const stationSearch = ref(''), trainSearch = ref(''), from = ref(''), to = ref(''), logText = ref(''), detailOpen = ref(false)
const expanded = ref<string[]>([]), trackStation = ref('')
const openPanels = ref<string[]>([])
function panel(id: string, event: Event) { openPanels.value = (event.target as HTMLDetailsElement).open ? [...new Set([...openPanels.value, id])] : openPanels.value.filter(key => key !== id) }
const canvasRef = ref<InstanceType<typeof DiagramCanvas> | null>(null)
const restoredHeight = ref<number>()
const saveViewOpen = ref(false), viewName = ref(''), savingView = ref(false), viewStatus = ref('')
let viewClosed = false
const snapshotMode = computed(() => !!props.savedView)
const trackResource = computed(() => data.value?.track_stations.find(resource => resource.node_id === trackStation.value))
const viewport = ref<Viewport>({ x0: 0, x1: 3600, y0: 0, y1: 1000 })
let generation = 0, styleTimer: number | undefined, loadingStyles = false
const styleIssues = ref<PlotIssue[]>([]), styleLogWritten = ref(true)
const hasDraft = computed(() => props.changes.length > 0 || props.dateBase !== props.originalDateBase)
const trainSources = computed(() => {
  const sources = new Map<string, TrainSource>()
  function add(objectType: 'base' | 'run', id: string, name: string, runNo?: number | null) {
    const key = `${objectType}:${id}`
    if (!sources.has(key)) sources.set(key, { key, objectType, label: objectType === 'base' ? '基本图' : runNo == null ? name || 'run' : `run_${runNo}`, name, runNo: runNo ?? Infinity, keys: [], available: objectType !== 'base' || props.objectType === 'base' || !!data.value?.overlay_base })
  }
  if (data.value) {
    const object = data.value.object
    if (!props.experimentId) add(props.objectType, object.id, object.name, object.run_no)
    for (const [index, member] of (data.value.members || []).entries()) {
      add('run', member.id, member.name, member.run_no)
      const source = sources.get(`run:${member.id}`)!
      source.label = `${index + 1}. run_${member.run_no} · ${member.name}`
      source.name = member.classification_path.map(n => n.name).join(' → ')
      source.color = member.color
    }
    if (props.objectType === 'run' && data.value.base) add('base', data.value.base.id, data.value.base.name)
    for (const series of data.value.series) {
      add(series.object_type, series.object_id, series.object_name, series.run_no ?? (series.object_id === object.id ? object.run_no : undefined))
      sources.get(sourceKey(series))!.keys.push(series.key)
    }
  }
  const positions = new Map(data.value?.members?.map((member, index) => [`run:${member.id}`, index]) || [])
  return [...sources.values()].sort((a, b) => (a.objectType === 'base' ? 0 : 1) - (b.objectType === 'base' ? 0 : 1) || (props.experimentId ? (positions.get(a.key) ?? -1) - (positions.get(b.key) ?? -1) : a.runNo - b.runNo || a.key.localeCompare(b.key)))
})
const displayed = computed(() => {
  const sources = new Map(trainSources.value.map(source => [source.key, source]))
  const checked = new Set(trainIds.value)
  return data.value?.series.filter(series => {
    const source = sources.get(sourceKey(series))
    return source && sourceEnabled(source) && (sourceMode(source.key) === 'all' || checked.has(series.key))
  }) || []
})
const stationOptions = computed(() => data.value?.axis.stations.filter(s => `${s.node_name_chn} ${s.node_name}`.includes(stationSearch.value)) || [])
const orderedTrains = computed(() => orderPlotTrains(data.value?.series || [], data.value?.object))
const trainOptions = computed(() => orderedTrains.value.filter(s => `${s.train_course_id} ${s.object_name} ${s.train_base_date}`.includes(trainSearch.value)))
function sourceOptions(source: TrainSource) { return trainOptions.value.filter(series => sourceKey(series) === source.key) }
const issues = computed(() => data.value ? [...data.value.issues.filter(i => i.code !== 'style_config'), ...styleIssues.value] : context.value?.issues || [])
const selectedDetails = computed(() => {
  const byKey = new Map(data.value?.series.map(series => [series.key, series]) || [])
  return selected.value.map(key => byKey.get(key)).filter((series): series is PlotSeries => !!series)
})
const ready = computed(() => data.value?.can_plot && stationIds.value.length && displayed.value.some(s => s.points.length))
function resetRange(dimension: 'both' | 'time' | 'station' = 'both') {
  if (!data.value) return
  const stations = data.value.axis.stations.filter(s => stationIds.value.includes(s.node_id))
  const fitted = fitViewport(data.value, stations)
  if (dimension !== 'station') {
    viewport.value = { ...viewport.value, x0: fitted.x0, x1: fitted.x1 }
    from.value = localTime(data.value.object.date_base || '', Math.max(0, fitted.x0))
    to.value = localTime(data.value.object.date_base || '', fitted.x1)
  }
  if (dimension !== 'time') viewport.value = { ...viewport.value, y0: fitted.y0, y1: fitted.y1 }
}
function reconcile(previous: string[], old: string[], incoming: string[]) {
  return incoming.filter(id => previous.includes(id) || !old.includes(id))
}
async function loadData(reason: 'line' | 'overlay' | 'refresh' | 'tracks' | 'style') {
  if (viewClosed || snapshotMode.value || !context.value || !line.value) return
  if (reason === 'line') { expanded.value = []; trackStation.value = '' }
  const version = ++generation, old = data.value
  busy.value = true; error.value = ''; logText.value = ''
  try {
    const result = props.experimentId ? await diagramApi.experimentData(props.experimentId, { revision: context.value.revision, line_ind: Number(line.value), overlay_base: context.value.overlay_available, expanded_stations: expanded.value }) : await diagramApi.data({ object_type: props.objectType, object_id: props.objectId, line_ind: Number(line.value),
      revision: hasDraft.value ? props.revision : context.value.revision, overlay_base: context.value.overlay_available, expanded_stations: expanded.value,
      changes: hasDraft.value ? props.changes : [], date_base: hasDraft.value ? props.dateBase || undefined : undefined })
    if (version !== generation) return
    const incomingStations = result.axis.stations.map(s => s.node_id), incomingTrains = result.series.map(s => s.key)
    stationIds.value = reason === 'line' ? incomingStations : reconcile(stationIds.value, old?.axis.stations.map(s => s.node_id) || [], incomingStations)
    trainIds.value = reason === 'line' ? incomingTrains : reconcile(trainIds.value, old?.series.map(s => s.key) || [], incomingTrains)
    selected.value = selected.value.filter(id => incomingTrains.includes(id))
    data.value = result; expanded.value = result.expanded_stations
    if (!result.track_stations.some(resource => resource.node_id === trackStation.value)) trackStation.value = result.track_stations.find(resource => resource.can_expand)?.node_id || result.track_stations[0]?.node_id || ''
    styleIssues.value = result.issues.filter(i => i.code === 'style_config')
    if (['line','refresh'].includes(reason) || !old?.can_plot) resetRange()
  } catch (e) { if (version === generation) { data.value = null; error.value = String(e) } }
  finally { if (version === generation) busy.value = false }
}
async function reload(initial = false) {
  if (viewClosed || snapshotMode.value) return
  busy.value = true; error.value = ''
  try {
    const previousRevision = context.value?.revision
    const result = props.experimentId ? await diagramApi.experimentContext(props.experimentId) : await diagramApi.context(props.objectType, props.objectId)
    if (viewClosed) return
    context.value = result
    if (previousRevision && previousRevision !== context.value.revision) expanded.value = []
    if (initial) {
      line.value = context.value.lines.some(l => String(l.line_ind) === props.initialLine) ? props.initialLine : String(context.value.lines.find(l => l.available)?.line_ind || context.value.lines[0]?.line_ind || '')
      overlay.value = context.value.overlay_available && (!hasDraft.value || props.dateBase === context.value.object.date_base)
    }
    if (line.value) await loadData('refresh'); else data.value = null
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
function applyTime() {
  const range = timeRange(data.value?.object.date_base || '', from.value, to.value)
  if (!range) { error.value = '请输入有效时间范围：结束须晚于开始，且不能早于运行基准日。'; return }
  error.value = ''; viewport.value = { ...viewport.value, x0: range[0], x1: range[1] }
}
function highlight(key: string, add = false) {
  selected.value = add ? selected.value.includes(key) ? selected.value.filter(id => id !== key) : [...selected.value, key] : [key]
}
function inspectSeries(series: PlotSeries) {
  if (!selected.value.includes(series.key)) selected.value = [...selected.value, series.key]
  detailOpen.value = true
}
async function toggleTrack(id: string) {
  if (busy.value || snapshotMode.value) return
  trackStation.value = id
  if (!stationIds.value.includes(id)) stationIds.value = [...stationIds.value, id]
  expanded.value = expanded.value.includes(id) ? expanded.value.filter(value => value !== id) : [...expanded.value, id]
  await loadData('tracks')
}
async function collapseTracks() { if (!busy.value && !snapshotMode.value) { expanded.value = []; await loadData('tracks') } }
async function readLog() { try { const log = await diagramApi.log(); logText.value = `${log.filename}\n${log.text}` } catch (e) { error.value = String(e) } }
async function refreshStyles() {
  if (snapshotMode.value || busy.value || !data.value || loadingStyles) return
  loadingStyles = true
  try {
    const config = await diagramApi.styles()
    if (busy.value) return
    styleIssues.value = config.issues; styleLogWritten.value = config.log_written
    if (data.value && data.value.styles.track_yita_seconds !== config.styles.track_yita_seconds && expanded.value.length) {
      await loadData('style'); return
    }
    if (data.value && JSON.stringify(data.value.styles) !== JSON.stringify(config.styles)) data.value = { ...data.value, styles: config.styles }
  } catch { /* Data reload reports connection failures; style polling retains the current chart. */ }
  finally { loadingStyles = false }
}
function restoreSavedView(saved: SavedDiagramView) {
  const snapshot = JSON.parse(JSON.stringify(saved.snapshot)) as SavedDiagramView['snapshot']
  const state = saved.state
  context.value = snapshot.context; data.value = snapshot.data
  line.value = String(state.line_ind); overlay.value = state.overlay_base; reverse.value = state.reverse
  stationIds.value = [...state.station_ids]; trainIds.value = [...state.train_keys]; selected.value = [...state.highlighted_keys]
  expanded.value = [...state.expanded_station_ids]; trackStation.value = state.track_station
  viewport.value = { ...state.viewport }; from.value = state.from_time; to.value = state.to_time
  detailOpen.value = state.detail_open; restoredHeight.value = state.chart_height
  stationSearch.value = state.display?.station_search || ''; trainSearch.value = state.display?.train_search || ''; openPanels.value = [...(state.display?.open_panels || [])]
  sourceDisplay.value = JSON.parse(JSON.stringify(state.display?.train_sources || {}))
  // Convert the former live filter into a fixed selection using its saved highlights.
  if (state.display?.only_highlighted) showHighlightedTrains()
  styleIssues.value = snapshot.data.issues.filter(issue => issue.code === 'style_config')
  viewStatus.value = `已打开保存视图：${saved.name}`
}
function openSaveView() {
  const title = context.value?.lines.find(item => String(item.line_ind) === line.value)?.line_name_chn || '运行图'
  viewName.value = `${props.savedView?.name || title} · ${new Date().toLocaleString()}`.slice(0, 200)
  saveViewOpen.value = true; viewStatus.value = ''
}
function currentView(): CreateDiagramView | null {
  if (props.experimentId || !context.value || !data.value || !ready.value || props.objectType !== 'run') return null
  return JSON.parse(JSON.stringify({
    name: viewName.value.trim() || '运行图',
    state: {
      version: 1, line_ind: Number(line.value), overlay_base: overlay.value, reverse: reverse.value,
      station_ids: stationIds.value, train_keys: trainIds.value, highlighted_keys: selected.value,
      expanded_station_ids: expanded.value, track_station: trackStation.value, viewport: viewport.value,
      from_time: from.value, to_time: to.value, detail_open: detailOpen.value,
      chart_height: canvasRef.value?.getHeight() || restoredHeight.value || 600,
      display: { station_search: stationSearch.value, train_search: trainSearch.value, open_panels: openPanels.value,
        only_highlighted: false, train_sources: Object.fromEntries(trainSources.value.map(source => [source.key, { enabled: sourceEnabled(source), mode: sourceMode(source.key) }])) },
    },
    snapshot: { context: context.value, data: data.value },
  })) as CreateDiagramView
}
async function saveCurrentView() {
  if (viewClosed || savingView.value || busy.value || !viewName.value.trim()) return
  const payload = currentView()
  if (!payload) return
  savingView.value = true; error.value = ''
  try {
    const saved = await diagramApi.saveView(props.objectId, payload)
    if (viewClosed) return
    viewStatus.value = `已保存视图：${saved.name}，可在run下点击回看。`
    saveViewOpen.value = false; emit('viewSaved', saved)
  } catch (e) { if (!viewClosed) error.value = String(e) }
  finally { savingView.value = false }
}
defineExpose({ capture: currentView, isBusy: () => busy.value })
onMounted(async () => {
  await nextTick(); if (viewClosed) return; if (!props.embedded) dialog.value?.showModal()
  if (props.savedView) restoreSavedView(props.savedView)
  else { await reload(true); if (!viewClosed) styleTimer = window.setInterval(refreshStyles, 4000) }
})
onUnmounted(() => { viewClosed = true; generation++; if (styleTimer) window.clearInterval(styleTimer); if (!props.embedded) previousFocus?.focus() })
</script>
<template><component :is="embedded ? 'section' : 'dialog'" ref="dialog" :class="embedded ? 'diagram-embedded' : 'diagram-dialog'" aria-labelledby="diagram-title" @cancel.prevent="emit('close')">
  <div class="diagram-heading"><h2 id="diagram-title">运行图 · {{ data?.object.name || context?.object.name || (objectType === 'base' ? '基本图' : 'run') }}</h2><div><button v-if="!snapshotMode" :disabled="busy" @click="reload()">刷新图形数据和样式</button> <button v-if="objectType === 'run' && !experimentId" :disabled="busy || savingView || !ready" @click="managed ? emit('requestSave') : openSaveView()">保存当前视图</button> <button v-if="!embedded" @click="emit('close')">{{ snapshotMode ? '关闭视图' : '返回时刻表' }}</button></div></div>
  <p v-if="savedView" class="category-context">保存视图：<strong>{{ savedView.name }}</strong> · {{ new Date(savedView.created_at).toLocaleString() }} · 按保存时的数据快照回看，可继续筛选、缩放及高亮。</p>
  <form v-if="saveViewOpen" class="diagram-save-view" @submit.prevent="saveCurrentView">
    <label>视图名称<input v-model="viewName" maxlength="200" required :disabled="savingView" /></label>
    <p class="muted">保存当前线路、车站、基本图/run列车、范围、高亮及绘图快照。时刻表草稿仍需在编辑器另行保存。</p>
    <div class="catalog-actions"><button type="submit" :disabled="savingView || busy || !viewName.trim()">{{ savingView ? '正在保存…' : '保存视图' }}</button><button type="button" :disabled="savingView" @click="saveViewOpen = false">取消</button></div>
  </form>
  <p v-if="viewStatus" role="status">{{ viewStatus }}</p>
  <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="busy" role="status">正在读取运行图…</p>
  <template v-if="context"><div class="diagram-context"><span>{{ data?.preview ? `预览未保存草稿（${data.preview_changes}个单元格）` : '已保存的工作数据' }}</span> · 运行基准日 {{ data?.object.date_base || context.object.date_base || '无' }} · {{ experimentId ? '实验存放类别' : (objectType === 'base' ? '基本图' : 'run') + '直属类别' }}：{{ formatPath(context.object.classification_path) }}
    <p>有效基本图：{{ context.base?.name || '无' }} {{ context.base?.baseTT_no || '' }} · {{ formatPath(context.base?.classification_path || []) }}</p></div>
    <div class="diagram-controls"><label>绘图线路<select v-model="line" :disabled="snapshotMode || busy || !context.lines.length" @change="loadData('line')"><option v-for="entry in context.lines" :key="entry.line_ind" :value="String(entry.line_ind)">{{ entry.line_name_chn }}（{{ entry.line_ind }}）{{ entry.available ? '' : ' · 资料不足' }}</option></select></label>
      <label class="confirmation"><input v-model="reverse" type="checkbox" />逆序站轴</label>
      <button :disabled="!data?.can_plot || busy" @click="viewport = zoomViewport(viewport, .8)">放大</button><button :disabled="!data?.can_plot || busy" @click="viewport = zoomViewport(viewport, 1.25)">缩小</button><button :disabled="!data?.can_plot || busy" @click="resetRange()">恢复自动范围</button>
    </div>
  </template>
  <template v-if="data"><div class="diagram-filters"><details class="diagram-station-filter" :open="openPanels.includes('stations')" @toggle="panel('stations', $event)"><summary>绘图车站（{{ stationIds.length }} / {{ data.axis.stations.length }}）</summary><input v-model="stationSearch" placeholder="筛选绘图车站" /><div class="diagram-station-actions"><button @click="stationIds = data.axis.stations.map(s => s.node_id)">全选车站</button><button @click="stationIds = []">清空车站</button></div><div class="checkbox-options"><label v-for="station in stationOptions" :key="station.node_id"><input v-model="stationIds" type="checkbox" :value="station.node_id" />{{ station.node_seq_of_line }} · {{ station.node_name_chn }}</label></div></details>
    <details class="diagram-train-filter" :open="openPanels.includes('trains')" @toggle="panel('trains', $event)"><summary>绘图列车（已选 {{ trainIds.length }} / {{ data.series.length }}，显示 {{ displayed.length }}）</summary>
      <div class="diagram-train-toolbar-wrap"><table class="diagram-train-toolbar" aria-label="绘图列车显示与选择"><tbody>
        <tr><th><button type="button" :disabled="busy || !selected.length" title="按当前高亮列车更新勾选名单，之后切换高亮不改变显示" @click="showHighlightedTrains">只显示高亮列车</button></th>
          <th v-for="source in trainSources" :key="source.key" :data-source="source.key" scope="col"><label class="diagram-train-toggle" :title="source.name" :style="source.color ? { color: source.color } : undefined"><input type="checkbox" :checked="sourceEnabled(source)" :disabled="busy || !source.available" :aria-label="`显示${source.label}`" @change="setSourceEnabled(source, ($event.target as HTMLInputElement).checked)" />{{ source.label }}</label>
            <div class="diagram-train-modes" role="radiogroup" :aria-label="`${source.label}显示范围`"><label><input type="radio" :name="`${controlId}-${source.key}`" value="all" :checked="sourceMode(source.key) === 'all'" :disabled="busy || !source.available" @change="setSourceMode(source, 'all')" />全部</label><label><input type="radio" :name="`${controlId}-${source.key}`" value="selected" :checked="sourceMode(source.key) === 'selected'" :disabled="busy || !source.available" @change="setSourceMode(source, 'selected')" />所选车次</label></div>
          </th><th class="diagram-train-search"><input v-model="trainSearch" aria-label="筛选绘图车次或方案" placeholder="筛选车次或方案" /></th></tr>
        <tr><td></td><td v-for="source in trainSources" :key="source.key" :data-source="source.key"><div class="diagram-source-actions"><button type="button" :disabled="busy || !source.available" :aria-label="`${source.label}全选`" @click="selectSource(source, true)">全选</button><button type="button" :disabled="busy || !source.available" :aria-label="`${source.label}全不选`" @click="selectSource(source, false)">全不选</button></div></td><td></td></tr>
        <tr v-if="experimentId" class="experiment-train-columns"><td></td><td v-for="source in trainSources" :key="source.key" :data-source="source.key"><div class="checkbox-options experiment-source-options"><label v-for="series in sourceOptions(source)" :key="series.key"><input v-model="trainIds" type="checkbox" :value="series.key" />{{ series.train_course_id }} · {{ series.train_base_date }} <button class="diagram-inspect" @click="inspectSeries(series)">明细</button></label><p v-if="!sourceOptions(source).length">无匹配车次</p></div></td><td></td></tr>
      </tbody></table></div>
      <div v-if="!experimentId" class="checkbox-options diagram-train-options"><label v-for="(series, index) in trainOptions" :key="series.key" :class="{ 'diagram-train-divider': index > 0 && series.train_course_id.trim().toUpperCase() !== trainOptions[index - 1]?.train_course_id.trim().toUpperCase() }"><input v-model="trainIds" type="checkbox" :value="series.key" />{{ series.train_course_id }} · {{ series.object_type === 'base' ? '基本图' : series.object_name }} · {{ series.train_base_date }} <button class="diagram-inspect" @click="inspectSeries(series)">明细</button></label></div>
    </details>
    <details class="diagram-time-filter" :open="openPanels.includes('time')" @toggle="panel('time', $event)"><summary>设置时间范围</summary><label>绘图开始时间<input v-model="from" type="datetime-local" step="1" /></label><label>绘图结束时间<input v-model="to" type="datetime-local" step="1" /></label><button @click="applyTime">应用时间范围</button></details></div>
    <details class="track-controls" :open="openPanels.includes('tracks')" @toggle="panel('tracks', $event)"><summary>车站股道信息与展开（{{ expanded.length }}站已展开）</summary>
      <div class="diagram-controls"><label>股道展开车站<select v-model="trackStation" :disabled="busy"><option v-for="resource in data.track_stations" :key="resource.node_id" :value="resource.node_id">{{ resource.node_name_chn }}{{ resource.can_expand ? ` · ${resource.track_count}条股道` : ' · 无可展开股道' }}</option></select></label>
        <button :disabled="snapshotMode || busy || !trackStation" @click="toggleTrack(trackStation)">{{ expanded.includes(trackStation) ? '收起本站股道' : '展开本站股道' }}</button>
        <button :disabled="snapshotMode || busy || !expanded.length" @click="collapseTracks">收起全部股道</button>
      </div>
      <template v-if="trackResource"><p>线路 {{ trackResource.line_ind }} · {{ trackResource.node_name_chn }}：{{ trackResource.track_count }}条股道{{ trackResource.can_expand ? ` · ${trackResource.tracks.map(track => track.number).join('、')}` : '' }}</p>
        <table v-if="trackResource.can_expand" class="track-resource-table"><thead><tr><th>方向</th><th>停站到发线</th><th>正线</th></tr></thead><tbody><tr><th>下行</th><td>{{ trackResource.directions.down?.stop_tracks.join('、') || '无到发线' }}</td><td>{{ trackResource.directions.down?.main_track ?? '无' }}</td></tr><tr><th>上行</th><td>{{ trackResource.directions.up?.stop_tracks.join('、') || '无到发线' }}</td><td>{{ trackResource.directions.up?.main_track ?? '无' }}</td></tr></tbody></table>
        <p v-for="(issue,index) in trackResource.issues" :key="index" class="muted">{{ issue.message }}</p>
      </template>
      <p v-if="snapshotMode" class="muted">保存视图保留原线路及股道展开状态；需要其他线路或新的股道展开时，请从run打开当前运行图。</p>
      <p v-else class="muted">也可双击图中站名展开/收起。股道自下向上按实际编号升序，*与虚线表示正线；上边界为下行到达/上行出发，下边界相反。间距 {{ data.styles.track_gap * 5 }}px，进路系数 {{ data.styles.track_yita_seconds }}秒；占用计算仅用于绘图。</p>
    </details>
    <div class="diagram-legend"><span>基本图：主题对比色，叠加时为虚线</span><span :style="{ color: data.styles.down }">● 下行</span><span :style="{ color: data.styles.up }">● 上行</span><span :style="{ color: data.styles.unknown }">● 方向未定</span><span>时序倒置：橙色虚线</span><span style="color: #e53935">▲ 通过列车股道未判定</span></div>
    <p class="muted diagram-instruction">以鼠标位置为中心：滚轮同步缩放两轴，Ctrl+滚轮仅缩放时间轴，Shift+滚轮仅缩放车站轴；拖动平移。底部拖柄可调整绘图高度；右上角可全屏/Dock、恢复两轴或分别恢复时间轴/车站轴。方向键平移，+/-缩放，Home恢复；点击运行线高亮，Ctrl+点击多选。筛选保留完整站轴间距和已有断点；双击站名展开/收起股道。</p>
    <p v-if="data.can_plot" class="diagram-range" role="status">当前时间范围：{{ timeLabel(viewport.x0, true) }} ～ {{ timeLabel(viewport.x1, true) }} · {{ displayed.length }}组列车 · 站轴按 NODE_SEQ_OF_LINE / PASS→PASS</p>
    <DiagramCanvas v-if="ready" ref="canvasRef" v-model:viewport="viewport" :busy="busy" :initial-height="restoredHeight" :data="data" :series="displayed" :station-ids="stationIds" :selected="selected" :reverse="reverse" @select="highlight" @reset="resetRange()" @reset-time="resetRange('time')" @reset-station="resetRange('station')" @toggle-track="toggleTrack" />
    <p v-else-if="!busy" class="empty-state">{{ data.can_plot ? '当前筛选没有可绘制的数据，请选择车站和列车。' : '该运行图暂不能绘制，请查看下方具体问题。' }}</p>
    <details :open="detailOpen" @toggle="detailOpen = ($event.target as HTMLDetailsElement).open">
      <summary>所选列车时刻明细（{{ selectedDetails.length }}组列车）</summary>
      <p class="muted">各列车按车站对齐显示。Ctrl+点击运行线可多选，也可在下方勾选需要对比的列车；同车次的基本图与run分别列出。</p>
      <details :open="openPanels.includes('details-trains')" @toggle="panel('details-trains', $event)">
        <summary>选择明细列车</summary>
        <div class="checkbox-options">
          <label v-for="train in orderedTrains" :key="train.key">
            <input v-model="selected" type="checkbox" :value="train.key" />
            {{ train.train_course_id }} · {{ train.object_type === 'base' ? '基本图' : train.object_name }} · {{ train.train_base_date }}
          </label>
        </div>
      </details>
      <button :disabled="!selected.length" @click="selected = []">清空选择</button>
      <DiagramTrainDetails v-if="detailOpen && selectedDetails.length" :series="selectedDetails" :stations="data.axis.stations" :date-base="data.object.date_base || ''" />
      <p v-else-if="!selectedDetails.length" class="empty-state">请选择需要对比的列车。</p>
    </details>
    <details v-if="!snapshotMode" :open="openPanels.includes('styles')" @toggle="panel('styles', $event)"><summary>样式配置</summary><p class="muted">{{ data.style_source }}；可设置上下行/基本图颜色、十分钟网格、线宽、track_gap（单位5px）、track_yita_seconds（秒）和按系列key配置单车样式。保存JSON后数秒内自动应用，也可点击“刷新图形数据和样式”。所选列车样式key：{{ selectedDetails.map(series => series.key).join('、') || '请选择列车' }}。</p></details>
  </template>
  <details class="diagram-issues" :open="openPanels.includes('issues') || (!snapshotMode && issues.some(i => i.severity === 'error'))" @toggle="panel('issues', $event)"><summary>绘图提示（{{ issues.length }}）</summary><ul><li v-for="(issue,index) in issues" :key="index" :class="issue.severity === 'error' ? 'error' : 'muted'">{{ issue.severity === 'error' ? '错误' : '提示' }}：{{ issue.message }}</li></ul><p v-if="data">{{ !issues.length ? '本次无绘图提示。' : data.log_written && styleLogWritten ? '本次提示已记录于绘图日志。' : '日志写入失败，请核对日志目录。' }}</p><button @click="readLog">查看绘图日志</button><pre v-if="logText" class="diagram-log">{{ logText }}</pre></details>
</component></template>
