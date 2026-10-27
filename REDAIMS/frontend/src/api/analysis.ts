import { request, post, type Change, type EditorData, type Train } from './baseImport'
import type { CreateDiagramView, SavedDiagramView } from './diagram'
export type AnalysisSection = 'diagram' | 'log' | 'delay'
export type AnalysisNodeType = 'view' | 'solver-log' | 'delay'
export const analysisLabels: Record<AnalysisNodeType, string> = { view: '视图', 'solver-log': '求解日志', delay: '延误分析' }
export interface AnalysisSource { revision: string; dateBase: string; originalDateBase: string; changes: Change[]; initialLine: string }
export interface SolverLogSummary { id: string; run_id: string; filename: string }
export interface LogDisplay { log_id: string; encoding: 'utf-8' | 'gb18030'; search: string; wrap: boolean; scroll_top: number; scroll_left: number; visualization_state: Record<string, unknown> }
export interface DelaySnapshot {
  version: 1; object: EditorData['object']; base: EditorData['object']; revision: string; unit: 'seconds'
  stations: EditorData['nodes']; trains: Train[]
  rows: { key: string; station_id: string; occurrence: number; node_name: string; node_name_chn: string }[]
  cells: { row_key: string; train_id: string; visit_seq: number; arrival: number | null; departure: number | null; arrival_reason: string; departure_reason: string }[]
  issues: string[]; method: string
}
export interface DelayDisplay {
  station_ids: string[]; train_ids: string[]; highlighted_ids: string[]
  station_search?: string; train_search?: string; open_panels?: string[]
  unit: 'seconds' | 'minutes'; chart_height: number; scroll_top: number; scroll_left: number
  viewport: { x0: number; x1: number; y0: number; y1: number }
}
export interface SavedDelay { state: DelayDisplay; snapshot: DelaySnapshot }
export interface AnalysisState {
  version: 1; expanded_sections: AnalysisSection[]; diagram: CreateDiagramView | null
  log: LogDisplay; delay: SavedDelay | null
}
export interface AnalysisNodeSummary { id: string; run_id: string; node_type: AnalysisNodeType; name: string; created_at: string }
export interface SavedAnalysisNode extends AnalysisNodeSummary { state: AnalysisState }
export interface AnalysisTarget { node?: SavedAnalysisNode; diagram?: SavedDiagramView; logId?: string }
export const defaultLogDisplay = (): LogDisplay => ({ log_id: '', encoding: 'utf-8', search: '', wrap: true, scroll_top: 0, scroll_left: 0, visualization_state: {} })
export const analysisApi = {
  nodes: () => request<AnalysisNodeSummary[]>('/analysis/nodes'),
  logs: () => request<SolverLogSummary[]>('/analysis/logs'),
  node: (run: string, id: string) => request<SavedAnalysisNode>(`/runs/${encodeURIComponent(run)}/analysis-nodes/${encodeURIComponent(id)}`),
  save: (run: string, body: { name: string; node_type: AnalysisNodeType; state: AnalysisState }) => post<AnalysisNodeSummary>(`/runs/${encodeURIComponent(run)}/analysis-nodes`, body),
  runLogs: (run: string) => request<SolverLogSummary[]>(`/runs/${encodeURIComponent(run)}/solver-logs`),
  logText: (run: string, id: string, encoding: LogDisplay['encoding']) => request<{ text: string; filename: string; digest: string }>(`/runs/${encodeURIComponent(run)}/solver-logs/${encodeURIComponent(id)}/text?encoding=${encoding}`),
  delays: (run: string) => request<DelaySnapshot>(`/runs/${encodeURIComponent(run)}/delay-analysis`),
}
