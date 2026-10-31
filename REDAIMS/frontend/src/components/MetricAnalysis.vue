<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { analysisApi, type DelaySnapshot, type MetricDisplay, type MetricId, type SavedMetrics } from '../api/analysis'
import { defaultMetricCamera, defaultTimeHeatmap, finite, initialMetrics, metricDefinition, metricIds, metricPresets, normalizeMetricSelection, rankCurveTrains, summarizeMetrics } from '../performanceMetrics'
import { buildDelay3D, delayTrainColor } from '../delay3D'
import DelayPlot3D from './DelayPlot3D.vue'
import DelayTimeHeatmap from './DelayTimeHeatmap.vue'

const props = defineProps<{ runId: string; runName?: string; initial?: SavedMetrics; seed?: DelaySnapshot; allowSave?: boolean }>()
const emit = defineEmits<{ back: []; save: [] }>()
const data = shallowRef<DelaySnapshot | null>(null), state = ref<MetricDisplay | null>(null)
const busy = ref(false), error = ref(''), frozen = ref(false), preset = ref('common')
const drawerOpen = ref(false), draft = ref<MetricId[]>([]), drawerError = ref(''), explained = ref<MetricId>('total')
const stationSearch = ref(''), trainSearch = ref(''), curveSearch = ref('')
const curvePickerOpen = ref(false), curveListPage = ref(0)
const curveStationOpen = ref(false), curveStationSearch = ref(''), curveStationPage = ref(0)
const curveLegendPage = ref(0)
const heading = ref<HTMLElement | null>(null), configButton = ref<HTMLButtonElement | null>(null), drawerHeading = ref<HTMLElement | null>(null)
const curveContainer = ref<HTMLElement | null>(null), curveWidth = ref(640)
let closed = false, generation = 0, observer: ResizeObserver | undefined
const summary = computed(() => data.value && state.value ? summarizeMetrics(data.value, state.value) : null)
const divisor = computed(() => state.value?.unit === 'seconds' ? 1 : 60)
const unit = computed(() => state.value?.unit === 'seconds' ? '秒' : '分钟')
const threshold = computed(() => state.value ? state.value.threshold_seconds / divisor.value : 0)
const terminalOpen = ref(false), terminalPage = ref(0)
const terminalOffset = computed(() => Math.min(terminalPage.value * 20, Math.max(0, Math.floor(((summary.value?.terminalDelayed.length || 1) - 1) / 20) * 20)))
const terminalPageRows = computed(() => summary.value?.terminalDelayed.slice(terminalOffset.value, terminalOffset.value + 20) || [])
const maximumTrainNames = computed(() => {
  const trains = summary.value?.maxTrains || []
  const counts = new Map<string, number>()
  for (const train of trains) counts.set(train.train_course_id, (counts.get(train.train_course_id) || 0) + 1)
  return trains.map(t => t.train_course_id + ((counts.get(t.train_course_id) || 0) > 1 ? '（' + t.train_base_date + '）' : ''))
})
const maximumGroups = computed(() => {
  const locations = new Map<string, Set<string>>()
  for (const event of summary.value?.maxEvents || []) {
    if (!locations.has(event.train_id)) locations.set(event.train_id, new Set())
    locations.get(event.train_id)!.add(event.station + (event.occurrence > 1 ? ' #' + event.occurrence : ''))
  }
  return (summary.value?.maxTrains || []).map((train,i) => ({ train: maximumTrainNames.value[i], stations: [...(locations.get(train.id) || [])] }))
})
const maximumLocations = computed(() => maximumGroups.value.map(group => group.train + '（' + group.stations.join('、') + '）'))
const maximumCaption = computed(() => maximumGroups.value.length
  ? '列车 ' + maximumGroups.value.slice(0,3).map(group => group.train + '（' + group.stations.slice(0,2).join('、') + (group.stations.length>2?'等'+group.stations.length+'处':'') + '）').join('、') + (maximumGroups.value.length > 3 ? '等' + maximumGroups.value.length + '列车' : '')
  : summary.value?.count ? '无晚点列车' : '无有效样本')
const includeZeroMean = computed({
  get: () => (state.value?.event==='departure'?state.value.include_zero_departures:state.value?.include_zero_arrivals)!==false,
  set: (value:boolean) => {
    if(!state.value)return
    if(state.value.event==='departure')state.value.include_zero_departures=value
    else state.value.include_zero_arrivals=value
  },
})
const info = (id: MetricId) => metricDefinition(id, state.value?.event || 'arrival', includeZeroMean.value)
function format(value: number | null | undefined, kind: 'time' | 'percent' | 'count' = 'time') {
  if (!finite(value)) return '—'
  const number = kind === 'time' ? value / divisor.value : value
  return (Math.round(number * 100) / 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}
function signed(value: number | null | undefined) { return finite(value) ? (value > 0 ? '+' : '') + format(value) : '—' }
const stationOptions = computed(() => (data.value?.stations || []).filter(s => (s.node_name + s.node_name_chn).includes(stationSearch.value)))
const trainOptions = computed(() => (data.value?.trains || []).filter(t => (t.train_course_id + ' ' + t.train_base_date).includes(trainSearch.value)))
const rankedCurveTrains = computed(() => data.value ? rankCurveTrains(data.value) : [])
const eligibleCurveTrains = computed(() => {
  const allowed = new Set(summary.value?.trains.map(t => t.id) || [])
  return rankedCurveTrains.value.filter(t => allowed.has(t.id))
})
const curveMatches = computed(() => eligibleCurveTrains.value.filter(t => (t.train_course_id + ' ' + t.train_base_date + ' ' + t.train_base_date.replaceAll('-','/')).includes(curveSearch.value)))
const curveListOffset = computed(() => Math.min(curveListPage.value*80,Math.max(0,Math.floor((curveMatches.value.length-1)/80)*80)))
const curveOptions = computed(() => curveMatches.value.slice(curveListOffset.value,curveListOffset.value+80))
const curveTrains = computed(() => {
  const selected=new Set(state.value?.curve_train_ids || [])
  return eligibleCurveTrains.value.filter(t=>selected.has(t.id))
})
const curveLegendOffset = computed(() => Math.min(curveLegendPage.value*80,Math.max(0,Math.floor((curveTrains.value.length-1)/80)*80)))
const curveLegendTrains = computed(() => curveTrains.value.slice(curveLegendOffset.value,curveLegendOffset.value+80))
const trainColorStyle = (id:string) => ({'--curve-train-color':delayTrainColor(id),'--curve-train-color-dark':delayTrainColor(id,true)})
const curveStationPool = computed(() => {
  const visited = new Set(data.value?.rows.map(r=>r.station_id) || [])
  return (data.value?.stations || []).filter(s=>visited.has(s.id))
})
const curveStationMatches = computed(() => curveStationPool.value.filter(s=>(s.node_name+' '+s.node_name_chn).includes(curveStationSearch.value)))
const curveStationOffset = computed(() => Math.min(curveStationPage.value*80,Math.max(0,Math.floor((curveStationMatches.value.length-1)/80)*80)))
const curveStationOptions = computed(() => curveStationMatches.value.slice(curveStationOffset.value,curveStationOffset.value+80))
const selectedCurveStations = computed(() => {
  const selected=new Set(state.value?.curve_station_ids || [])
  return curveStationPool.value.filter(s=>selected.has(s.id))
})
const curveStationLabel = computed(() => {
  const selected=selectedCurveStations.value
  if(!selected.length)return '绘图车站：请选择（可多选）'
  if(selected.length===curveStationPool.value.length)return '绘图车站：全部 '+selected.length+' 个'
  return '绘图车站：'+(selected.length===1?selected[0].node_name_chn:'已选择 '+selected.length+' 个')
})
function checkCurveStation(id:string,checked:boolean){
  if(!state.value)return
  const selected=new Set(state.value.curve_station_ids || [])
  if(checked)selected.add(id);else selected.delete(id)
  state.value.curve_station_ids=[...selected]
}
const scene3D = computed(() => data.value ? buildDelay3D(data.value,curveTrains.value.map(t=>t.id),state.value?.curve_fields || [],state.value?.curve_station_ids) : null)
const curveSelectionLabel = computed(()=>curveTrains.value.length===1?curveOptionLabel(curveTrains.value[0]):curveTrains.value.length?'已选择 '+curveTrains.value.length+' 列车（可多选）':'选择列车（可多选）')
function curveOptionLabel(train: ReturnType<typeof rankCurveTrains>[number]) {
  const average = train.meanLateArrival === null ? (train.arrivalCount ? '无到达晚点事件' : '无可计算到达事件')
    : '平均到达延误 ' + (Math.round(train.meanLateArrival / 60 * 100) / 100).toLocaleString('zh-CN', {maximumFractionDigits:2}) + '分钟'
  return train.train_course_id + '  ' + train.train_base_date.replaceAll('-','/') + ' (' + average + ')'
}
function checkCurveTrain(id:string,checked:boolean){
  if(!state.value)return
  const selected=new Set(state.value.curve_train_ids||[])
  if(checked)selected.add(id);else selected.delete(id)
  state.value.curve_train_ids=[...selected]
  if(checked)state.value.active_train_id=id
  else if(state.value.active_train_id===id)state.value.active_train_id=state.value.curve_train_ids[0]||''
}
function selectMatchedCurves(){
  if(!state.value)return
  state.value.curve_train_ids=[...new Set([...(state.value.curve_train_ids||[]),...curveMatches.value.map(t=>t.id)])]
}
function clearCurves(){if(state.value){state.value.curve_train_ids=[];state.value.active_train_id=''}}
function pickCurveTrain(id:string){
  if(!state.value)return
  const selected=state.value.curve_train_ids||[]
  if(!selected.includes(id))state.value.curve_train_ids=selected.length>1?[...selected,id]:[id]
  state.value.active_train_id=id
}
const byCell = computed(() => new Map((data.value?.cells || []).map(c => [c.row_key + '|' + c.train_id, c])))
const cell = (row: string, train: string) => byCell.value.get(row + '|' + train)
const rowOffset = computed(() => Math.min(state.value?.row_offset || 0, Math.max(0, Math.floor(((summary.value?.rows.length || 1) - 1) / 25) * 25)))
const trainOffset = computed(() => Math.min(state.value?.train_offset || 0, Math.max(0, Math.floor(((summary.value?.trains.length || 1) - 1) / 20) * 20)))
const pageRows = computed(() => summary.value?.rows.slice(rowOffset.value, rowOffset.value + 25) || [])
const pageTrains = computed(() => summary.value?.trains.slice(trainOffset.value, trainOffset.value + 20) || [])
const selectedCell = ref<{ row: string; train: string } | null>(null)
const selectedDetail = computed(() => {
  if (!selectedCell.value || !data.value || !state.value) return ''
  const row = data.value.rows.find(r => r.key === selectedCell.value!.row)
  const train = data.value.trains.find(t => t.id === selectedCell.value!.train)
  const value = cell(selectedCell.value.row, selectedCell.value.train)
  const field = state.value.event, reason = value?.[field === 'arrival' ? 'arrival_reason' : 'departure_reason']
  return [train?.train_course_id, row?.node_name_chn, field === 'arrival' ? '到达偏差' : '出发偏差', signed(value?.[field]) + (finite(value?.[field]) ? unit.value : ''), reason || (!value ? 'run未访问本站' : '')].filter(Boolean).join(' · ')
})
function pickCell(row: string, train: string) {
  selectedCell.value = { row, train }
  pickCurveTrain(train)
}
function heatStyle(value: number | null | undefined) {
  if (!finite(value) || !value) return {}
  const max = summary.value?.values.max || 1
  const intensity = Math.min(45, 10 + Math.abs(value) / max * 35)
  return { backgroundColor: 'color-mix(in srgb, var(' + (value < 0 ? '--metric-early' : '--metric-late') + ') ' + intensity + '%, var(--surface))' }
}
function resetPages() { if (state.value) { state.value.row_offset = 0; state.value.train_offset = 0 } }
function applyPreset() {
  if (state.value && metricPresets[preset.value]) { state.value.selected = [...metricPresets[preset.value]]; explained.value = state.value.selected[0] }
}
function setThreshold(text: string) {
  const value = Number(text)
  if (!text.trim() || !finite(value) || value < 0 || value * divisor.value > 86400) { error.value = '晚点阈值须为0至86400秒之间的数值。'; return }
  if (state.value) state.value.threshold_seconds = value * divisor.value
  error.value = ''
}
async function openDrawer() {
  draft.value = [...(state.value?.selected || [])]; drawerError.value = ''; drawerOpen.value = true
  await nextTick(); drawerHeading.value?.focus()
}
function closeDrawer() { drawerOpen.value = false; void nextTick(() => configButton.value?.focus()) }
function applyMetrics() {
  if (draft.value.length < 2 || draft.value.length > 6) { drawerError.value = '请选择2至6个总览指标。'; return }
  if (state.value) state.value.selected = [...draft.value]
  if (!draft.value.includes(explained.value)) explained.value = draft.value[0]
  preset.value = 'custom'; closeDrawer()
}
function cancel() { if (drawerOpen.value) closeDrawer(); else if(curveStationOpen.value)curveStationOpen.value=false;else if(curvePickerOpen.value)curvePickerOpen.value=false;else if(terminalOpen.value)terminalOpen.value=false;else emit('back') }
function install(snapshot: DelaySnapshot, settings?: MetricDisplay) {
  data.value = snapshot
  state.value = settings ? JSON.parse(JSON.stringify(settings)) : initialMetrics(snapshot)
  const current = state.value!
  current.include_zero_arrivals ??= true
  current.include_zero_departures ??= true
  current.selected = normalizeMetricSelection(current.selected)
  const stations = new Set(snapshot.stations.map(s => s.id)), trains = new Set(snapshot.trains.map(t => t.id))
  current.station_ids = current.station_ids.filter(id => stations.has(id))
  current.train_ids = current.train_ids.filter(id => trains.has(id))
  if (!trains.has(current.active_train_id)) current.active_train_id = snapshot.trains[0]?.id || ''
  current.curve_train_ids=[...new Set(current.curve_train_ids ?? (current.active_train_id?[current.active_train_id]:[]))].filter(id=>trains.has(id))
  current.curve_station_ids=[...new Set(current.curve_station_ids ?? snapshot.stations.map(s=>s.id))].filter(id=>stations.has(id))
  current.curve_mode ??= '2d'
  current.curve_fields=[...new Set(current.curve_fields??['arrival','departure'])].filter(field=>field==='arrival'||field==='departure')
  current.curve_camera={...defaultMetricCamera(),...current.curve_camera}
  current.time_heatmap={...defaultTimeHeatmap(),...current.time_heatmap}
  const found = Object.entries(metricPresets).find(([, ids]) => JSON.stringify(ids) === JSON.stringify(current.selected))
  preset.value = found?.[0] || 'custom'
}
async function load() {
  const version = ++generation
  busy.value = true; error.value = ''
  try {
    const result = await analysisApi.delays(props.runId)
    if (closed || version !== generation) return
    install(result, state.value || undefined); frozen.value = false; selectedCell.value = null
  } catch (e) { if (!closed && version === generation) error.value = String(e) }
  finally { if (!closed && version === generation) busy.value = false }
}
function capture(): SavedMetrics | null {
  if (!data.value || !state.value) return null
  return JSON.parse(JSON.stringify({ state: { ...state.value, row_offset: rowOffset.value, train_offset: trainOffset.value }, snapshot: data.value }))
}
defineExpose({ capture, isBusy: () => busy.value, focus: () => heading.value?.focus(), cancel })
watch(() => props.runId, () => {
  generation++; data.value = null; state.value = null; selectedCell.value = null; drawerOpen.value = false
  stationSearch.value = ''; trainSearch.value = ''; curveSearch.value = ''
  terminalOpen.value = false; terminalPage.value = 0
  curvePickerOpen.value=false;curveListPage.value=0
  curveStationOpen.value=false;curveStationSearch.value='';curveStationPage.value=0
  curveLegendPage.value=0
  if (props.initial?.snapshot.object.id === props.runId) {
    install(JSON.parse(JSON.stringify(props.initial.snapshot)), props.initial.state); frozen.value = true
  } else if (props.seed?.object.id === props.runId) {
    install(props.seed); frozen.value = true
  } else void load()
}, { immediate: true })
watch(() => summary.value?.terminalDelayed, () => { terminalPage.value = 0 })
watch([curveSearch,()=>summary.value?.trains.map(t=>t.id).join('|')],()=>{curveListPage.value=0})
watch(curveStationSearch,()=>{curveStationPage.value=0})
watch(()=>curveTrains.value.map(t=>t.id).join('|'),()=>{curveLegendPage.value=0})
watch(() => summary.value?.trains.map(t => t.id), ids => {
  if (state.value && ids && !ids.includes(state.value.active_train_id)) state.value.active_train_id = state.value.curve_train_ids?.find(id=>ids.includes(id)) || ids[0] || ''
})
const curve = computed(() => {
  const width = curveWidth.value, left = 58, right = width - 22, top = 26, bottom = 228
  const scene = scene3D.value
  let rows = scene?.stations || []
  // Keep a single train in route order; multiple trains share station positions.
  if (scene?.trains.length === 1) {
    const sequence = new Map((data.value?.cells || []).filter(c=>c.train_id===scene.trains[0].id).map(c=>[c.row_key,c.visit_seq]))
    rows = [...rows].sort((a,b)=>(sequence.get(a.key)||0)-(sequence.get(b.key)||0))
  }
  const indices = new Map(rows.map((r,i)=>[r.key,i]))
  const x = (i:number) => left+(rows.length>1?i/(rows.length-1):.5)*(right-left)
  const y0 = scene?.zMin ?? -30, y1 = scene?.zMax ?? 30
  const y = (value:number) => bottom-(value-y0)/(y1-y0)*(bottom-top)
  const labelCount = Math.min(rows.length,Math.max(2,Math.floor((right-left)/95)))
  const labelIndices = new Set(Array.from({length:labelCount},(_,i)=>Math.round(i*(rows.length-1)/Math.max(1,labelCount-1))))
  const labels = rows.map((r,i)=>({x:x(i),key:r.key,label:r.node_name_chn+(r.occurrence>1?'#'+r.occurrence:''),index:i})).filter((_,i)=>labelIndices.has(i))
  const names = new Map(curveTrains.value.map(t=>[t.id,t.train_course_id+' · '+t.train_base_date.replaceAll('-','/')]))
  const traces = scene?.traces || []
  // All samples remain in paths; bound optional markers across the entire plot.
  const markerBudget = Math.floor(1200/Math.max(1,traces.length))
  const plots = traces.map(trace=>{
    let path = '', ordinal = 0
    const total = trace.pieces.reduce((sum,piece)=>sum+piece.length,0)
    const stride = Math.max(1,Math.ceil(total/Math.max(1,markerBudget)))
    const points:{x:number;y:number;label:string;rowKey:string}[] = []
    for(const piece of trace.pieces)piece.forEach((point,i)=>{
      const index = indices.get(point.rowKey)!
      path += (i?' L':'M')+x(index)+' '+y(point.z)
      if(piece.length===1)path += ' L'+x(index)+' '+y(point.z)
      if(markerBudget>0&&ordinal++%stride===0)points.push({x:x(index),y:y(point.z),rowKey:point.rowKey,label:names.get(trace.trainId)+' · '+rows[index].node_name_chn+(rows[index].occurrence>1?' #'+rows[index].occurrence:'')+' · '+(trace.field==='arrival'?'到达':'出发')+signed(point.seconds)+unit.value})
    })
    return {field:trace.field,trainId:trace.trainId,path,points,name:names.get(trace.trainId)}
  })
  return {width,left,right,top,bottom,labels,plots,empty:!scene?.pointCount,zero:y(0),ticks:Array.from({length:5},(_,i)=>{const v=y0+(y1-y0)*i/4;return {y:y(v),text:format(v)}})}
})
onMounted(() => {
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(entries => { const width = entries[0]?.contentRect.width; if (width && width >= 180) curveWidth.value = width })
    if (curveContainer.value) observer.observe(curveContainer.value)
  }
})
// The result can arrive after mount, so attach the observer when the plot is created.
watch(curveContainer, (node, old) => { if (old) observer?.unobserve(old); if (node) observer?.observe(node) })
onUnmounted(() => { closed = true; generation++; observer?.disconnect() })
</script>
<template>
  <section class="metric-analysis" aria-label="指标分析" @keydown.esc.stop.prevent="cancel">
    <div class="analysis-heading">
      <div><h2 id="metric-analysis-title" ref="heading" tabindex="-1">指标分析<span v-if="runName"> · {{ runName }}</span></h2><span class="muted">单个run · {{ data?.base.name || '读取有效基本图' }}</span></div>
      <div class="catalog-actions"><button type="button" @click="emit('back')">返回运行图分析工作区</button><button v-if="allowSave !== false" type="button" :disabled="!data || busy" @click="emit('save')">保存指标分析</button><button type="button" :disabled="busy" @click="load">{{ busy ? '正在读取…' : '重新计算当前已保存数据' }}</button></div>
    </div>
    <slot name="save"></slot>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="busy" role="status">正在读取run与有效基本图的已保存时刻表…</p>
    <template v-if="data && state && summary">
      <p class="muted">{{ frozen ? '使用已读取的数据快照。' : '使用最近读取的已保存数据。' }}不包含时刻表未保存草稿。基准日 {{ data.object.date_base }} · 数据修订 {{ data.revision.slice(0,12) }}</p>
      <div class="analysis-controls metric-toolbar">
        <label>指标预设<select v-model="preset" @change="applyPreset"><option value="common">常用延误</option><option value="terminal">终到评价</option><option value="distribution">晚点分布</option><option value="custom" disabled>自定义</option></select></label>
        <label>观测事件<select v-model="state.event"><option value="arrival">到达</option><option value="departure">出发</option></select></label>
        <label>显示单位<select v-model="state.unit"><option value="minutes">分钟</option><option value="seconds">秒</option></select></label>
        <label>晚点阈值（{{ unit }}）<input type="number" min="0" :max="86400/divisor" step="any" :value="threshold" @change="setThreshold(($event.target as HTMLInputElement).value)" /></label>
        <label>统计范围<select v-model="state.scope" @change="resetPages"><option value="all">整个run</option><option value="selected">所选列车和车站</option></select></label>
        <button ref="configButton" type="button" @click="openDrawer">配置指标</button>
      </div>
      <details v-if="state.scope === 'selected'" class="metric-scope">
        <summary>选择统计列车和车站（{{ state.train_ids.length }} 列车 / {{ state.station_ids.length }} 车站）</summary>
        <div class="metric-scope-columns">
          <div><label>搜索车站<input v-model="stationSearch" /></label><div class="editor-actions"><button @click="state.station_ids=data.stations.map(s=>s.id);resetPages()">全选车站</button><button @click="state.station_ids=[];resetPages()">清空车站</button></div><div class="checkbox-options"><label v-for="station in stationOptions.slice(0,80)" :key="station.id"><input v-model="state.station_ids" type="checkbox" :value="station.id" @change="resetPages" />{{ station.node_name_chn }}</label></div><small v-if="stationOptions.length>80">仅列出前80项，可搜索其余项。</small></div>
          <div><label>搜索列车<input v-model="trainSearch" /></label><div class="editor-actions"><button @click="state.train_ids=data.trains.map(t=>t.id);resetPages()">全选列车</button><button @click="state.train_ids=[];resetPages()">清空列车</button></div><div class="checkbox-options"><label v-for="train in trainOptions.slice(0,80)" :key="train.id"><input v-model="state.train_ids" type="checkbox" :value="train.id" @change="resetPages" />{{ train.train_course_id }} · {{ train.train_base_date }}</label></div><small v-if="trainOptions.length>80">仅列出前80项，可搜索其余项。</small></div>
        </div>
      </details>
      <p class="metric-sample-count">统计范围：{{ summary.trainCount }} 列车、{{ summary.rows.length }} 个车站访问行 · 有效{{ state.event==='arrival'?'到达':'出发' }}事件 {{ summary.count }} · 无可计算时刻 {{ summary.excluded }}（含不适用） · 有效终到 {{ summary.terminalCount }} 列车（须真实终到位于统计车站范围）</p>
      <p v-if="!data.endpoints" class="category-context">此旧快照不含完整路径端点信息，终到指标显示“—”；可明确点击重新计算读取当前数据。</p>
      <div class="metric-cards">
        <div v-for="id in state.selected" :key="id" class="metric-card" :data-metric-id="id" :class="{'metric-card-selected':explained===id}">
          <div class="metric-card-heading">
            <button type="button" class="metric-card-title" :aria-pressed="explained===id" :title="id==='max'?maximumLocations.join('、'):undefined" @click="explained=id">{{ info(id).label }}<template v-if="id==='max'">：{{ maximumCaption }}</template></button>
            <label v-if="id==='mean'" class="metric-include-zero" :title="'取消勾选时仅统计'+(state.event==='arrival'?'到达':'出发')+'偏差大于0的事件；正点、提前和缺失不计入分母，不受晚点阈值影响。'"><input v-model="includeZeroMean" type="checkbox" @change="explained='mean'" />包含零晚点事件</label>
          </div>
          <button type="button" class="metric-card-main" :aria-pressed="explained===id" @click="explained=id">
            <strong>{{ format(summary.values[id],info(id).kind) }}<small>{{ info(id).kind==='time'?unit:info(id).kind==='percent'?'%':'列' }}</small></strong>
            <small v-if="id!=='terminal_affected'">{{ id==='mean'?'平均值样本 '+summary.meanSampleCount+' 个事件':id==='late_rate'||id==='terminal_rate'?'偏差 > '+format(state.threshold_seconds)+unit:id.startsWith('terminal')?'每趟列车一次':'查看统计口径' }}</small>
          </button>
          <details v-if="id==='terminal_affected'" class="metric-terminal-dropdown" :open="terminalOpen" @toggle="terminalOpen=($event.target as HTMLDetailsElement).open">
            <summary>查看终到晚点列车</summary>
            <div v-if="terminalOpen" class="metric-terminal-options" aria-label="按终到晚点降序排列的列车">
              <div class="metric-terminal-heading"><strong>终到晚点列车（{{ summary.terminalDelayed.length }}）</strong><span>偏差 &gt; {{ format(state.threshold_seconds) }}{{ unit }} · 晚点从大到小</span><button type="button" @click="terminalOpen=false">收起</button></div>
              <div v-if="summary.terminalDelayed.length" class="metric-terminal-table"><table><thead><tr><th>列车</th><th>列车基准日</th><th>终到站</th><th>终到晚点（{{ unit }}）</th></tr></thead><tbody><tr v-for="entry in terminalPageRows" :key="entry.train_id"><td><button type="button" @click="pickCell(entry.row_key,entry.train_id)">{{ entry.train_course_id }}</button></td><td>{{ entry.train_base_date }}</td><td>{{ entry.terminal_station }}</td><td>{{ format(entry.seconds) }}</td></tr></tbody></table></div>
              <p v-else>{{ summary.terminalCount?'没有超过当前阈值的终到晚点列车。':'当前范围没有可计算的完整终到样本。' }}</p>
              <div v-if="summary.terminalDelayed.length>20" class="editor-actions"><button type="button" :disabled="terminalOffset===0" @click="terminalPage=Math.max(0,terminalPage-1)">上一页</button><span>{{ terminalOffset+1 }}–{{ terminalOffset+terminalPageRows.length }} / {{ summary.terminalDelayed.length }}</span><button type="button" :disabled="terminalOffset+20>=summary.terminalDelayed.length" @click="terminalPage++">下一页</button></div>
            </div>
          </details>
        </div>
      </div>
      <div class="metric-definition" aria-live="polite">
        <p><strong>{{ info(explained).label }}：</strong>{{ info(explained).definition }}</p>
        <div class="metric-formula"><math xmlns="http://www.w3.org/1998/Math/MathML" display="block" v-html="info(explained).formula"></math></div>
        <p>{{ info(explained).notation }}</p>
        <p v-if="explained==='max' && maximumLocations.length">最大晚点车次及车站：{{ maximumLocations.join('、') }}{{ (summary.maxEvents.length>1)?'（并列）':'' }}</p>
      </div>
      <div class="metric-plots">
        <section class="metric-panel" ref="curveContainer" :data-curve-dimension="state.curve_mode==='3d'?'3':'2'">
          <h3>到发偏差曲线</h3>
          <div class="editor-actions metric-curve-fields" role="radiogroup" aria-label="延误演变曲线显示方式">
            <label><input v-model="state.curve_mode" type="radio" :name="'metric-curve-mode-'+runId" value="2d" />2D延误演变曲线</label>
            <label><input v-model="state.curve_mode" type="radio" :name="'metric-curve-mode-'+runId" value="3d" />3D延误演变曲线</label>
          </div>
          <div class="metric-curve-selectors">
          <details class="metric-curve-picker" :open="curvePickerOpen" @toggle="curvePickerOpen=($event.target as HTMLDetailsElement).open">
            <summary>{{ curveSelectionLabel }}</summary>
            <div v-if="curvePickerOpen" class="metric-curve-choices">
              <label>查找曲线列车<input v-model="curveSearch" /></label>
              <div class="editor-actions"><button type="button" @click="selectMatchedCurves">全选搜索结果</button><button type="button" @click="clearCurves">清空绘图列车</button></div>
              <label v-for="train in curveOptions" :key="train.id" class="metric-check"><input type="checkbox" :checked="state.curve_train_ids?.includes(train.id)" @change="checkCurveTrain(train.id,($event.target as HTMLInputElement).checked)" />{{ curveOptionLabel(train) }}</label>
              <div v-if="curveMatches.length>80" class="editor-actions"><button :disabled="curveListOffset===0" @click="curveListPage=Math.max(0,curveListPage-1)">上一页列车</button><span>{{ curveListOffset+1 }}–{{ curveListOffset+curveOptions.length }} / {{ curveMatches.length }}</span><button :disabled="curveListOffset+80>=curveMatches.length" @click="curveListPage++">下一页列车</button></div>
              <p v-if="!curveOptions.length">没有匹配列车。</p>
            </div>
          </details>
          <details class="metric-curve-picker" :open="curveStationOpen" @toggle="curveStationOpen=($event.target as HTMLDetailsElement).open">
            <summary>{{ curveStationLabel }}</summary>
            <div v-if="curveStationOpen" class="metric-curve-choices">
              <label>查找绘图车站<input v-model="curveStationSearch" /></label>
              <div class="editor-actions"><button type="button" @click="state.curve_station_ids=curveStationPool.map(s=>s.id)">全选车站</button><button type="button" @click="state.curve_station_ids=[]">清空车站</button></div>
              <label v-for="station in curveStationOptions" :key="station.id" class="metric-check"><input type="checkbox" :checked="state.curve_station_ids?.includes(station.id)" @change="checkCurveStation(station.id,($event.target as HTMLInputElement).checked)" />{{ station.node_name_chn || station.node_name }}</label>
              <div v-if="curveStationMatches.length>80" class="editor-actions"><button type="button" :disabled="curveStationOffset===0" @click="curveStationPage=Math.max(0,curveStationPage-1)">上一页车站</button><span>{{ curveStationOffset+1 }}–{{ curveStationOffset+curveStationOptions.length }} / {{ curveStationMatches.length }}</span><button type="button" :disabled="curveStationOffset+80>=curveStationMatches.length" @click="curveStationPage++">下一页车站</button></div>
              <p v-if="!curveStationOptions.length">没有匹配车站。</p>
            </div>
          </details>
          </div>
          <div class="editor-actions metric-curve-fields"><span>作图控制：</span><label><input v-model="state.curve_fields" type="checkbox" value="arrival" />到达延误</label><label><input v-model="state.curve_fields" type="checkbox" value="departure" />出发延误</label></div>
          <p class="muted">按绘图车站选择显示列车到发偏差；2D模式用不同颜色叠加所选列车，3D模式可旋转查看。2D单车按SEQ，多车及3D按共用车站轴展示，同站重复经停分别保留，缺失时刻断线。绘图车站独立于统计车站范围。列车按完整路径中仅晚点事件的平均到达晚点降序排列，均值固定以分钟显示。</p>
          <p v-if="!curveTrains.length" class="empty-state">请选择一趟或多趟绘图列车。</p>
          <p v-else-if="!selectedCurveStations.length" class="empty-state">请选择一个或多个绘图车站。</p>
          <p v-else-if="!state.curve_fields?.length" class="empty-state">请选择到达延误或出发延误。</p>
          <template v-else-if="state.curve_mode==='3d'">
            <DelayPlot3D v-if="scene3D?.pointCount && state.curve_camera" :scene="scene3D" :camera="state.curve_camera" :unit="state.unit" :active-train-id="state.active_train_id" @update:camera="state.curve_camera=$event" @pick="pickCell" />
            <p v-else class="empty-state">所选列车没有可计算的到发偏差。</p>
          </template>
          <svg v-else-if="!curve.empty" class="metric-curve" :viewBox="'0 0 '+curve.width+' 290'" role="img" aria-label="所选列车的2D延误演变曲线，颜色区分列车、实线为到达、虚线为出发">
            <text x="2" y="14">{{ unit }}</text>
            <g v-for="(tick,i) in curve.ticks" :key="i"><line :x1="curve.left" :x2="curve.right" :y1="tick.y" :y2="tick.y" class="metric-grid" /><text :x="curve.left-8" :y="tick.y+4" text-anchor="end">{{ tick.text }}</text></g>
            <line :x1="curve.left" :x2="curve.right" :y1="curve.zero" :y2="curve.zero" class="metric-grid" />
            <g v-for="plot in curve.plots" :key="plot.trainId+':'+plot.field" :class="['metric-evolution-trace','metric-'+plot.field,{'is-active':plot.trainId===state.active_train_id}]" :style="trainColorStyle(plot.trainId)" :data-train-id="plot.trainId" :data-event="plot.field"><path :d="plot.path" fill="none"><title>{{ plot.name }} · {{ plot.field==='arrival'?'到达':'出发' }}</title></path><circle v-for="(point,i) in plot.points" :key="i" :cx="point.x" :cy="point.y" r="3" @click="pickCell(point.rowKey,plot.trainId)"><title>{{ point.label }}</title></circle></g>
            <text v-for="(label,i) in curve.labels" :key="label.key" :x="label.x" y="252" :text-anchor="i===0?'start':i===curve.labels.length-1?'end':'middle'">{{ label.label }}</text>
            <text :x="curve.right" y="282" text-anchor="end">车站（运行顺序）</text>
          </svg>
          <p v-else class="empty-state">所选列车没有可计算的到发偏差。</p>
          <p class="metric-legend"><span v-if="state.curve_fields?.includes('arrival')" class="metric-event-key"><i class="metric-event-line" aria-hidden="true"></i>到达 · 实线</span><span v-if="state.curve_fields?.includes('departure')" class="metric-event-key"><i class="metric-event-line is-departure" aria-hidden="true"></i>出发 · 虚线</span></p>
          <div v-if="curveTrains.length" class="metric-curve-train-legend" aria-label="列车颜色图例">
            <button v-for="train in curveLegendTrains" :key="train.id" type="button" :style="trainColorStyle(train.id)" :aria-pressed="state.active_train_id===train.id" @click="pickCurveTrain(train.id)"><span class="metric-train-color" aria-hidden="true"></span>{{ train.train_course_id }} · {{ train.train_base_date.replaceAll('-','/') }}</button>
          </div>
          <div v-if="curveTrains.length>80" class="editor-actions"><button type="button" :disabled="curveLegendOffset===0" @click="curveLegendPage=Math.max(0,curveLegendPage-1)">上一页图例</button><span>{{ curveLegendOffset+1 }}–{{ curveLegendOffset+curveLegendTrains.length }} / {{ curveTrains.length }}</span><button type="button" :disabled="curveLegendOffset+80>=curveTrains.length" @click="curveLegendPage++">下一页图例</button></div>
        </section>
        <section class="metric-panel">
          <h3>{{ state.event==='arrival'?'到达':'出发' }}偏差热力表（{{ unit }}）</h3>
          <div class="editor-actions"><button :disabled="rowOffset===0" @click="state.row_offset=Math.max(0,rowOffset-25)">上一页车站</button><span>{{ summary.rows.length?rowOffset+1:0 }}–{{ rowOffset+pageRows.length }} / {{ summary.rows.length }} 行</span><button :disabled="rowOffset+25>=summary.rows.length" @click="state.row_offset=rowOffset+25">下一页车站</button></div>
          <div class="editor-actions"><button :disabled="trainOffset===0" @click="state.train_offset=Math.max(0,trainOffset-20)">前一组列车</button><span>{{ summary.trains.length?trainOffset+1:0 }}–{{ trainOffset+pageTrains.length }} / {{ summary.trains.length }} 列车</span><button :disabled="trainOffset+20>=summary.trains.length" @click="state.train_offset=trainOffset+20">后一组列车</button></div>
          <div class="table-wrap metric-heatmap"><table><thead><tr><th>车站</th><th v-for="train in pageTrains" :key="train.id"><button type="button" @click="pickCurveTrain(train.id)">{{ train.train_course_id }}<small>{{ train.train_base_date }}</small></button></th></tr></thead><tbody><tr v-for="row in pageRows" :key="row.key"><th>{{ row.node_name_chn }}{{ row.occurrence>1?' #'+row.occurrence:'' }}</th><td v-for="train in pageTrains" :key="train.id"><button type="button" :class="{ 'metric-missing':!finite(cell(row.key,train.id)?.[state.event]) }" :style="heatStyle(cell(row.key,train.id)?.[state.event])" :title="cell(row.key,train.id)?.[state.event==='arrival'?'arrival_reason':'departure_reason'] || train.train_course_id+' · '+row.node_name_chn+' · '+signed(cell(row.key,train.id)?.[state.event])+unit" :aria-label="train.train_course_id+' '+row.node_name_chn+' '+signed(cell(row.key,train.id)?.[state.event])+unit" @click="pickCell(row.key,train.id)">{{ signed(cell(row.key,train.id)?.[state.event]) }}</button></td></tr></tbody></table></div>
          <p v-if="!summary.rows.length || !summary.trains.length" class="empty-state">当前范围没有事件，请调整统计选择。</p>
          <p class="metric-legend"><span class="metric-early-label">负值：提前</span><span class="metric-late-label">正值：晚点</span><span>—：无可计算时刻</span></p>
          <p v-if="selectedDetail" aria-live="polite">{{ selectedDetail }}</p>
          <small>翻页和高亮不改变统计范围；累计指标包含范围内全部事件。</small>
        </section>
        <section class="metric-panel metric-time-panel">
          <h3>到发晚点时空热力图（{{ unit }}）</h3>
          <DelayTimeHeatmap :data="data" :state="state" @update:display="state.time_heatmap=$event" />
        </section>
      </div>
      <details v-if="data.issues.length"><summary>匹配提示（{{ data.issues.length }}）</summary><ul><li v-for="(issue,i) in data.issues" :key="i">{{ issue }}</li></ul></details>
    </template>
    <aside v-if="drawerOpen && state" class="metric-drawer" role="dialog" aria-labelledby="metric-config-title" @keydown.esc.stop.prevent="closeDrawer">
      <div class="analysis-heading"><h3 id="metric-config-title" ref="drawerHeading" tabindex="-1">配置总览指标</h3><button type="button" @click="closeDrawer">关闭</button></div>
      <p>选择2至6项，当前已选 {{ draft.length }} 项。</p>
      <template v-for="group in [{title:'晚点规模与分布',ids:metricIds.slice(0,4)},{title:'影响范围',ids:metricIds.slice(4,6)},{title:'终到表现（到达事件）',ids:metricIds.slice(6)}]" :key="group.title">
        <h4>{{ group.title }}</h4><label v-for="id in group.ids" :key="id" class="metric-check"><input v-model="draft" type="checkbox" :value="id" /><span>{{ info(id).label }}<small>{{ info(id).definition }}</small><span class="metric-formula metric-formula-compact"><math xmlns="http://www.w3.org/1998/Math/MathML" v-html="info(id).formula"></math></span></span></label>
      </template>
      <p v-if="drawerError" class="error" role="alert">{{ drawerError }}</p>
      <div class="editor-actions"><button type="button" @click="closeDrawer">取消</button><button type="button" @click="applyMetrics">应用</button></div>
    </aside>
  </section>
</template>
