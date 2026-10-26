<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { formatPath, type Change } from '../api/baseImport'
import { diagramApi, type PlotContext, type PlotData, type PlotSeries, type PlotIssue } from '../api/diagram'
import { fitViewport, localTime, timeLabel, timeRange, zoomViewport, type Viewport } from '../diagramGeometry'
import DiagramCanvas from './DiagramCanvas.vue'
import DiagramTrainDetails from './DiagramTrainDetails.vue'
const props = defineProps<{ objectType: 'base' | 'run'; objectId: string; revision: string; dateBase: string; originalDateBase: string; changes: Change[]; initialLine: string }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null), previousFocus = document.activeElement as HTMLElement | null
const context = ref<PlotContext | null>(null), data = ref<PlotData | null>(null), busy = ref(false), error = ref('')
const line = ref(''), overlay = ref(false), reverse = ref(false), stationIds = ref<string[]>([]), trainIds = ref<string[]>([]), selected = ref<string[]>([])
const stationSearch = ref(''), trainSearch = ref(''), from = ref(''), to = ref(''), logText = ref(''), detailOpen = ref(false)
const expanded = ref<string[]>([]), trackStation = ref('')
const trackResource = computed(() => data.value?.track_stations.find(resource => resource.node_id === trackStation.value))
const viewport = ref<Viewport>({ x0: 0, x1: 3600, y0: 0, y1: 1000 })
let generation = 0, styleTimer: number | undefined, loadingStyles = false
const styleIssues = ref<PlotIssue[]>([]), styleLogWritten = ref(true)
const hasDraft = computed(() => props.changes.length > 0 || props.dateBase !== props.originalDateBase)
const displayed = computed(() => data.value?.series.filter(series => trainIds.value.includes(series.key)) || [])
const stationOptions = computed(() => data.value?.axis.stations.filter(s => `${s.node_name_chn} ${s.node_name}`.includes(stationSearch.value)) || [])
const trainOptions = computed(() => data.value?.series.filter(s => `${s.train_course_id} ${s.object_name} ${s.train_base_date}`.includes(trainSearch.value)) || [])
const issues = computed(() => data.value ? [...data.value.issues.filter(i => i.code !== 'style_config'), ...styleIssues.value] : context.value?.issues || [])
const selectedDetails = computed(() => {
  const byKey = new Map(data.value?.series.map(series => [series.key, series]) || [])
  return selected.value.map(key => byKey.get(key)).filter((series): series is PlotSeries => !!series)
})
const ready = computed(() => data.value?.can_plot && stationIds.value.length && displayed.value.some(s => s.points.length))
function resetRange() {
  if (!data.value) return
  const stations = data.value.axis.stations.filter(s => stationIds.value.includes(s.node_id))
  viewport.value = fitViewport(data.value, stations)
  from.value = localTime(data.value.object.date_base || '', Math.max(0, viewport.value.x0))
  to.value = localTime(data.value.object.date_base || '', viewport.value.x1)
}
function reconcile(previous: string[], old: string[], incoming: string[]) {
  return incoming.filter(id => previous.includes(id) || !old.includes(id))
}
async function loadData(reason: 'line' | 'overlay' | 'refresh' | 'tracks' | 'style') {
  if (!context.value || !line.value) return
  if (reason === 'line') { expanded.value = []; trackStation.value = '' }
  const version = ++generation, old = data.value
  busy.value = true; error.value = ''; logText.value = ''
  try {
    const result = await diagramApi.data({ object_type: props.objectType, object_id: props.objectId, line_ind: Number(line.value),
      revision: hasDraft.value ? props.revision : context.value.revision, overlay_base: overlay.value, expanded_stations: expanded.value,
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
  busy.value = true; error.value = ''
  try {
    const previousRevision = context.value?.revision
    context.value = await diagramApi.context(props.objectType, props.objectId)
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
  if (busy.value) return
  trackStation.value = id
  if (!stationIds.value.includes(id)) stationIds.value = [...stationIds.value, id]
  expanded.value = expanded.value.includes(id) ? expanded.value.filter(value => value !== id) : [...expanded.value, id]
  await loadData('tracks')
}
async function collapseTracks() { if (!busy.value) { expanded.value = []; await loadData('tracks') } }
async function readLog() { try { const log = await diagramApi.log(); logText.value = `${log.filename}\n${log.text}` } catch (e) { error.value = String(e) } }
async function refreshStyles() {
  if (busy.value || !data.value || loadingStyles) return
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
onMounted(async () => { await nextTick(); dialog.value?.showModal(); await reload(true); styleTimer = window.setInterval(refreshStyles, 4000) })
onUnmounted(() => { generation++; if (styleTimer) window.clearInterval(styleTimer); previousFocus?.focus() })
</script>
<template><dialog ref="dialog" class="diagram-dialog" aria-labelledby="diagram-title" @cancel.prevent="emit('close')">
  <div class="diagram-heading"><h2 id="diagram-title">运行图 · {{ data?.object.name || context?.object.name || (objectType === 'base' ? '基本图' : 'run') }}</h2><div><button :disabled="busy" @click="reload()">刷新图形数据和样式</button> <button @click="emit('close')">返回时刻表</button></div></div>
  <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="busy" role="status">正在读取运行图…</p>
  <template v-if="context"><div class="diagram-context"><span>{{ data?.preview ? `预览未保存草稿（${data.preview_changes}个单元格）` : '已保存的工作数据' }}</span> · 运行基准日 {{ data?.object.date_base || context.object.date_base || '无' }} · {{ objectType === 'base' ? '基本图' : 'run' }}直属类别：{{ formatPath(context.object.classification_path) }}
    <p>有效基本图：{{ context.base?.name || '无' }} {{ context.base?.baseTT_no || '' }} · {{ formatPath(context.base?.classification_path || []) }}</p></div>
    <div class="diagram-controls"><label>绘图线路<select v-model="line" :disabled="busy || !context.lines.length" @change="loadData('line')"><option v-for="entry in context.lines" :key="entry.line_ind" :value="String(entry.line_ind)">{{ entry.line_name_chn }}（{{ entry.line_ind }}）{{ entry.available ? '' : ' · 资料不足' }}</option></select></label>
      <label class="confirmation"><input v-model="reverse" type="checkbox" />逆序站轴</label><label v-if="objectType === 'run'" class="confirmation"><input v-model="overlay" type="checkbox" :disabled="busy || !context.base" @change="loadData('overlay')" />叠加有效基本图</label>
      <button :disabled="!data?.can_plot || busy" @click="viewport = zoomViewport(viewport, .8)">放大</button><button :disabled="!data?.can_plot || busy" @click="viewport = zoomViewport(viewport, 1.25)">缩小</button><button :disabled="!data?.can_plot || busy" @click="resetRange">恢复自动范围</button>
    </div>
  </template>
  <template v-if="data"><div class="diagram-filters"><details><summary>绘图车站（{{ stationIds.length }} / {{ data.axis.stations.length }}）</summary><input v-model="stationSearch" placeholder="筛选绘图车站" /><button @click="stationIds = data.axis.stations.map(s => s.node_id)">全选车站</button> <button @click="stationIds = []">清空车站</button><div class="checkbox-options"><label v-for="station in stationOptions" :key="station.node_id"><input v-model="stationIds" type="checkbox" :value="station.node_id" />{{ station.node_seq_of_line }} · {{ station.node_name_chn }}</label></div></details>
    <details><summary>绘图列车（{{ trainIds.length }} / {{ data.series.length }}）</summary><input v-model="trainSearch" placeholder="筛选绘图车次或方案" /><button @click="trainIds = data.series.map(s => s.key)">全部显示</button> <button @click="trainIds = []">全部隐藏</button> <button :disabled="!selected.length" @click="trainIds = selected.slice()">只显示高亮列车</button><div class="checkbox-options"><label v-for="series in trainOptions" :key="series.key"><input v-model="trainIds" type="checkbox" :value="series.key" />{{ series.train_course_id }} · {{ series.object_type === 'base' ? '基本图' : series.object_name }} · {{ series.train_base_date }} <button class="diagram-inspect" @click="inspectSeries(series)">明细</button></label></div></details>
    <details><summary>设置时间范围</summary><label>绘图开始时间<input v-model="from" type="datetime-local" step="1" /></label><label>绘图结束时间<input v-model="to" type="datetime-local" step="1" /></label><button @click="applyTime">应用时间范围</button></details></div>
    <details class="track-controls"><summary>车站股道信息与展开（{{ expanded.length }}站已展开）</summary>
      <div class="diagram-controls"><label>股道展开车站<select v-model="trackStation" :disabled="busy"><option v-for="resource in data.track_stations" :key="resource.node_id" :value="resource.node_id">{{ resource.node_name_chn }}{{ resource.can_expand ? ` · ${resource.track_count}条股道` : ' · 无可展开股道' }}</option></select></label>
        <button :disabled="busy || !trackStation" @click="toggleTrack(trackStation)">{{ expanded.includes(trackStation) ? '收起本站股道' : '展开本站股道' }}</button>
        <button :disabled="busy || !expanded.length" @click="collapseTracks">收起全部股道</button>
      </div>
      <template v-if="trackResource"><p>线路 {{ trackResource.line_ind }} · {{ trackResource.node_name_chn }}：{{ trackResource.track_count }}条股道{{ trackResource.can_expand ? ` · ${trackResource.tracks.map(track => track.number).join('、')}` : '' }}</p>
        <table v-if="trackResource.can_expand" class="track-resource-table"><thead><tr><th>方向</th><th>停站到发线</th><th>正线</th></tr></thead><tbody><tr><th>下行</th><td>{{ trackResource.directions.down?.stop_tracks.join('、') || '无到发线' }}</td><td>{{ trackResource.directions.down?.main_track ?? '无' }}</td></tr><tr><th>上行</th><td>{{ trackResource.directions.up?.stop_tracks.join('、') || '无到发线' }}</td><td>{{ trackResource.directions.up?.main_track ?? '无' }}</td></tr></tbody></table>
        <p v-for="(issue,index) in trackResource.issues" :key="index" class="muted">{{ issue.message }}</p>
      </template>
      <p class="muted">也可双击图中站名展开/收起。股道自下向上按实际编号升序，*与虚线表示正线；上边界为下行到达/上行出发，下边界相反。间距 {{ data.styles.track_gap * 5 }}px，进路系数 {{ data.styles.track_yita_seconds }}秒；占用计算仅用于绘图。</p>
    </details>
    <div class="diagram-legend"><span>基本图：主题对比色，叠加时为虚线</span><span :style="{ color: data.styles.down }">● 下行</span><span :style="{ color: data.styles.up }">● 上行</span><span :style="{ color: data.styles.unknown }">● 方向未定</span><span>时序倒置：橙色虚线</span><span style="color: #e53935">▲ 通过列车股道未判定</span></div>
    <p class="muted diagram-instruction">以鼠标位置为中心：滚轮同步缩放两轴，Ctrl+滚轮仅缩放时间轴，Shift+滚轮仅缩放车站轴；拖动平移。方向键平移，+/-缩放，Home恢复；点击运行线高亮，Ctrl+点击多选。筛选保留完整站轴间距和已有断点；双击站名展开/收起股道。</p>
    <p v-if="data.can_plot" class="diagram-range" role="status">当前时间范围：{{ timeLabel(viewport.x0, true) }} ～ {{ timeLabel(viewport.x1, true) }} · {{ displayed.length }}组列车 · 站轴按 NODE_SEQ_OF_LINE / PASS→PASS</p>
    <DiagramCanvas v-if="ready && !busy" v-model:viewport="viewport" :data="data" :series="displayed" :station-ids="stationIds" :selected="selected" :reverse="reverse" @select="highlight" @reset="resetRange" @toggle-track="toggleTrack" />
    <p v-else-if="!busy" class="empty-state">{{ data.can_plot ? '当前筛选没有可绘制的数据，请选择车站和列车。' : '该运行图暂不能绘制，请查看下方具体问题。' }}</p>
    <details :open="detailOpen" @toggle="detailOpen = ($event.target as HTMLDetailsElement).open">
      <summary>所选列车时刻明细（{{ selectedDetails.length }}组列车）</summary>
      <p class="muted">各列车按车站对齐显示。Ctrl+点击运行线可多选，也可在下方勾选需要对比的列车；同车次的基本图与run分别列出。</p>
      <details>
        <summary>选择明细列车</summary>
        <div class="checkbox-options">
          <label v-for="train in data.series" :key="train.key">
            <input v-model="selected" type="checkbox" :value="train.key" />
            {{ train.train_course_id }} · {{ train.object_type === 'base' ? '基本图' : train.object_name }} · {{ train.train_base_date }}
          </label>
        </div>
      </details>
      <button :disabled="!selected.length" @click="selected = []">清空选择</button>
      <DiagramTrainDetails v-if="detailOpen && selectedDetails.length" :series="selectedDetails" :stations="data.axis.stations" :date-base="data.object.date_base || ''" />
      <p v-else-if="!selectedDetails.length" class="empty-state">请选择需要对比的列车。</p>
    </details>
    <details><summary>样式配置</summary><p class="muted">{{ data.style_source }}；可设置上下行/基本图颜色、十分钟网格、线宽、track_gap（单位5px）、track_yita_seconds（秒）和按系列key配置单车样式。保存JSON后数秒内自动应用，也可点击“刷新图形数据和样式”。所选列车样式key：{{ selectedDetails.map(series => series.key).join('、') || '请选择列车' }}。</p></details>
  </template>
  <details class="diagram-issues" :open="issues.some(i => i.severity === 'error')"><summary>绘图提示（{{ issues.length }}）</summary><ul><li v-for="(issue,index) in issues" :key="index" :class="issue.severity === 'error' ? 'error' : 'muted'">{{ issue.severity === 'error' ? '错误' : '提示' }}：{{ issue.message }}</li></ul><p v-if="data">{{ !issues.length ? '本次无绘图提示。' : data.log_written && styleLogWritten ? '本次提示已记录于绘图日志。' : '日志写入失败，请核对日志目录。' }}</p><button @click="readLog">查看绘图日志</button><pre v-if="logText" class="diagram-log">{{ logText }}</pre></details>
</dialog></template>
