import type { DelaySnapshot, MetricDisplay, MetricTimeHeatmap } from './api/analysis'

export type HeatmapField = 'arrival' | 'departure'
export interface TimeHeatmapCell {
  station: number; bin: number; total: number; count: number; lateCount: number
  arrivalCount: number; departureCount: number
}
// Timetable strings describe railway wall-clock time. UTC is only a numeric
// calendar coordinate here, so the browser's time zone and DST cannot shift bins.
export function parseHeatmapTime(value: unknown): number | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value)) return null
  const parsed = Date.parse(value + 'Z') / 1000
  return Number.isFinite(parsed) ? parsed : null
}
export function formatHeatmapTime(value: number, date = false) {
  const iso = new Date(value * 1000).toISOString()
  return (date ? iso.slice(0,10).replaceAll('-', '/') + ' ' : '') + iso.slice(11,16)
}
export function buildTimeHeatmap(data: DelaySnapshot, state: Pick<MetricDisplay,'scope'|'station_ids'|'train_ids'>, display: MetricTimeHeatmap) {
  const selectedStations = new Set(state.station_ids), selectedTrains = new Set(state.train_ids)
  const stations = data.stations.filter(s => state.scope === 'all' || selectedStations.has(s.id))
  const stationIndex = new Map(stations.map((s,i) => [s.id,i]))
  const rowStations = new Map(data.rows.map(r => [r.key,stationIndex.get(r.station_id)]))
  const knownTrains = new Set(data.trains.map(t => t.id))
  const step = display.interval_minutes * 60, fields = [...new Set(display.fields)]
  const buckets = new Map<number,Map<number,TimeHeatmapCell>>()
  let first = Infinity, last = -Infinity, count = 0, lateCount = 0, total = 0, missingTime = 0, excluded = 0
  let hasTimeFields = false
  for (const cell of data.cells) {
    const station = rowStations.get(cell.row_key)
    if (station === undefined || !knownTrains.has(cell.train_id) || (state.scope !== 'all' && !selectedTrains.has(cell.train_id))) continue
    for (const field of fields) {
      const key = field === 'arrival' ? 'arrival_time' : 'departure_time'
      if (key in cell) hasTimeFields = true
      const value = cell[field]
      if (typeof value !== 'number' || !Number.isFinite(value)) { excluded++; continue }
      const time = parseHeatmapTime(cell[key])
      if (time === null) { missingTime++; continue }
      first = Math.min(first,time); last = Math.max(last,time)
      // Absolute bins keep arrivals and departures on opposite sides of midnight apart.
      const bin = Math.floor(time / step)
      if (!buckets.has(station)) buckets.set(station,new Map())
      let bucket = buckets.get(station)!.get(bin)
      if (!bucket) {
        bucket = {station,bin,total:0,count:0,lateCount:0,arrivalCount:0,departureCount:0}
        buckets.get(station)!.set(bin,bucket)
      }
      const late = Math.max(0,value)
      bucket.total += late; bucket.count++; bucket[field === 'arrival' ? 'arrivalCount' : 'departureCount']++
      count++; total += late
      if (late > 0) {bucket.lateCount++;lateCount++}
    }
  }
  const start = count ? Math.floor(first / 86400) * 86400 : 0
  const end = count ? (Math.floor(last / 86400) + 1) * 86400 : 0
  const columns = (end-start)/step, firstBin = start/step
  let max = 0
  for (const row of buckets.values()) for (const bucket of row.values()) max = Math.max(max,bucket.total)
  return {stations,buckets,step,start,end,columns,firstBin,max,count,lateCount,total,missingTime,excluded,hasTimeFields}
}
export type TimeHeatmapScene = ReturnType<typeof buildTimeHeatmap>
export function timeHeatmapBucket(scene: TimeHeatmapScene, station: number, column: number) {
  if (station < 0 || station >= scene.stations.length || column < 0 || column >= scene.columns) return undefined
  return scene.buckets.get(station)?.get(scene.firstBin+column)
}
const colors = [[53,42,135],[30,104,212],[20,184,197],[123,208,67],[253,231,37]]
export function timeHeatmapColor(value: number, max: number) {
  const position = max > 0 ? Math.max(0,Math.min(1,value/max))*(colors.length-1) : 0
  const index = Math.min(colors.length-2,Math.floor(position)), amount = position-index
  return 'rgb('+colors[index].map((v,i)=>Math.round(v+(colors[index+1][i]-v)*amount)).join(',')+')'
}
