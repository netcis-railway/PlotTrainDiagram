<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { PlotData, PlotSeries, PlotPoint, PlotSegment } from '../api/diagram'
import { createTrackLayout, projectOnTracks, trackExtraHeight, visibleTrackStations, wheelViewport, type TrackLayout } from '../trackLayout'
import { clipSegment, panViewport, project, spacedLabels, tickStep, timeLabel, localTime, zoomViewport, type Bounds, type Viewport } from '../diagramGeometry'
const props = defineProps<{ data: PlotData; series: PlotSeries[]; stationIds: string[]; selected: string[]; reverse: boolean; viewport: Viewport }>()
const emit = defineEmits<{ 'update:viewport': [value: Viewport]; select: [key: string, add: boolean]; reset: []; toggleTrack: [id: string] }>()
const shell = ref<HTMLDivElement | null>(null), canvas = ref<HTMLCanvasElement | null>(null)
interface Hit { series: PlotSeries; point: PlotPoint; segment?: PlotSegment }
const hover = ref<Hit | null>(null)
const hoverEvent = computed(() => hover.value?.series.events.find(event => event.id === hover.value?.point.event_id))
const hoverEnd = computed(() => { const hit = hover.value; return hit?.segment ? hit.series.events.find(event => event.id === hit.series.points[hit.segment!.to].event_id) : null })
const hoverPosition = ref({ x: 0, y: 0 })
const usagePointLabels = { track_entry: '进入股道', track_exit: '离开股道', pass_track: '通过股道标记', track_unassigned: '股道未判定' }
const trackStations = computed(() => visibleTrackStations(props.data, props.stationIds, props.viewport))
const extraHeight = computed(() => trackExtraHeight(trackStations.value, props.data.styles.track_gap * 5))
let layout: TrackLayout | null = null
let stationHits: { id: string; y: number }[] = []
let observer: ResizeObserver | undefined, theme: MutationObserver | undefined, frame = 0, hoverFrame = 0
let box: Bounds = { left: 90, top: 28, width: 600, height: 400 }
let screenPoints: { x: number; y: number; hit: Hit }[] = []
let screenSegments: { ax: number; ay: number; bx: number; by: number; hit: Hit }[] = []
let drag: { x: number; y: number; originX: number; originY: number; moved: boolean } | null = null
function queue() { if (!frame) frame = requestAnimationFrame(() => { frame = 0; draw() }) }
function color(series: PlotSeries) {
  const override = props.data.styles.train_styles[series.key]
  if (override?.color) return override.color
  if (series.object_type === 'base') return document.documentElement.dataset.theme === 'dark' ? props.data.styles.base_dark : props.data.styles.base
  return props.data.styles[series.direction]
}
function draw() {
  if (!canvas.value || !shell.value) return
  const width = Math.max(320, shell.value.clientWidth), height = Math.max(300, shell.value.clientHeight), ratio = window.devicePixelRatio || 1
  const drawing = canvas.value.getContext('2d')
  if (!drawing) return
  const ctx: CanvasRenderingContext2D = drawing
  canvas.value.width = Math.round(width * ratio); canvas.value.height = Math.round(height * ratio)
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
  const css = getComputedStyle(document.documentElement), styles = props.data.styles
  ctx.fillStyle = css.getPropertyValue('--surface').trim() || '#fff'; ctx.fillRect(0, 0, width, height)
  ctx.font = `${styles.font_size}px "Microsoft YaHei", sans-serif`
  const stations = props.data.axis.stations.filter(station => props.stationIds.includes(station.node_id))
  const labelWidth = Math.max(60, ...stations.map(station => ctx.measureText(station.node_name_chn).width))
  const left = Math.min(300, Math.max(labelWidth + 48, trackStations.value.length ? labelWidth + 142 : 0))
  box = { left, top: 28, width: Math.max(100, width - left - 24), height: height - 92 }
  const view = props.viewport
  layout = createTrackLayout(view, box, props.reverse, trackStations.value, styles.track_gap * 5)
  const activeLayout = layout
  screenPoints = []; screenSegments = []; stationHits = []
  ctx.strokeStyle = styles.grid; ctx.lineWidth = .6; ctx.globalAlpha = .5
  const step = tickStep(view, styles.grid_minutes, box.width)
  ctx.textAlign = 'center'; ctx.textBaseline = 'top'
  for (let second = Math.ceil(view.x0 / step) * step; second <= view.x1; second += step) {
    const pixel = project({ seconds: second, y: view.y0 }, view, box, props.reverse)
    if (second % 3600 !== 0) { ctx.beginPath(); ctx.moveTo(pixel.x, box.top); ctx.lineTo(pixel.x, box.top + box.height); ctx.stroke() }
    ctx.globalAlpha = 1; ctx.fillStyle = css.getPropertyValue('--text').trim(); ctx.fillText(timeLabel(second), pixel.x, box.top + box.height + 10); ctx.globalAlpha = .5
  }
  // Hour lines are independent of the adaptive minor ticks (e.g. a 40-minute step).
  // At extreme zoom-out retain whole-hour multiples without painting subpixel grids.
  const hourStep = Math.max(1, Math.ceil((view.x1 - view.x0) / 3600 / Math.max(1, box.width))) * 3600
  ctx.strokeStyle = '#2e9f55'; ctx.lineWidth = 2; ctx.globalAlpha = 1; ctx.setLineDash([])
  for (let second = Math.ceil(view.x0 / hourStep) * hourStep; second <= view.x1; second += hourStep) {
    const pixel = project({ seconds: second, y: view.y0 }, view, box, props.reverse)
    ctx.beginPath(); ctx.moveTo(pixel.x, box.top); ctx.lineTo(pixel.x, box.top + box.height); ctx.stroke()
  }
  ctx.strokeStyle = styles.grid; ctx.lineWidth = .6; ctx.globalAlpha = .5
  const axisLabels = stations.filter(station => station.y >= view.y0 && station.y <= view.y1).map(station => ({
    station, pixel: projectOnTracks({ seconds: view.x0, y: station.y }, activeLayout),
  }))
  const labelYs = spacedLabels(axisLabels.map(item => item.pixel.y), box.top + styles.font_size / 2,
    box.top + box.height - styles.font_size / 2, styles.font_size + 2)
  axisLabels.forEach(({ station, pixel }, index) => {
    const band = activeLayout.bands.find(item => item.station.node_id === station.node_id)
    if (!band) {
      ctx.beginPath(); ctx.moveTo(box.left, pixel.y); ctx.lineTo(box.left + box.width, pixel.y); ctx.stroke()
    } else {
      const gap = activeLayout.gap, half = (band.resource.track_count + 1) / 2
      const smallFont = Math.max(6, Math.min(styles.font_size, gap * 2 - 1)), cols = Math.max(1, Math.ceil((smallFont + 1) / gap))
      const columnWidth = Math.max(20, ...band.resource.tracks.map(t => ctx.measureText(`${t.number}*`).width + 6))
      const levels = [{ offset: -half, label: '下到/上发', main: false },
        ...band.resource.tracks.map((track, j) => ({ offset: (band.resource.track_count - 1) / 2 - j,
          label: `${track.number}${track.roles.some(role => role.endsWith('_main')) ? '*' : ''}`, main: track.roles.some(role => role.endsWith('_main')) })),
        { offset: half, label: '下发/上到', main: false }]
      levels.forEach((level, j) => {
        const y = band.center + level.offset * gap
        ctx.lineWidth = level.main ? 1.3 : .6; ctx.setLineDash(level.main ? [5, 3] : [])
        ctx.beginPath(); ctx.moveTo(box.left, y); ctx.lineTo(box.left + box.width, y); ctx.stroke(); ctx.setLineDash([])
        ctx.globalAlpha = 1; ctx.fillStyle = css.getPropertyValue('--text').trim(); ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
        ctx.font = `${level.main ? 'bold ' : ''}${j === 0 || j === levels.length - 1 ? 9 : smallFont}px "Microsoft YaHei", sans-serif`
        const column = j > 0 && j < levels.length - 1 ? (j - 1) % cols : cols
        ctx.fillText(level.label, box.left - 8 - column * columnWidth, y); ctx.globalAlpha = .5
      })
      ctx.lineWidth = .6
    }
    if (Math.abs(labelYs[index] - pixel.y) > 1) {
      ctx.beginPath(); ctx.moveTo(box.left - 3, pixel.y); ctx.lineTo(box.left - 17, labelYs[index]); ctx.lineTo(box.left - 22, labelYs[index]); ctx.stroke()
    }
    ctx.globalAlpha = 1; ctx.fillStyle = css.getPropertyValue('--text').trim(); ctx.textBaseline = 'middle'
    ctx.font = `${styles.font_size}px "Microsoft YaHei", sans-serif`
    ctx.textAlign = trackStations.value.length ? 'left' : 'right'
    ctx.fillText(`${band ? '▾ ' : '▸ '}${station.node_name_chn}`, trackStations.value.length ? 7 : box.left - 25, labelYs[index]); ctx.globalAlpha = .5
    stationHits.push({ id: station.node_id, y: labelYs[index] })
  })
  ctx.globalAlpha = 1; ctx.strokeStyle = css.getPropertyValue('--border').trim(); ctx.strokeRect(box.left, box.top, box.width, box.height)
  ctx.fillStyle = css.getPropertyValue('--muted').trim(); ctx.textAlign = 'left'; ctx.textBaseline = 'top'
  ctx.fillText(`时间 · 基准日 ${props.data.object.date_base}（跨日以天偏移标示）`, box.left, height - 25)
  ctx.save(); ctx.beginPath(); ctx.rect(box.left, box.top, box.width, box.height); ctx.clip()
  const allowed = new Set(props.stationIds)
  const unassigned: { x: number; y: number; hit: Hit }[] = []
  for (const series of props.series) {
    const events = new Map(series.events.map(event => [event.id, event])), selected = props.selected.includes(series.key)
    const override = styles.train_styles[series.key], stroke = color(series), lineWidth = override?.width || styles.width
    const visible = (point: PlotPoint) => allowed.has(events.get(point.event_id)?.node_id || '')
    const pixels = series.points.map(point => projectOnTracks(point, activeLayout))
    const segments: { a: { x: number; y: number }; b: { x: number; y: number }; segment: PlotSegment }[] = []
    for (const segment of series.segments) {
      const a = series.points[segment.from], b = series.points[segment.to]
      if (!visible(a) || !visible(b)) continue
      const originalA = pixels[segment.from], originalB = pixels[segment.to]
      const clipped = clipSegment({ seconds: originalA.x, y: originalA.y }, { seconds: originalB.x, y: originalB.y },
        { x0: box.left, x1: box.left + box.width, y0: box.top, y1: box.top + box.height })
      if (!clipped) continue
      const pa = { x: clipped[0].seconds, y: clipped[0].y }, pb = { x: clipped[1].seconds, y: clipped[1].y }
      segments.push({ a: pa, b: pb, segment })
      screenSegments.push({ ax: pa.x, ay: pa.y, bx: pb.x, by: pb.y, hit: { series, point: a, segment } })
    }
    function paths(highlight: boolean) {
      for (const anomaly of highlight ? [false] : [false, true]) {
        ctx.strokeStyle = highlight ? styles.highlight : anomaly ? '#e78b2d' : stroke
        ctx.lineWidth = highlight ? lineWidth + 5 : lineWidth
        ctx.globalAlpha = highlight ? .45 : series.object_type === 'base' && props.data.object.object_type === 'run' ? .65 : 1
        ctx.setLineDash(highlight ? [] : anomaly ? [2, 3] : override?.dashed || (series.object_type === 'base' && props.data.object.object_type === 'run') ? [6, 4] : [])
        ctx.beginPath()
        for (const item of segments) if (highlight || item.segment.anomaly === anomaly) { ctx.moveTo(item.a.x, item.a.y); ctx.lineTo(item.b.x, item.b.y) }
        ctx.stroke()
      }
    }
    if (selected) paths(true)
    paths(false); ctx.setLineDash([]); ctx.globalAlpha = 1; ctx.fillStyle = stroke
    let label: { x: number; y: number } | null = null
    ctx.beginPath()
    series.points.forEach((point, index) => {
      const pixel = pixels[index]
      if (!visible(point) || pixel.x < box.left || pixel.x > box.left + box.width || pixel.y < box.top || pixel.y > box.top + box.height) return
      if (point.usage_kind === 'track_unassigned') unassigned.push({ ...pixel, hit: { series, point } })
      else {
        ctx.moveTo(pixel.x + styles.point_radius, pixel.y); ctx.arc(pixel.x, pixel.y, styles.point_radius, 0, Math.PI * 2)
        screenPoints.push({ x: pixel.x, y: pixel.y, hit: { series, point } })
      }
      if (!label) label = pixel
    })
    ctx.fill()
    if (label) {
      const pixel = label as { x: number; y: number }
      ctx.font = `${selected ? 'bold ' : ''}${styles.font_size}px "Microsoft YaHei", sans-serif`
      ctx.textAlign = 'left'; ctx.textBaseline = series.object_type === 'base' ? 'bottom' : 'top'
      ctx.fillText(series.train_course_id, pixel.x + 5, pixel.y + (series.object_type === 'base' ? -5 : 5))
    }
  }
  // Draw unresolved-track markers last so overlay lines cannot hide their warning shape.
  const radius = Math.max(5, styles.point_radius * 2)
  ctx.fillStyle = '#e53935'; ctx.strokeStyle = css.getPropertyValue('--surface').trim() || '#fff'; ctx.lineWidth = 1
  for (const marker of unassigned) {
    ctx.beginPath(); ctx.moveTo(marker.x, marker.y - radius)
    ctx.lineTo(marker.x + radius, marker.y + radius); ctx.lineTo(marker.x - radius, marker.y + radius)
    ctx.closePath(); ctx.fill(); ctx.stroke()
  }
  screenPoints = unassigned.concat(screenPoints)
  ctx.restore(); ctx.globalAlpha = 1; ctx.setLineDash([])
}
function hitTest(x: number, y: number): Hit | null {
  let nearest: Hit | null = null, distance = 100
  for (const item of screenPoints) {
    const d = (item.x - x) ** 2 + (item.y - y) ** 2
    if (d < distance) { nearest = item.hit; distance = d }
  }
  if (nearest) return nearest
  for (const item of screenSegments) {
    if (x < Math.min(item.ax, item.bx) - 5 || x > Math.max(item.ax, item.bx) + 5 || y < Math.min(item.ay, item.by) - 5 || y > Math.max(item.ay, item.by) + 5) continue
    const dx = item.bx - item.ax, dy = item.by - item.ay
    const t = Math.max(0, Math.min(1, ((x - item.ax) * dx + (y - item.ay) * dy) / (dx * dx + dy * dy || 1)))
    const d = (x - item.ax - t * dx) ** 2 + (y - item.ay - t * dy) ** 2
    if (d < 36) return item.hit
  }
  return null
}
function position(event: Pick<MouseEvent, 'clientX' | 'clientY'>) { const rect = canvas.value!.getBoundingClientRect(); return { x: event.clientX - rect.left, y: event.clientY - rect.top } }
function pointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  const p = position(event); drag = { ...p, originX: p.x, originY: p.y, moved: false }; canvas.value?.setPointerCapture(event.pointerId); hover.value = null
}
function pointerMove(event: PointerEvent) {
  const p = position(event)
  if (drag && event.buttons) {
    const dx = p.x - drag.x, dy = p.y - drag.y
    drag.moved ||= Math.hypot(p.x - drag.originX, p.y - drag.originY) > 3
    const view = props.viewport
    emit('update:viewport', panViewport(view, -dx / box.width * (view.x1 - view.x0), (props.reverse ? 1 : -1) * dy / (layout?.baseBox.height || box.height) * (view.y1 - view.y0)))
    drag.x = p.x; drag.y = p.y; return
  }
  if (hoverFrame) cancelAnimationFrame(hoverFrame)
  hoverFrame = requestAnimationFrame(() => { hoverFrame = 0; hover.value = hitTest(p.x, p.y); hoverPosition.value = { x: Math.min(p.x + 14, Math.max(10, (shell.value?.clientWidth || 600) - 310)), y: Math.max(0, p.y - 140) } })
}
function pointerUp(event: PointerEvent) {
  if (drag && !drag.moved) { const p = position(event), hit = hitTest(p.x, p.y); if (hit) emit('select', hit.series.key, event.ctrlKey || event.metaKey) }
  drag = null; if (canvas.value?.hasPointerCapture(event.pointerId)) canvas.value.releasePointerCapture(event.pointerId)
}
function doubleClick(event: MouseEvent) {
  const p = position(event)
  if (p.x > box.left) return
  const nearest = stationHits.slice().sort((a, b) => Math.abs(a.y - p.y) - Math.abs(b.y - p.y))[0]
  if (nearest && Math.abs(nearest.y - p.y) <= Math.max(9, props.data.styles.font_size)) emit('toggleTrack', nearest.id)
}
function wheel(event: WheelEvent) {
  if (!layout || event.deltaY === 0) return
  emit('update:viewport', wheelViewport({ ...layout, view: props.viewport }, position(event), event)); hover.value = null
}
function keyboard(event: KeyboardEvent) {
  const view = props.viewport, dx = (view.x1 - view.x0) * .1, dy = (view.y1 - view.y0) * .1
  if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','Home'].includes(event.key)) event.preventDefault(); else return
  if (event.key === 'Home') emit('reset')
  else if (['+','=','-'].includes(event.key)) emit('update:viewport', zoomViewport(view, event.key === '-' ? 1.25 : .8))
  else emit('update:viewport', panViewport(view, event.key === 'ArrowLeft' ? -dx : event.key === 'ArrowRight' ? dx : 0, event.key === 'ArrowUp' ? -dy : event.key === 'ArrowDown' ? dy : 0))
  hover.value = null
}
watch(() => [props.data, props.series, props.stationIds, props.selected, props.reverse, props.viewport], () => { hover.value = null; queue() }, { deep: false })
onMounted(() => { observer = new ResizeObserver(queue); if (shell.value) observer.observe(shell.value); theme = new MutationObserver(queue); theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] }); queue() })
onUnmounted(() => { observer?.disconnect(); theme?.disconnect(); cancelAnimationFrame(frame); cancelAnimationFrame(hoverFrame) })
</script>
<template><div ref="shell" class="diagram-canvas-shell" :style="{ height: `calc(clamp(340px, 58vh, 760px) + ${extraHeight}px)` }">
  <canvas ref="canvas" tabindex="0" role="img" aria-label="列车运行图，横轴为时间，纵轴为车站" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="drag = null" @pointerleave="hover = null" @wheel.prevent="wheel" @keydown="keyboard" @dblclick="doubleClick">运行图可通过下方所选列车时刻明细查阅。</canvas>
  <div v-if="hover && hoverEvent" class="diagram-tooltip" :style="{ left: `${hoverPosition.x}px`, top: `${hoverPosition.y}px` }">
    <div v-if="hover.segment && ['travel','dwell'].includes(hover.segment.kind)">运行线段起点 → {{ hoverEnd?.node_name_chn }}（下列时刻属于起点）</div>
    <strong>{{ hover.series.train_course_id }} · {{ hover.series.object_type === 'base' ? '基本图' : hover.series.object_name }}</strong>
    <div>{{ hoverEvent.node_name_chn }} · SEQ {{ hoverEvent.visit_seq }} · 股道 {{ hoverEvent.track_code ?? '未记录' }}</div>
    <div>到达：{{ hoverEvent.arrival ? localTime(data.object.date_base || '', hoverEvent.arrival.seconds).replace('T',' ') : '空' }}</div>
    <div>出发：{{ hoverEvent.departure ? localTime(data.object.date_base || '', hoverEvent.departure.seconds).replace('T',' ') : '空' }}</div>
    <div v-if="hover.point.calculated">{{ hover.point.usage_kind ? usagePointLabels[hover.point.usage_kind] : '计算点' }}： {{ timeLabel(hover.point.seconds, true) }}（用于绘图）</div>
    <div v-if="hoverEvent.track_usage?.passing && hoverEvent.track_usage.adopted_track == null">▲ 红色三角形：股道未判定</div>
    <div v-if="hoverEvent.track_usage?.adopted_track != null">绘图股道 {{ hoverEvent.track_usage.adopted_track }}{{ hoverEvent.track_usage.defaulted ? '（空值采用1，仅显示）' : '' }}</div>
    <div>列车基准日 {{ hover.series.train_base_date }}</div><div>{{ hoverEvent.source.sheet }} · 源行 {{ hoverEvent.source.row }}</div>
  </div>
</div></template>
