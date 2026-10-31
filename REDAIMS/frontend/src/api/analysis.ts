import { request, post, type Change, type EditorData, type Train } from './baseImport'
import type { CreateDiagramView, SavedDiagramView } from './diagram'
export type AnalysisSection = 'diagram' | 'log' | 'delay'
export type SectionNotes = Partial<Record<AnalysisSection, string | null>>
export interface RunMetadata { id: string; batch_id: string | null; name: string; run_no: number; notes: string; analysis_notes: Partial<Record<AnalysisSection, string>> }
export type AnalysisNodeType = 'view' | 'solver-log' | 'delay' | 'metrics'
export const analysisLabels: Record<AnalysisNodeType, string> = { view: '视图', 'solver-log': '求解日志', delay: '延误预览', metrics: '指标分析' }
export function analysisLabel(type: string): string {
  const label = analysisLabels[type as AnalysisNodeType]
  return typeof label === 'string' ? label : '分析'
}
export interface AnalysisSource { revision: string; dateBase: string; originalDateBase: string; changes: Change[]; initialLine: string }
export type SolverResultSource = 'solver-log' | 'manual' | 'unavailable'
export interface SolverLogSummary { id: string; run_id: string; filename: string; section_notes?: SectionNotes; solver_type?: string; default_plotter?: string | null; detection?: { encoding?: 'utf-8' | 'gb18030' | null; mode?: string; reason?: string }; best_objective?: number | null; solve_seconds?: number | null; objective_source?: SolverResultSource; time_source?: SolverResultSource; result_warnings?: string[] }
export interface SolverPlotter { id: string; label: string; solver_type: string; source_file: string; available: boolean }
export interface SolverLogConfig { solvers: { id: string; label: string; default_plotter: string | null }[]; plotters: SolverPlotter[]; revision: string }
export interface SolverPlot { plotter_id: string; label: string; mime_type: 'image/png'; image_base64: string; image_name: string; solver_type: string; summary: Record<string, number | null> }
export interface LogDisplay { log_id: string; encoding: 'utf-8' | 'gb18030'; search: string; wrap: boolean; scroll_top: number; scroll_left: number; visualization_state: Record<string, unknown> }
export interface DelaySnapshot {
  version: 1; object: EditorData['object']; base: EditorData['object']; revision: string; unit: 'seconds'
  stations: EditorData['nodes']; trains: Train[]
  rows: { key: string; station_id: string; occurrence: number; node_name: string; node_name_chn: string }[]
  cells: { row_key: string; train_id: string; visit_seq: number; arrival: number | null; departure: number | null; arrival_reason: string; departure_reason: string; arrival_time?: string | null; departure_time?: string | null }[]
  issues: string[]; method: string
  endpoints?: { train_id: string; origin_row_key: string | null; terminal_row_key: string | null; origin_departure: number | null; terminal_arrival: number | null; origin_reason: string; terminal_reason: string }[]
}
export interface DelayDisplay {
  station_ids: string[]; train_ids: string[]; highlighted_ids: string[]
  station_search?: string; train_search?: string; open_panels?: string[]
  unit: 'seconds' | 'minutes'; chart_height: number; scroll_top: number; scroll_left: number
  viewport: { x0: number; x1: number; y0: number; y1: number }
}
export interface SavedDelay { state: DelayDisplay; snapshot: DelaySnapshot }
export type MetricId = 'total' | 'mean' | 'max' | 'p95' | 'late_rate' | 'affected' | 'terminal_total' | 'terminal_mean' | 'terminal_rate' | 'terminal_affected'
export interface MetricCamera { azimuth: number; elevation: number; zoom: number }
export interface MetricTimeHeatmap { interval_minutes: 1 | 10 | 60; fields: ('arrival' | 'departure')[] }
export interface MetricDisplay {
  selected: MetricId[]; event: 'arrival' | 'departure'; unit: 'seconds' | 'minutes'
  include_zero_arrivals?: boolean
  include_zero_departures?: boolean
  curve_train_ids?: string[] | null; curve_fields?: ('arrival' | 'departure')[]; curve_camera?: MetricCamera
  curve_station_ids?: string[] | null
  curve_mode?: '2d' | '3d'
  time_heatmap?: MetricTimeHeatmap
  threshold_seconds: number; scope: 'all' | 'selected'; station_ids: string[]; train_ids: string[]
  active_train_id: string; row_offset: number; train_offset: number
}
export interface SavedMetrics { state: MetricDisplay; snapshot: DelaySnapshot }
export interface AnalysisState {
  version: 1; expanded_sections: AnalysisSection[]; diagram: CreateDiagramView | null
  log: LogDisplay; delay: SavedDelay | null
  metrics?: SavedMetrics | null; active_view?: 'workspace' | 'metrics'
}
export interface SavedItemMetadata { name: string; notes: string }
export interface AnalysisNodeSummary { id: string; run_id: string; node_type: AnalysisNodeType; name: string; created_at: string; notes?: string; section_notes?: SectionNotes }
export interface SavedAnalysisNode extends AnalysisNodeSummary { state: AnalysisState }
export interface AnalysisTarget { node?: SavedAnalysisNode; diagram?: SavedDiagramView; logId?: string }
export const defaultLogDisplay = (): LogDisplay => ({ log_id: '', encoding: 'utf-8', search: '', wrap: true, scroll_top: 0, scroll_left: 0, visualization_state: {} })
export const analysisApi = {
  logMetadata: (run: string, id: string) => request<SolverLogSummary>(`/runs/${encodeURIComponent(run)}/solver-logs/${encodeURIComponent(id)}`),
  updateLogResults: (run: string, id: string, body: { best_objective?: number | null; solve_seconds?: number | null }) => request<SolverLogSummary>(`/runs/${encodeURIComponent(run)}/solver-logs/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  runMetadata: (run: string) => request<RunMetadata>(`/runs/${encodeURIComponent(run)}/metadata`),
  updateRun: (run: string, body: { name: string; notes: string }) => request<RunMetadata>(`/runs/${encodeURIComponent(run)}/metadata`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  runSectionNote: (run: string, section: AnalysisSection, notes: string) => request<RunMetadata>(`/runs/${encodeURIComponent(run)}/analysis-notes`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ section, notes }) }),
  logSectionNote: (run: string, id: string, section: AnalysisSection, notes: string | null) => request<SolverLogSummary>(`/runs/${encodeURIComponent(run)}/solver-logs/${encodeURIComponent(id)}/section-notes`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ section, notes }) }),
  nodeSectionNote: (run: string, id: string, section: AnalysisSection, notes: string | null) => request<AnalysisNodeSummary>(`/runs/${encodeURIComponent(run)}/analysis-nodes/${encodeURIComponent(id)}/section-notes`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ section, notes }) }),
  logConfig: () => request<SolverLogConfig>('/solver-logs/config'),
  classifyLog: (run: string, id: string, solverType = 'auto') => post<SolverLogSummary>(`/runs/${encodeURIComponent(run)}/solver-logs/${encodeURIComponent(id)}/classify`, { solver_type: solverType }),
  plotLog: (run: string, id: string, encoding: LogDisplay['encoding'], plotterId: string) => post<SolverPlot>(`/runs/${encodeURIComponent(run)}/solver-logs/${encodeURIComponent(id)}/visualization`, { encoding, plotter_id: plotterId }),
  nodes: () => request<AnalysisNodeSummary[]>('/analysis/nodes'),
  logs: () => request<SolverLogSummary[]>('/analysis/logs'),
  node: (run: string, id: string) => request<SavedAnalysisNode>(`/runs/${encodeURIComponent(run)}/analysis-nodes/${encodeURIComponent(id)}`),
  deleteNode: (run: string, id: string) => request(`/runs/${encodeURIComponent(run)}/analysis-nodes/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  deleteLog: (run: string, id: string) => request(`/runs/${encodeURIComponent(run)}/solver-logs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  save: (run: string, body: { name: string; notes?: string; section_notes?: SectionNotes; node_type: AnalysisNodeType; state: AnalysisState }) => post<AnalysisNodeSummary>(`/runs/${encodeURIComponent(run)}/analysis-nodes`, body),
  update: (run: string, id: string, body: SavedItemMetadata) => request<AnalysisNodeSummary>(`/runs/${encodeURIComponent(run)}/analysis-nodes/${encodeURIComponent(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  runLogs: (run: string) => request<SolverLogSummary[]>(`/runs/${encodeURIComponent(run)}/solver-logs`),
  logText: (run: string, id: string, encoding: LogDisplay['encoding']) => request<{ text: string; filename: string; digest: string; solver_type?: string; default_plotter?: string | null; detection?: SolverLogSummary['detection'] }>(`/runs/${encodeURIComponent(run)}/solver-logs/${encodeURIComponent(id)}/text?encoding=${encoding}`),
  delays: (run: string) => request<DelaySnapshot>(`/runs/${encodeURIComponent(run)}/delay-analysis`),
}
