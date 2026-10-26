import type { PlotData, PlotPoint } from './api/diagram'
import { editedSeconds } from './timetableOrdering'
export interface Viewport { x0: number; x1: number; y0: number; y1: number }
export interface Bounds { left: number; top: number; width: number; height: number }
export function fitViewport(data: PlotData, stations = data.axis.stations): Viewport {
  const [low, high] = data.time_extent || [0, 3600]
  const pad = Math.max(120, (high - low) * .035)
  const ys = stations.map(station => station.y), lowY = ys.length ? Math.min(...ys) : 0, highY = ys.length ? Math.max(...ys) : data.axis.total
  const padY = Math.max(1, data.axis.total * .025)
  return { x0: low - pad, x1: high + pad, y0: lowY - padY, y1: highY + padY }
}
export function project(point: Pick<PlotPoint, 'seconds' | 'y'>, view: Viewport, box: Bounds, reverse: boolean) {
  const y = (point.y - view.y0) / (view.y1 - view.y0)
  return { x: box.left + (point.seconds - view.x0) / (view.x1 - view.x0) * box.width,
    y: box.top + (reverse ? 1 - y : y) * box.height }
}
export function clipSegment(a: { seconds: number; y: number }, b: { seconds: number; y: number }, view: Viewport) {
  const dx = b.seconds - a.seconds, dy = b.y - a.y
  let t0 = 0, t1 = 1
  const p = [-dx, dx, -dy, dy], q = [a.seconds - view.x0, view.x1 - a.seconds, a.y - view.y0, view.y1 - a.y]
  for (let i = 0; i < 4; i++) {
    if (p[i] === 0) { if (q[i] < 0) return null; continue }
    const t = q[i] / p[i]
    if (p[i] < 0) t0 = Math.max(t0, t); else t1 = Math.min(t1, t)
    if (t0 > t1) return null
  }
  return [{ seconds: a.seconds + dx * t0, y: a.y + dy * t0 }, { seconds: a.seconds + dx * t1, y: a.y + dy * t1 }]
}
export function zoomViewport(view: Viewport, scale: number, ax = .5, ay = .5, dimension: 'time' | 'station' | 'both' = 'both'): Viewport {
  const result = { ...view }
  if (dimension !== 'station') {
    const width = Math.max(5, Math.min(1e12, (view.x1 - view.x0) * scale)), anchor = view.x0 + (view.x1 - view.x0) * ax
    result.x0 = anchor - width * ax; result.x1 = result.x0 + width
  }
  if (dimension !== 'time') {
    const height = Math.max(.1, (view.y1 - view.y0) * scale), anchor = view.y0 + (view.y1 - view.y0) * ay
    result.y0 = anchor - height * ay; result.y1 = result.y0 + height
  }
  return result
}
export function panViewport(view: Viewport, dx: number, dy: number): Viewport {
  return { x0: view.x0 + dx, x1: view.x1 + dx, y0: view.y0 + dy, y1: view.y1 + dy }
}
export function timeLabel(seconds: number, withSeconds = false) {
  const whole = Math.floor(seconds), days = Math.floor(whole / 86400), value = whole - days * 86400
  const h = String(Math.floor(value / 3600)).padStart(2, '0'), m = String(Math.floor(value % 3600 / 60)).padStart(2, '0')
  return `${days ? `${days > 0 ? '+' : ''}${days}天 ` : ''}${h}:${m}${withSeconds ? ':' + String(value % 60).padStart(2, '0') : ''}`
}
export function localTime(dateBase: string, seconds: number) {
  try {
    const date = new Date(Date.parse(`${dateBase}T00:00:00Z`) + seconds * 1000)
    return date.getUTCFullYear() >= 2020 && date.getUTCFullYear() <= 9999 ? date.toISOString().slice(0, 19) : ''
  } catch { return '' }
}
export function timeRange(dateBase: string, from: string, to: string): [number, number] | null {
  const a = editedSeconds(from, dateBase), b = editedSeconds(to, dateBase)
  return a !== null && b !== null && b > a ? [a, b] : null
}
export function tickStep(view: Viewport, minutes: number, width: number) {
  let step = minutes * 60
  while ((view.x1 - view.x0) / step > Math.max(2, width / 65)) step *= 2
  return step
}

// Move only labels; station grid lines keep their actual equivalent coordinates.
export function spacedLabels(values: number[], top: number, bottom: number, gap: number) {
  const ordered = values.map((value, index) => ({ value, index })).sort((a, b) => a.value - b.value)
  const spacing = Math.min(gap, Math.max(0, bottom - top) / Math.max(1, values.length - 1))
  const positions = ordered.map(item => Math.max(top, Math.min(bottom, item.value)))
  for (let i = 1; i < positions.length; i++) positions[i] = Math.max(positions[i], positions[i - 1] + spacing)
  if (positions.length && positions[positions.length - 1] > bottom) {
    positions[positions.length - 1] = bottom
    for (let i = positions.length - 2; i >= 0; i--) positions[i] = Math.min(positions[i], positions[i + 1] - spacing)
  }
  const result: number[] = []
  ordered.forEach((item, index) => { result[item.index] = positions[index] })
  return result
}
