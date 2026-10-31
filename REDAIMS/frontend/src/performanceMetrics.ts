import type { DelaySnapshot, MetricCamera, MetricDisplay, MetricId, MetricTimeHeatmap } from './api/analysis'

export const metricIds: MetricId[] = ['total', 'mean', 'max', 'p95', 'late_rate', 'affected', 'terminal_total', 'terminal_mean', 'terminal_rate', 'terminal_affected']
export const metricPresets: Record<string, MetricId[]> = {
  common: ['total', 'mean', 'max', 'late_rate'],
  terminal: ['terminal_total', 'terminal_mean', 'terminal_rate', 'terminal_affected'],
  distribution: ['mean', 'p95', 'max', 'late_rate'],
}
export const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
export const defaultMetricCamera = (): MetricCamera => ({ azimuth: -40, elevation: 28, zoom: 1 })
export const defaultTimeHeatmap = (): MetricTimeHeatmap => ({ interval_minutes: 10, fields: ['arrival', 'departure'] })
export function normalizeMetricSelection(selected: MetricId[]): MetricId[] {
  const legacy: MetricId[] = ['terminal_total', 'terminal_mean', 'terminal_rate', 'affected']
  return selected.length === legacy.length && legacy.every(id => selected.includes(id))
    ? selected.map(id => id === 'affected' ? 'terminal_affected' : id) : [...selected]
}

// Trusted MathML only: all nodes and symbols below are application constants.
// Run names, station names and user input are never interpolated into these formulas.
const row = (...items: string[]) => '<mrow>' + items.join('') + '</mrow>'
const symbol = (value: string) => '<mi>' + value + '</mi>'
const op = (value: string) => '<mo>' + value + '</mo>'
const number = (value: string) => '<mn>' + value + '</mn>'
const sub = (base: string, index: string) => '<msub>' + base + index + '</msub>'
const frac = (top: string, bottom: string) => '<mfrac>' + top + bottom + '</mfrac>'
const bounds = (operator: string, index: string) => '<munder>' + op(operator) + index + '</munder>'
const card = (value: string) => row(op('|'), value, op('|'))
const indicator = (condition: string) => row(symbol('𝟙'), op('['), condition, op(']'))
const K = sub(symbol('𝒦'), symbol('D'))
const N = symbol('N')
const index = row(symbol('i'), op(','), symbol('k'))
const member = row(op('('), index, op(')'), op('∈'), symbol('ℰ'))
const endMember = row(symbol('k'), op('∈'), K)
const time = (letter: 'a' | 'd', end = false, planned = false) => {
  const value = sub(symbol(letter), end ? row(sub(symbol('D'), symbol('k')), op(','), symbol('k')) : index)
  return planned ? '<msup>' + value + number('0') + '</msup>' : value
}
const deviation = (letter: 'a' | 'd', end = false) => row(time(letter, end), op('−'), time(letter, end, true))
const positive = (value: string) => row('<mi mathvariant="normal">max</mi>', op('('), number('0'), op(','), value, op(')'))
export function metricFormula(id: MetricId, event: MetricDisplay['event'], includeZeroEvents = true) {
  const letter = event === 'arrival' ? 'a' : 'd'
  const delta = deviation(letter), late = positive(delta)
  const total = row(bounds('∑', member), late)
  const lateOnlyMean = !includeZeroEvents
  const positiveMember = row(op('('), index, op(')'), op('∈'), sub(symbol('ℰ'), op('+')))
  const meanFormula = lateOnlyMean ? frac(row(bounds('∑', positiveMember), delta), sub(N, op('+'))) : frac(total, N)
  const endTotal = row(bounds('∑', endMember), positive(deviation('a', true)))
  const endCount = row(bounds('∑', endMember), indicator(row(deviation('a', true), op('>'), symbol('τ'))))
  const definitions: Record<MetricId, string> = {
    total, mean: meanFormula,
    max: row(bounds('max', member), late),
    p95: sub(symbol('L'), row(op('('), op('⌈'), number('0.95'), N, op('⌉'), op(')'))),
    late_rate: row(frac(row(bounds('∑', member), indicator(row(delta, op('>'), symbol('τ')))), N), op('×'), number('100'), op('%')),
    affected: card(row(op('{'), symbol('k'), op(':'), op('∃'), symbol('i'), op(','), member, op(','), delta, op('>'), symbol('τ'), op('}'))),
    terminal_total: endTotal, terminal_mean: frac(endTotal, card(K)),
    terminal_rate: row(frac(endCount, card(K)), op('×'), number('100'), op('%')),
    terminal_affected: endCount,
  }
  const notation = id.startsWith('terminal')
    ? 'a为run到达时刻，上标0为基本图图定到达时刻；Dₖ为列车k在基本图完整路径的终到站；𝒦_D为当前范围内具有有效终到到达时刻的列车集合；τ为晚点阈值。每趟列车一次，不把筛选末站当终到。'
    : 'i为车站访问，k为列车；ℰ为当前范围内的有效' + (event === 'arrival' ? '到达' : '出发') + '事件集合，N为其事件数；a、d为run时刻，上标0为图定时刻；τ为晚点阈值。' + (id === 'p95' ? 'L为所选事件的非负晚点，按升序排列并包含零值。' : '')
  return { formula: row(op('='), definitions[id]), notation: notation + (id === 'mean' && lateOnlyMean ? 'ℰ₊只包含'+(event === 'arrival'?'到达':'出发')+'偏差>0的事件，N₊为其数量；正点、提前、缺失均不计入此平均值分母，与晚点阈值无关。' : '') }
}
export function metricDefinition(id: MetricId, event: MetricDisplay['event'], includeZeroEvents = true) {
  const type = event === 'arrival' ? '到达' : '出发'
  const definitions: Record<MetricId, { label: string; kind: 'time' | 'percent' | 'count'; definition: string }> = {
    total: { label: '累计' + type + '晚点', kind: 'time', definition: '对有效事件的 max(偏差, 0) 求和；同车沿途事件分别累计，提前不抵消晚点。' },
    mean: { label: '平均' + type + '晚点', kind: 'time', definition: !includeZeroEvents ? '仅对'+type+'偏差>0的有效事件取平均；零晚点、提前和缺失不计入分母，与晚点阈值无关。' : '累计晚点 ÷ 全部有效事件数，包含零晚点事件，提前按零晚点计。' },
    max: { label: '最大' + type + '晚点', kind: 'time', definition: '有效事件的非负晚点最大值。' },
    p95: { label: 'P95 ' + type + '晚点', kind: 'time', definition: '非负晚点（包含零）升序排列，取第 ceil(0.95 × N) 个值。' },
    late_rate: { label: type + '晚点率', kind: 'percent', definition: '偏差严格大于阈值的有效事件数 ÷ 全部有效事件数。' },
    affected: { label: '沿途受影响列车数', kind: 'count', definition: '在统计范围内存在超阈值事件的列车数；每趟列车只计一次。' },
    terminal_total: { label: '终到累计晚点', kind: 'time', definition: '完整路径终到到达晚点的累计值；每趟列车一次，不把筛选末站当终到。' },
    terminal_mean: { label: '终到平均晚点', kind: 'time', definition: '终到累计晚点 ÷ 有效终到列车数，包含零晚点列车。' },
    terminal_rate: { label: '终到晚点列车率', kind: 'percent', definition: '终到到达偏差严格大于阈值的列车数 ÷ 有效终到列车数。' },
    terminal_affected: { label: '受影响列车数', kind: 'count', definition: '完整路径终到到达偏差严格大于阈值的列车数；每趟列车只计一次。' },
  }
  return { ...definitions[id], ...metricFormula(id, event, includeZeroEvents) }
}
export function initialMetrics(data: DelaySnapshot): MetricDisplay {
  return { selected: [...metricPresets.common], event: 'arrival', include_zero_arrivals: true, include_zero_departures: true, curve_train_ids: data.trains[0] ? [data.trains[0].id] : [], curve_station_ids: data.stations.map(s=>s.id), curve_mode: '2d', curve_fields: ['arrival','departure'], curve_camera: defaultMetricCamera(), time_heatmap: defaultTimeHeatmap(), unit: 'minutes', threshold_seconds: 0, scope: 'all', station_ids: data.stations.map(s => s.id), train_ids: data.trains.map(t => t.id), active_train_id: data.trains[0]?.id || '', row_offset: 0, train_offset: 0 }
}
export function rankCurveTrains(data: DelaySnapshot) {
  const arrivals = new Map<string, { count: number; lateCount: number; total: number }>()
  for (const cell of data.cells) {
    if (!finite(cell.arrival)) continue
    let stats = arrivals.get(cell.train_id)
    if (!stats) { stats = { count: 0, lateCount: 0, total: 0 }; arrivals.set(cell.train_id, stats) }
    stats.count++
    if (cell.arrival > 0) { stats.lateCount++; stats.total += cell.arrival }
  }
  return data.trains.map(train => {
    const stats = arrivals.get(train.id)
    return { ...train, meanLateArrival: stats?.lateCount ? stats.total / stats.lateCount : null, arrivalCount: stats?.count || 0, lateArrivalCount: stats?.lateCount || 0 }
  }).sort((a, b) => {
    if (a.meanLateArrival === null && b.meanLateArrival !== null) return 1
    if (b.meanLateArrival === null && a.meanLateArrival !== null) return -1
    return (b.meanLateArrival ?? 0) - (a.meanLateArrival ?? 0) || a.train_course_id.localeCompare(b.train_course_id, 'zh-CN', { numeric: true }) || a.train_base_date.localeCompare(b.train_base_date) || a.id.localeCompare(b.id)
  })
}
export function summarizeMetrics(data: DelaySnapshot, state: MetricDisplay) {
  const stations = new Set(state.scope === 'all' ? data.stations.map(s => s.id) : state.station_ids)
  const trains = new Set(state.scope === 'all' ? data.trains.map(t => t.id) : state.train_ids)
  const rows = data.rows.filter(r => stations.has(r.station_id)), rowKeys = new Set(rows.map(r => r.key))
  const rowByKey = new Map(rows.map(r => [r.key, r])), trainById = new Map(data.trains.map(t => [t.id, t]))
  const cells = data.cells.filter(c => trains.has(c.train_id) && rowKeys.has(c.row_key))
  const valid = cells.filter(c => finite(c[state.event]))
  const positive = valid.map(c => Math.max(0, c[state.event]!)).sort((a, b) => a - b)
  const count = valid.length, total = positive.reduce((a, b) => a + b, 0)
  const includeZeroEvents = (state.event === 'arrival' ? state.include_zero_arrivals : state.include_zero_departures) !== false
  const meanSampleCount = includeZeroEvents ? count : positive.filter(v => v > 0).length
  const delayed = valid.filter(c => c[state.event]! > state.threshold_seconds)
  const maxCells = count && positive[count - 1] > 0 ? valid.filter(c => c[state.event] === positive[count - 1]) : []
  const maxTrainIds = new Set(maxCells.map(c => c.train_id))
  const maxTrains = data.trains.filter(t => maxTrainIds.has(t.id))
  const maxEvents = maxCells.map(c => ({
    train_id: c.train_id, row_key: c.row_key, visit_seq: c.visit_seq,
    station: rowByKey.get(c.row_key)?.node_name_chn || rowByKey.get(c.row_key)?.node_name || '未知车站',
    occurrence: rowByKey.get(c.row_key)?.occurrence || 1,
  }))
  const endCandidates = (data.endpoints || []).filter(e => trains.has(e.train_id) && e.terminal_row_key !== null && rowKeys.has(e.terminal_row_key))
  const terminals = endCandidates.filter(e => finite(e.terminal_arrival))
  const terminalDelayed = terminals.filter(e => e.terminal_arrival! > state.threshold_seconds).map(e => ({
    train_id: e.train_id, train_course_id: trainById.get(e.train_id)?.train_course_id || e.train_id,
    train_base_date: trainById.get(e.train_id)?.train_base_date || '',
    row_key: e.terminal_row_key!,
    terminal_station: rowByKey.get(e.terminal_row_key!)?.node_name_chn || rowByKey.get(e.terminal_row_key!)?.node_name || '未知终到站',
    seconds: e.terminal_arrival!,
  })).sort((a, b) => b.seconds - a.seconds || a.train_course_id.localeCompare(b.train_course_id, 'zh-CN', { numeric: true }) || a.train_base_date.localeCompare(b.train_base_date) || a.train_id.localeCompare(b.train_id))
  const endTotal = terminals.reduce((a, e) => a + Math.max(0, e.terminal_arrival!), 0)
  const values: Record<MetricId, number | null> = {
    total: count ? total : null, mean: meanSampleCount ? total / meanSampleCount : null, max: count ? positive[count - 1] : null,
    p95: count ? positive[Math.ceil(.95 * count) - 1] : null,
    late_rate: count ? delayed.length / count * 100 : null,
    affected: count ? new Set(delayed.map(c => c.train_id)).size : null,
    terminal_total: terminals.length ? endTotal : null,
    terminal_mean: terminals.length ? endTotal / terminals.length : null,
    terminal_rate: terminals.length ? terminalDelayed.length / terminals.length * 100 : null,
    terminal_affected: terminals.length ? terminalDelayed.length : null,
  }
  return { values, count, meanSampleCount, excluded: cells.length - count, lateCount: delayed.length, terminalCount: terminals.length, terminalCandidates: endCandidates.length, trainCount: trains.size, rows, cells, trains: data.trains.filter(t => trains.has(t.id)), maxTrains, maxEvents, terminalDelayed }
}
