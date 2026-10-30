export interface ClassificationEntry { id: string; kind: string; name: string }
export interface ValidationIssue { node_ind?: number | string; node_name?: string; node_name_chn?: string; sheet?: string; row?: number; cell?: string; field?: string; severity: 'error' | 'warning'; message: string; event_id?: string }
export interface PreviewTable { name: string; headers: (string | null)[]; rows: { row: number; values: unknown[] }[]; total_rows: number }
export interface EffectiveBase { mode: 'physical' | 'inherited' | 'missing'; base_tt_id: string | null; name?: string; baseTT_no?: string; owner_category_id: string | null; owner_path?: ClassificationEntry[] }
export interface Resolution { requested_category_id: string; effective: EffectiveBase; local_base: EffectiveBase | null }
export interface BaseTimetable { id: string; base_tt_id: string; baseTT_no: string; object_type: 'base'; owner_category_id: string; name: string; date_base: string; revision: number; classification_path: ClassificationEntry[]; summary: Record<string, number>; metadata: { issues: ValidationIssue[] }; source_files: { id: string; filename: string; digest: string; managed_path: string }[]; working_file?: { managed_path: string; digest: string } | null }
export interface OrdinaryRun { id: string; batch_id: string | null; name: string; run_no: number }
export interface Impact { kind: string; id: string; name: string; before: EffectiveBase; after: EffectiveBase }
export interface MovePreview { preview_token: string; source_path: ClassificationEntry[]; target_path: ClassificationEntry[]; can_move: boolean; occupied_base_id?: string; issues: ValidationIssue[]; impact: Impact[] }
export interface Train { id: string; train_course_id: string; train_base_date: string; adopted_seq?: number; fallback?: boolean }
export interface ImportJob { job_id: string; filename: string; state: string; base_tt_id: string | null; error: string | null; report: { can_commit: boolean; preview_token: string; replacement: BaseTimetable | null; effective_before: EffectiveBase; impact: Impact[]; issues: ValidationIssue[]; previews: PreviewTable[]; summary: Record<string, number>; trains: Train[]; options: { owner_category_id: string; name: string; date_base: string; date_mode: 'rebase' | 'preserve'; sheet?: string | null } } }
export interface EventTime { hms: string; seconds: number; day_offset: number }
export interface TimetableEvent { id: string; node_id: string; train_id: string; node_name: string; train_course_id: string; visit_seq: number; track_code: number | null; arrival: EventTime | null; departure: EventTime | null }
export interface EditorNode { id: string; node_name_chn: string; node_name: string; node_ind?: number | null; line_inds?: number[]; line_seqs?: Record<string, number | null> }
export interface EditorLine { line_ind: number; line_code: string; line_name_chn: string }
export interface OriginalOrder { nodes: string[]; trains: string[]; source: 'excel' | 'provenance'; notice: string }
export interface EditorData { object: { id: string; object_type: 'base' | 'run'; name: string; baseTT_no?: string; run_no?: number; owner_category_id: string | null; date_base: string | null; classification_path: ClassificationEntry[] }; revision: string; nodes: EditorNode[]; route_nodes?: EditorNode[]; display_lines?: EditorLine[]; original_order?: OriginalOrder; trains: Train[]; events: TimetableEvent[]; infrastructure: Record<string, unknown[]> }
export type EditField = 'arrival' | 'departure' | 'track_code' | 'visit_seq'
export interface Change { event_id: string; field: EditField; value: string | number | null }
export interface EditValidation { can_save: boolean; validation_token: string; change_count: number; issues: ValidationIssue[]; date_base_change?: { before: string; after: string } | null; train_date_changes: { train_course_id: string; before: string; after: string }[] }
export async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const path = `/api/v1${url}`, method = options?.method?.toUpperCase() || 'GET'
  const response = await fetch(path, options)
  if (response.status === 204) return undefined as T
  const body = await response.text()
  const context = `HTTP ${response.status}，${method} ${path}`
  let data: unknown
  try { data = JSON.parse(body) }
  catch {
    let hint = '请检查后端服务及 /api/ 反向代理配置。'
    if (response.status === 413) hint = '请求体超过服务器或代理的大小限制；如使用 Nginx，请检查 client_max_body_size。'
    else if ([502, 503, 504].includes(response.status)) hint = '请检查后端服务是否正常运行，以及反向代理的连接和超时日志。'
    else if ([404, 405].includes(response.status)) hint = '请检查后端代码是否已更新并重启，以及 /api/ 是否正确代理到后端。'
    else if (response.status >= 500) hint = '后端处理失败，请查看 Python 后端服务的异常日志。'
    else if (response.ok || response.redirected) hint = 'API 请求可能被转到了前端页面或登录页，请检查 /api/ 代理及重定向配置。'
    const contentType = response.headers.get('content-type') || '未提供 Content-Type'
    const problem = body.trim() ? '返回内容不是有效 JSON' : '返回内容为空'
    throw new Error(`请求失败（${context}）：${problem}（${contentType}）。${hint}`)
  }
  if (!response.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : undefined
    const message = typeof detail === 'string' ? detail : detail == null ? '请求失败' : JSON.stringify(detail)
    throw new Error(`${message}（${context}）`)
  }
  return data as T
}
export const post = <T>(url: string, body: object) => request<T>(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const objectUrl = (kind: 'base' | 'run', id: string) => `/${kind === 'base' ? 'base-timetables' : 'runs'}/${id}`
export const baseApi = {
  preview: (params: URLSearchParams, file: File) => request<ImportJob>(`/base-timetables/import/preview?${params}`, { method: 'POST', body: file }),
  jobs: () => request<ImportJob[]>('/ingest/jobs'), job: (id: string) => request<ImportJob>(`/ingest/jobs/${id}`),
  cancel: (id: string) => request(`/ingest/jobs/${id}`, { method: 'DELETE' }),
  commit: (id: string, body: object) => post<BaseTimetable>(`/base-timetables/import/${id}/commit`, body),
  bases: () => request<BaseTimetable[]>('/base-timetables'), base: (id: string) => request<BaseTimetable>(`/base-timetables/${id}`),
  runs: () => request<OrdinaryRun[]>('/runs'), resolution: (id: string) => request<Resolution>(`/catalog/${id}/base-timetable`),
  deletePreview: (id: string) => request<{ preview_token: string; can_delete: boolean; impact: Impact[]; blocking_dependencies: Impact[] }>(`/base-timetables/${id}/deletion-preview`),
  deleteBase: (id: string, token: string) => request(`/base-timetables/${id}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed: true, preview_token: token }) }),
}
export const labels: Record<string, string> = { user: '研究员', network: '路网', scenario: '场景', case: '案例', algorithm: '算法', batch: '批次', run: 'run' }
export const formatPath = (chain: ClassificationEntry[]) => chain.map(n => `${labels[n.kind] || n.kind}：${n.name}`).join(' → ')

export function formatIssueNode(issue: ValidationIssue) {
  const parts: string[] = []
  if (issue.node_ind !== undefined && issue.node_ind !== null && issue.node_ind !== '') parts.push(`NODE_IND=${issue.node_ind}`)
  if (issue.node_name) parts.push(`NODE_NAME=${issue.node_name}`)
  if (issue.node_name_chn) parts.push(`站名=${issue.node_name_chn}`)
  return parts.length ? ` · ${parts.join(' / ')}` : ''
}
