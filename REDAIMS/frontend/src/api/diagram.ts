import { request, post, type Change, type ClassificationEntry, type EditorData, type EventTime } from './baseImport'
export interface PlotIssue { code: string; severity: 'error' | 'warning'; message: string; train_course_id?: string; event_id?: string }
export interface PlotBase { id: string; baseTT_no: string; name: string; date_base: string; revision: number; classification_path: ClassificationEntry[]; owner_category_id: string }
export interface PlotLine { line_ind: number; line_code: string; line_name_chn: string; station_count: number; available: boolean; issues: PlotIssue[] }
export interface PlotContext { object: EditorData['object']; revision: string; base: PlotBase | null; lines: PlotLine[]; overlay_available: boolean; issues: PlotIssue[] }
export interface PlotStation { node_id: string; node_name: string; node_name_chn: string; node_code: string; node_seq_of_line: number; y: number }
export interface TrackUsage { direction: 'down' | 'up' | 'unknown'; passing: boolean; original_track: number | null; adopted_track: number | null; defaulted: boolean; start_seconds: number | null; end_seconds: number | null; can_occupy: boolean }
export interface TrackResource { node_id: string; node_name: string; node_name_chn: string; line_ind: number; can_expand: boolean; tracks: { number: number; roles: string[] }[]; track_count: number; directions: Partial<Record<'down' | 'up', { stop_tracks: number[]; main_track: number | null }>>; issues: PlotIssue[] }
export interface PlotEvent { track_usage?: TrackUsage; id: string; node_id: string; node_name: string; node_name_chn: string; visit_seq: number; track_code: number | null; arrival: EventTime | null; departure: EventTime | null; source: { sheet?: string; row?: number; first_column?: number } }
export interface PlotPoint { track_offset?: number; calculated?: boolean; usage_kind?: 'track_entry' | 'track_exit' | 'pass_track' | 'track_unassigned'; event_id: string; field: 'arrival' | 'departure'; seconds: number; y: number }
export interface PlotSegment { from: number; to: number; kind: 'dwell' | 'travel' | 'track_enter' | 'track_occupancy' | 'track_leave' | 'track_pass'; anomaly: boolean }
export interface PlotSeries { key: string; object_type: 'base' | 'run'; object_id: string; object_name: string; train_id: string; train_course_id: string; train_base_date: string; direction: 'down' | 'up' | 'unknown'; points: PlotPoint[]; segments: PlotSegment[]; events: PlotEvent[] }
export interface PlotStyles { down: string; up: string; unknown: string; base: string; base_dark: string; grid: string; highlight: string; width: number; point_radius: number; grid_minutes: number; font_size: number; track_gap: number; track_yita_seconds: number; train_styles: Record<string, { color: string | null; width: number | null; dashed: boolean }> }
export interface PlotData { track_stations: TrackResource[]; expanded_stations: string[]; object: EditorData['object']; revision: string; base: PlotBase | null; line_ind: number; axis_revision: string; axis: { stations: PlotStation[]; total: number; unit: string }; series: PlotSeries[]; preview: boolean; preview_changes: number; can_plot: boolean; overlay_base: boolean; time_extent: [number, number] | null; styles: PlotStyles; style_source: string; issues: PlotIssue[]; operation_id: string; log_written: boolean }
export const diagramApi = {
  context: (kind: 'base' | 'run', id: string) => request<PlotContext>(`/diagram/lines?${new URLSearchParams({ object_type: kind, object_id: id })}`),
  data: (body: { object_type: 'base' | 'run'; object_id: string; revision: string; line_ind: number; overlay_base: boolean; expanded_stations?: string[]; changes: Change[]; date_base?: string }) => post<PlotData>('/diagram/data', body),
  styles: () => request<{ styles: PlotStyles; issues: PlotIssue[]; revision: string; source: string; log_written: boolean }>('/diagram/styles'),
  log: () => request<{ filename: string; text: string }>('/diagram/warnings'),
}
