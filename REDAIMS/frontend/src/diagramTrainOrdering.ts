import type { PlotData, PlotSeries } from './api/diagram'

const types = ['X', 'G', 'T', 'K', 'D']
const text = new Intl.Collator('en', { numeric: true, sensitivity: 'base' })
function numberPart(course: string) {
  const digits = course.match(/\d+/)?.[0]
  return digits === undefined ? null : digits.replace(/^0+(?=\d)/, '')
}
function compareNumber(a: string | null, b: string | null) {
  if (a === null) return b === null ? 0 : 1
  if (b === null) return -1
  return a.length - b.length || (a < b ? -1 : a > b ? 1 : 0)
}
function runNumber(series: PlotSeries, object?: PlotData['object']) {
  const value = series.run_no ?? (series.object_id === object?.id ? object.run_no : undefined)
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : Infinity
}

// Sort only presentation options; series identities and the plot's drawing order stay intact.
export function orderPlotTrains(series: readonly PlotSeries[], object?: PlotData['object']): PlotSeries[] {
  return series.map(item => {
    const course = item.train_course_id.trim().toUpperCase(), prefix = course.charAt(0)
    const rank = types.indexOf(prefix)
    return { item, course, prefix, rank: rank < 0 ? types.length : rank, number: numberPart(course), run: item.object_type === 'base' ? -1 : runNumber(item, object) }
  }).sort((a, b) => a.rank - b.rank
    || (a.rank === types.length ? text.compare(a.prefix, b.prefix) : 0)
    || compareNumber(a.number, b.number)
    || (a.run < b.run ? -1 : a.run > b.run ? 1 : 0)
    || text.compare(a.course, b.course)
    || text.compare(a.item.train_base_date, b.item.train_base_date)
    || text.compare(a.item.object_name, b.item.object_name)
    || text.compare(a.item.object_id, b.item.object_id)
    || text.compare(a.item.key, b.item.key)
  ).map(entry => entry.item)
}
