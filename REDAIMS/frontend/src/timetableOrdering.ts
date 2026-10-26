import type { Change, EditorLine, EditorNode, EventTime, TimetableEvent, Train } from './api/baseImport'

export type StationSort = 'original' | 'down' | 'up'
export type TrainSort = 'original' | 'arrival' | 'departure'

export function originalOrder<T extends { id: string }>(items: T[], ids: string[] = []): T[] {
  const rank = new Map(ids.map((id, index) => [id, index]))
  return items.map((item, index) => ({ item, index })).sort((a, b) =>
    (rank.get(a.item.id) ?? Infinity) - (rank.get(b.item.id) ?? Infinity) || a.index - b.index
  ).map(value => value.item)
}
export function availableLines(nodes: EditorNode[], known: EditorLine[] = []): EditorLine[] {
  const result = new Map<number, EditorLine>()
  for (const item of known) {
    if (Number.isInteger(item.line_ind) && item.line_ind > 0) result.set(item.line_ind, item)
  }
  for (const node of nodes) for (const ind of node.line_inds || []) {
    if (Number.isInteger(ind) && ind > 0 && !result.has(ind)) result.set(ind, { line_ind: ind, line_code: '', line_name_chn: '' })
  }
  return [...result.values()].sort((a, b) => a.line_ind - b.line_ind)
}
export function stationsOnLine(nodes: EditorNode[], selectedLine: string): EditorNode[] {
  return selectedLine ? nodes.filter(node => node.line_inds?.includes(Number(selectedLine))) : nodes
}
function compareNumber(a: number | undefined, b: number | undefined, sign = 1) {
  if (a === undefined) return b === undefined ? 0 : 1
  if (b === undefined) return -1
  return (a - b) * sign
}
function line(node: EditorNode) {
  const values = (node.line_inds || []).filter(value => Number.isInteger(value) && value > 0)
  return values.length ? Math.min(...values) : undefined
}
export function orderStations(nodes: EditorNode[], mode: StationSort, ids: string[] = [], selectedLine = '') {
  const result = originalOrder(nodes, ids)
  if (mode === 'original') return result
  const sign = mode === 'down' ? 1 : -1
  return result.sort((a, b) => (!selectedLine ? compareNumber(line(a), line(b), sign) : 0) ||
    compareNumber(a.node_ind ?? undefined, b.node_ind ?? undefined, sign))
}
function dayValue(text: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
  if (!match) return null
  const [year, month, day] = match.slice(1).map(Number)
  if (year < 2020) return null
  const value = Date.UTC(year, month - 1, day), date = new Date(value)
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day ? value : null
}
export function editedSeconds(value: Change['value'], dateBase: string): number | null {
  if (typeof value !== 'string' || !value.trim()) return null
  const text = value.trim()
  const duration = /^(\d+):([0-5]\d):([0-5]\d(?:\.\d+)?)$/.exec(text)
  if (duration) {
    const seconds = Math.round(Number(duration[1]) * 3600 + Number(duration[2]) * 60 + Number(duration[3]))
    return Number.isSafeInteger(seconds) && seconds >= 0 ? seconds : null
  }
  const full = /^(\d{4}-\d{2}-\d{2})[T ]([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d(?:\.\d+)?))?$/.exec(text)
  if (!full) return null
  const start = dayValue(dateBase), day = dayValue(full[1])
  if (start === null || day === null) return null
  const seconds = Math.round((day - start) / 1000 + Number(full[2]) * 3600 + Number(full[3]) * 60 + Number(full[4] || 0))
  return Number.isSafeInteger(seconds) && seconds >= 0 ? seconds : null
}
// NODE_SEQ_OF_LINE is per-line business order. NODE_IND is only an identity index.
function nearbyStations(nodes: EditorNode[], station: string, selectedLine: string): EditorNode[] {
  const origin = nodes.find(node => node.id === station)
  if (!origin) return []
  const originLines = [...new Set((origin.line_inds || []).filter(ind => Number.isInteger(ind) && ind > 0))]
  const routes = selectedLine ? originLines.filter(ind => ind === Number(selectedLine)) : originLines
  const candidates: { node: EditorNode; steps: number; line: number; seq: number }[] = []
  for (const ind of routes) {
    const start = origin.line_seqs?.[String(ind)]
    if (!Number.isInteger(start) || start! <= 0) continue
    const route = nodes.filter(node => node.line_inds?.includes(ind)).map(node => ({ node, seq: node.line_seqs?.[String(ind)] }))
      .filter((item): item is { node: EditorNode; seq: number } => Number.isInteger(item.seq) && item.seq! > 0)
    // An ambiguous line order cannot be replaced by NODE_IND or array order.
    if (new Set(route.map(item => item.seq)).size !== route.length) continue
    for (const { node, seq } of route) if (node.id !== station) candidates.push({ node, steps: Math.abs(seq - start!), line: ind, seq })
  }
  candidates.sort((a, b) => a.steps - b.steps || a.line - b.line || a.seq - b.seq)
  const seen = new Set<string>()
  return candidates.filter(({ node }) => {
    if (seen.has(node.id)) return false
    seen.add(node.id); return true
  }).map(({ node }) => node)
}
export function orderTrains(trains: Train[], events: TimetableEvent[], station: string, mode: TrainSort,
  changes: Record<string, Change>, dateBase: string, ids: string[] = [], nodes: EditorNode[] = [], selectedLine = '') {
  const result = originalOrder(trains, ids)
  if (mode === 'original' || !station) return result
  const other = mode === 'arrival' ? 'departure' : 'arrival'
  const visits = new Map<string, Map<string, TimetableEvent>>()
  for (const event of events) {
    if (!visits.has(event.train_id)) visits.set(event.train_id, new Map())
    visits.get(event.train_id)!.set(event.node_id, event)
  }
  function seconds(event: TimetableEvent | undefined, field: 'arrival' | 'departure'): number | undefined {
    if (!event) return undefined
    const change = changes[`${event.id}:${field}`]
    const value = change ? editedSeconds(change.value, dateBase) : (event[field] as EventTime | null)?.seconds
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined
  }
  const neighbors = nearbyStations(nodes, station, selectedLine)
  const keys = new Map<string, { time: number | undefined; priority: number }>()
  for (const train of trains) {
    const trainVisits = visits.get(train.id), event = trainVisits?.get(station)
    let time = seconds(event, mode), priority = 1
    if (time === undefined) { time = seconds(event, other); priority = 2 }
    // A real visit with two empty/invalid times stays unsorted; it is not a non-visit.
    if (!event) {
      priority = 3
      for (const node of neighbors) {
        const visit = trainVisits?.get(node.id)
        time = seconds(visit, mode) ?? seconds(visit, other)
        if (time !== undefined) break
      }
    }
    keys.set(train.id, { time, priority: time === undefined ? 4 : priority })
  }
  // Fallbacks are inserted by time, not appended as separate priority blocks.
  // Stable ties use priority first, then the original Excel column order.
  return result.sort((a, b) => {
    const left = keys.get(a.id)!, right = keys.get(b.id)!
    return compareNumber(left.time, right.time) || left.priority - right.priority
  })
}
