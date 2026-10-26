import type { PlotEvent, PlotSeries, PlotStation } from './api/diagram'

export interface ComparisonRow {
  key: string
  name: string
  visit: number
  repeated: boolean
  events: (PlotEvent | null)[]
}

// Match visits by station identity and occurrence, preserving each train's own SEQ and empty times.
export function comparisonRows(series: PlotSeries[], stations: PlotStation[]): ComparisonRow[] {
  const nodes = new Map(stations.map(station => [station.node_id, { name: station.node_name_chn, count: 0 }]))
  const visits = series.map(train => {
    const byNode = new Map<string, PlotEvent[]>()
    for (const event of train.events.slice().sort((a, b) => a.visit_seq - b.visit_seq)) {
      const events = byNode.get(event.node_id) || []
      events.push(event)
      byNode.set(event.node_id, events)
      if (!nodes.has(event.node_id)) nodes.set(event.node_id, { name: event.node_name_chn, count: 0 })
      const node = nodes.get(event.node_id)!
      node.count = Math.max(node.count, events.length)
    }
    return byNode
  })
  return [...nodes].flatMap(([id, node]) => Array.from({ length: node.count }, (_, index) => ({
    key: id + ':' + index,
    name: node.name,
    visit: index + 1,
    repeated: node.count > 1,
    events: visits.map(train => train.get(id)?.[index] || null),
  })))
}
