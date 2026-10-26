import type { Change } from './baseImport'
export interface RepairTrain { id: string; train_course_id: string; direction: 'UB' | 'DB' | null; related_lines: number[]; missing_g: boolean; empty_count: number; visits: number }
export interface RepairContext { repair_token: string; trains: RepairTrain[]; lines: { line_ind: number; line_name_chn: string }[] }
export interface RepairSelection { train_id: string; lines: { line_ind: number; directions: ('UB' | 'DB')[] }[] }
export interface RepairIssue { train_course_id: string; node_name: string; node_name_chn: string; message: string }
export interface RepairResult { can_apply: boolean; changes: Change[]; issues: RepairIssue[]; warnings: RepairIssue[] }
export interface RepairRow { train: RepairTrain; selected: boolean; lines: { line_ind: number; selected: boolean; UB: boolean; DB: boolean }[] }
export function initialRepairRows(context: RepairContext): RepairRow[] {
  return context.trains.map(train => ({ train, selected: train.missing_g || train.empty_count > 0,
    lines: context.lines.map(line => ({ line_ind: line.line_ind, selected: train.related_lines.includes(line.line_ind), UB: train.related_lines.includes(line.line_ind) && train.direction === 'UB', DB: train.related_lines.includes(line.line_ind) && train.direction === 'DB' })) }))
}
export function repairSelections(rows: RepairRow[]): RepairSelection[] {
  return rows.filter(row => row.selected).map(row => ({ train_id: row.train.id,
    lines: row.lines.filter(line => line.selected).map(line => ({ line_ind: line.line_ind,
      directions: [...(line.UB ? ['UB' as const] : []), ...(line.DB ? ['DB' as const] : [])] })) }))
}

export function repairLineState(rows: RepairRow[], lineInd: number) {
  const cells = rows.flatMap(row => row.lines.filter(line => line.line_ind === lineInd))
  const checked = cells.some(line => line.selected || line.UB || line.DB)
  return { checked, indeterminate: checked && !cells.every(line => line.selected && (line.UB || line.DB)) }
}
export function setRepairLine(rows: RepairRow[], lineInd: number, checked: boolean) {
  for (const row of rows) {
    const line = row.lines.find(line => line.line_ind === lineInd)
    if (!line) continue
    line.selected = checked
    line.UB = checked && row.train.direction === 'UB'
    line.DB = checked && row.train.direction === 'DB'
  }
}
