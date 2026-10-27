<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId } from 'vue'
import { analysisApi, type DelayDisplay, type DelaySnapshot, type SavedDelay } from '../api/analysis'
const clipId = useId()
const props = defineProps<{ runId: string; initial?: SavedDelay }>()
const data = ref<DelaySnapshot | null>(props.initial ? JSON.parse(JSON.stringify(props.initial.snapshot)) : null)
const state = ref<DelayDisplay>(props.initial ? JSON.parse(JSON.stringify(props.initial.state)) : { station_ids: [], train_ids: [], highlighted_ids: [], unit: 'minutes', chart_height: 340, scroll_top: 0, scroll_left: 0, viewport: { x0: -.5, x1: 1, y0: -60, y1: 60 } })
const busy = ref(false), error = ref(''), table = ref<HTMLElement | null>(null), stationSearch = ref(props.initial?.state.station_search || ''), trainSearch = ref(props.initial?.state.train_search || '')
const openPanels = ref<string[]>([...(props.initial?.state.open_panels || [])])
function panel(id: string, event: Event) { openPanels.value = (event.target as HTMLDetailsElement).open ? [...new Set([...openPanels.value, id])] : openPanels.value.filter(key => key !== id) }
let closed = false
const colors = ['#2879c6', '#b348a4', '#c36d16', '#128879', '#ba4753', '#6c64c7']
const rows = computed(() => data.value?.rows.filter(row => state.value.station_ids.includes(row.station_id)) || [])
const trains = computed(() => data.value?.trains.filter(train => state.value.train_ids.includes(train.id)) || [])
const stationOptions = computed(() => data.value?.stations.filter(s => (s.node_name_chn + s.node_name).includes(stationSearch.value)) || [])
const trainOptions = computed(() => data.value?.trains.filter(t => (t.train_course_id + t.train_base_date).includes(trainSearch.value)) || [])
const byCell = computed(() => new Map(data.value?.cells.map(cell => [cell.row_key + '|' + cell.train_id, cell]) || []))
const divisor = computed(() => state.value.unit === 'minutes' ? 60 : 1)
function format(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  const number = value / divisor.value
  return (number > 0 ? '+' : '') + (Math.round(number * 100) / 100).toString()
}
function cell(row: string, train: string) { return byCell.value.get(row + '|' + train) }
function highlight(id: string) { state.value.highlighted_ids = state.value.highlighted_ids.includes(id) ? state.value.highlighted_ids.filter(key => key !== id) : [...state.value.highlighted_ids, id] }
function reset() {
  const values = rows.value.flatMap(row => trains.value.flatMap(train => {
    const current = cell(row.key, train.id); return [current?.arrival, current?.departure].filter((n): n is number => typeof n === 'number')
  }))
  const low = values.reduce((a, b) => Math.min(a, b), 0), high = values.reduce((a, b) => Math.max(a, b), 0), margin = Math.max(30, (high - low) * .1)
  state.value.viewport = { x0: -.5, x1: Math.max(.5, rows.value.length - .5), y0: low - margin, y1: high + margin }
}
function range(field: keyof DelayDisplay['viewport'], value: string) {
  const next = { ...state.value.viewport, [field]: Number(value) }
  if (!value.trim() || !Object.values(next).every(Number.isFinite) || next.x1 <= next.x0 || next.y1 <= next.y0) { error.value = '坐标范围无效：上限须大于下限。'; return }
  error.value = ''; state.value.viewport = next
}
const chart = computed(() => {
  const view = state.value.viewport, height = state.value.chart_height
  const left = 68, right = 970, top = 18, bottom = height - 64
  const x = (i: number) => left + (i - view.x0) / (view.x1 - view.x0) * (right - left)
  const y = (seconds: number) => bottom - (seconds - view.y0) / (view.y1 - view.y0) * (bottom - top)
  const plots = trains.value.flatMap((train, trainIndex) => ['arrival', 'departure'].map(field => {
    let path = '', previous = false
    const points: { x: number; y: number; label: string }[] = []
    rows.value.forEach((row, i) => {
      const current = cell(row.key, train.id), seconds = current?.[field as 'arrival' | 'departure']
      if (seconds === null || seconds === undefined) { previous = false; return }
      const px = x(i), py = y(seconds)
      path += `${previous ? ' L' : ' M'}${px} ${py}`; previous = true
      if (i >= view.x0 && i <= view.x1 && seconds >= view.y0 && seconds <= view.y1) points.push({ x: px, y: py, label: `${train.train_course_id} · ${row.node_name_chn} · ${field === 'arrival' ? '到达' : '出发'} ${format(seconds)}${state.value.unit === 'minutes' ? '分' : '秒'}` })
    })
    return { key: train.id + field, id: train.id, field, path, points, color: colors[trainIndex % colors.length], highlighted: state.value.highlighted_ids.includes(train.id) }
  }))
  return {
    left, right, top, bottom, plots,
    ticks: Array.from({ length: 5 }, (_, i) => { const value = view.y0 + (view.y1 - view.y0) * i / 4; return { y: y(value), label: format(value) } }),
    stations: rows.value.map((row, i) => ({ key: row.key, x: x(i), label: row.node_name_chn + (row.occurrence > 1 ? `#${row.occurrence}` : '') })).filter((s, i) => s.x >= left && s.x <= right && i % Math.max(1, Math.ceil((view.x1 - view.x0) / 12)) === 0),
  }
})
function wheel(event: WheelEvent) {
  const bounds = (event.currentTarget as SVGElement).getBoundingClientRect(), view = state.value.viewport
  const fx = Math.max(0, Math.min(1, ((event.clientX - bounds.left) / bounds.width * 1000 - chart.value.left) / (chart.value.right - chart.value.left)))
  const fy = Math.max(0, Math.min(1, ((event.clientY - bounds.top) / bounds.height * state.value.chart_height - chart.value.top) / (chart.value.bottom - chart.value.top)))
  const factor = Math.exp(Math.max(-1, Math.min(1, event.deltaY / 600)))
  const cx = view.x0 + fx * (view.x1 - view.x0), cy = view.y1 - fy * (view.y1 - view.y0)
  const next = { ...view }
  if (!event.shiftKey && (view.x1 - view.x0) * factor >= .1 && (view.x1 - view.x0) * factor <= 100000) { next.x0 = cx + (view.x0 - cx) * factor; next.x1 = cx + (view.x1 - cx) * factor }
  if (!event.ctrlKey && (view.y1 - view.y0) * factor >= 1 && (view.y1 - view.y0) * factor <= 1e9) { next.y0 = cy + (view.y0 - cy) * factor; next.y1 = cy + (view.y1 - cy) * factor }
  state.value.viewport = next
}
async function load() {
  busy.value = true; error.value = ''
  try {
    const result = await analysisApi.delays(props.runId)
    if (closed) return
    data.value = result; state.value.station_ids = result.stations.map(s => s.id); state.value.train_ids = result.trains.map(t => t.id); state.value.highlighted_ids = []; reset()
  } catch (e) { if (!closed) error.value = String(e) }
  finally { if (!closed) busy.value = false }
}
function capture(): SavedDelay | null {
  if (!data.value || busy.value) return null
  return JSON.parse(JSON.stringify({ state: { ...state.value, station_search: stationSearch.value, train_search: trainSearch.value, open_panels: openPanels.value, scroll_top: table.value?.scrollTop ?? state.value.scroll_top, scroll_left: table.value?.scrollLeft ?? state.value.scroll_left }, snapshot: data.value }))
}
defineExpose({ capture, isBusy: () => busy.value })
onMounted(async () => {
  if (!props.initial) await load()
  await nextTick()
  if (table.value) { table.value.scrollTop = state.value.scroll_top; table.value.scrollLeft = state.value.scroll_left }
})
onUnmounted(() => { closed = true })
</script>
<template>
  <p class="muted">延误 = run到发时刻 − 绑定基本图到发时刻；正值表示晚点，负值表示早到/早发，0表示正点。无对应列车、经停或时刻显示“—”，悬停查看原因。此处分析已保存的时刻表。</p>
  <p v-if="initial" class="category-context">按保存时的延误数据快照回看。</p>
  <button v-if="!initial" :disabled="busy" @click="load">重新计算延误</button>
  <p v-if="busy" role="status">正在计算延误…</p><p v-if="error" class="error" role="alert">{{ error }}</p>
  <template v-if="data">
    <p>比较基本图：{{ data.base.name }} · {{ data.method }}</p>
    <div class="diagram-filters"><details :open="openPanels.includes('stations')" @toggle="panel('stations', $event)"><summary>延误车站（{{ state.station_ids.length }}）</summary><input v-model="stationSearch" placeholder="搜索车站" /><button @click="state.station_ids = data.stations.map(s => s.id)">全选</button> <button @click="state.station_ids = []">清空</button><div class="checkbox-options"><label v-for="station in stationOptions" :key="station.id"><input v-model="state.station_ids" type="checkbox" :value="station.id" />{{ station.node_name_chn }}</label></div></details>
      <details :open="openPanels.includes('trains')" @toggle="panel('trains', $event)"><summary>延误列车（{{ state.train_ids.length }}）</summary><input v-model="trainSearch" placeholder="搜索列车" /><button @click="state.train_ids = data.trains.map(t => t.id)">全选</button> <button @click="state.train_ids = []">清空</button><div class="checkbox-options"><label v-for="train in trainOptions" :key="train.id"><input v-model="state.train_ids" type="checkbox" :value="train.id" />{{ train.train_course_id }} · {{ train.train_base_date }}</label></div></details></div>
    <div class="analysis-controls"><label>延误单位<select v-model="state.unit"><option value="minutes">分钟</option><option value="seconds">秒</option></select></label><button @click="reset">恢复自动范围</button><label>绘图高度<input v-model.number="state.chart_height" type="range" min="200" max="1000" step="20" /></label></div>
    <div ref="table" class="table-wrap editor-table delay-table" tabindex="0" aria-label="列车到达与出发延误表"><table><thead><tr><th class="station-corner" rowspan="3">NODE_NAME_CHN</th><th v-for="(train, trainIndex) in trains" :key="train.id" colspan="2" :class="{ 'delay-selected': state.highlighted_ids.includes(train.id) }"><button :style="{ color: colors[trainIndex % colors.length] }" @click="highlight(train.id)">{{ train.train_course_id }}</button></th></tr><tr><th v-for="train in trains" :key="train.id" colspan="2">{{ train.train_base_date }}</th></tr><tr><template v-for="train in trains" :key="train.id"><th>到达延误</th><th>出发延误</th></template></tr></thead><tbody><tr v-for="row in rows" :key="row.key"><th>{{ row.node_name_chn }}{{ row.occurrence > 1 ? ' #' + row.occurrence : '' }}</th><template v-for="train in trains" :key="train.id"><td v-for="field in (['arrival', 'departure'] as const)" :key="field" :title="cell(row.key, train.id)?.[field + '_reason' as 'arrival_reason' | 'departure_reason'] || (!cell(row.key, train.id) ? 'run未经过本站' : '')" :class="{ 'delay-positive': (cell(row.key, train.id)?.[field] || 0) > 0, 'delay-negative': (cell(row.key, train.id)?.[field] || 0) < 0, 'delay-selected': state.highlighted_ids.includes(train.id) }">{{ format(cell(row.key, train.id)?.[field]) }}</td></template></tr></tbody></table></div>
    <p v-if="!rows.length || !trains.length" class="empty-state">请选择车站和列车。</p>
    <div class="analysis-controls delay-ranges"><label v-for="field in (['x0','x1','y0','y1'] as const)" :key="field">{{ ({ x0: '站序下限', x1: '站序上限', y0: '延误下限（秒）', y1: '延误上限（秒）' })[field] }}<input type="number" step="any" :value="state.viewport[field]" @change="range(field, ($event.target as HTMLInputElement).value)" /></label></div>
    <p class="muted">实线：到达延误；虚线：出发延误。点击列车标题或曲线高亮。滚轮以鼠标为中心缩放；Ctrl仅站序轴，Shift仅延误轴。</p>
    <svg v-if="rows.length && trains.length" class="delay-chart" preserveAspectRatio="none" :viewBox="'0 0 1000 ' + state.chart_height" :style="{ height: state.chart_height + 'px' }" role="img" aria-label="列车到发延误曲线" @wheel.prevent="wheel">
      <defs><clipPath :id="clipId"><rect :x="chart.left" :y="chart.top" :width="chart.right - chart.left" :height="chart.bottom - chart.top" /></clipPath></defs>
      <g v-for="tick in chart.ticks" :key="tick.y"><line :x1="chart.left" :x2="chart.right" :y1="tick.y" :y2="tick.y" class="delay-grid" /><text :x="chart.left - 8" :y="tick.y + 4" text-anchor="end">{{ tick.label }}</text></g>
      <text x="5" y="12">{{ state.unit === 'minutes' ? '分钟' : '秒' }}</text>
      <g v-for="station in chart.stations" :key="station.key"><line :x1="station.x" :x2="station.x" :y1="chart.top" :y2="chart.bottom" class="delay-grid" /><text :x="station.x" :y="chart.bottom + 22" text-anchor="middle">{{ station.label }}</text></g>
      <g :clip-path="`url(#${clipId})`"><g v-for="plot in chart.plots" :key="plot.key" :opacity="state.highlighted_ids.length && !plot.highlighted ? .25 : 1" @click="highlight(plot.id)"><path :d="plot.path" fill="none" :stroke="plot.color" :stroke-width="plot.highlighted ? 3.5 : 1.5" :stroke-dasharray="plot.field === 'departure' ? '7 4' : undefined" /><circle v-for="(point,index) in plot.points" :key="index" :cx="point.x" :cy="point.y" :r="plot.highlighted ? 4 : 2.5" :fill="plot.color"><title>{{ point.label }}</title></circle></g></g>
    </svg>
    <details v-if="data.issues.length" :open="openPanels.includes('issues')" @toggle="panel('issues', $event)"><summary>匹配提示（{{ data.issues.length }}）</summary><ul><li v-for="issue in data.issues" :key="issue">{{ issue }}</li></ul></details>
  </template>
</template>
