import type { Change } from './baseImport'
export interface RepairTrain { id: string; train_course_id: string; direction: 'UB' | 'DB' | null; related_lines: number[]; missing_g: boolean; empty_count: number; conflict_count?: number; visits: number }
export interface RepairContext { warnings?: RepairIssue[]; repair_token: string; trains: RepairTrain[]; lines: { line_ind: number; line_name_chn: string }[] }
export interface RepairSelection { train_id: string; lines: { line_ind: number; directions: ('UB' | 'DB')[] }[] }
export interface RepairIssue { train_course_id: string; node_name: string; node_name_chn: string; message: string }
export interface RepairResult { can_apply: boolean; changes: Change[]; issues: RepairIssue[]; warnings: RepairIssue[] }
export interface RepairRow { train: RepairTrain; selected: boolean; lines: { line_ind: number; readonly available: boolean; selected: boolean; UB: boolean; DB: boolean }[] }
export function initialRepairRows(context: RepairContext): RepairRow[] {
  return context.trains.map(train => ({ train, selected: train.missing_g || train.empty_count > 0,
    lines: context.lines.map(line => ({ line_ind: line.line_ind, available: train.related_lines.includes(line.line_ind), selected: train.related_lines.includes(line.line_ind), UB: train.related_lines.includes(line.line_ind) && train.direction === 'UB', DB: train.related_lines.includes(line.line_ind) && train.direction === 'DB' })) }))
}
export function repairSelections(rows: RepairRow[]): RepairSelection[] {
  return rows.filter(row => row.selected).map(row => ({ train_id: row.train.id,
    lines: row.lines.filter(line => line.available && row.train.related_lines.includes(line.line_ind) && line.selected).map(line => ({ line_ind: line.line_ind,
      directions: [...(line.UB ? ['UB' as const] : []), ...(line.DB ? ['DB' as const] : [])] })) }))
}

export function repairLineState(rows: RepairRow[], lineInd: number) {
  const cells = rows.flatMap(row => row.lines.filter(line => line.line_ind === lineInd && line.available))
  const checked = cells.some(line => line.selected || line.UB || line.DB)
  const direction: 'UB' | 'DB' | null = cells.length && cells.every(line => line.selected && line.UB && !line.DB) ? 'UB'
    : cells.length && cells.every(line => line.selected && line.DB && !line.UB) ? 'DB' : null
  return { checked, indeterminate: checked && !cells.every(line => line.selected && (line.UB || line.DB)), direction, disabled: cells.length === 0 }
}
export function setRepairLine(rows: RepairRow[], lineInd: number, checked: boolean) {
  for (const row of rows) {
    const line = row.lines.find(line => line.line_ind === lineInd)
    if (!line) continue
    line.selected = checked && line.available
    line.UB = line.selected && row.train.direction === 'UB'
    line.DB = line.selected && row.train.direction === 'DB'
  }
}

export function setRepairDirection(line: RepairRow['lines'][number], direction: 'UB' | 'DB') {
  if (!line.available) return
  line.UB = direction === 'UB'
  line.DB = direction === 'DB'
}

// Apply to all eligible rows, including search-hidden and currently unselected trains.
export function setRepairLineDirection(rows: RepairRow[], lineInd: number, direction: 'UB' | 'DB') {
  for (const row of rows) {
    const line = row.lines.find(line => line.line_ind === lineInd)
    if (!line) continue
    if (!line.available) { line.selected = false; line.UB = false; line.DB = false; continue }
    line.selected = true
    setRepairDirection(line, direction)
  }
}

export function setConflictRepairSelection(rows: RepairRow[], enabled: boolean) {
  if (enabled) for (const row of rows) if (row.train.conflict_count) row.selected = true
}
