import { post, request, type ValidationIssue } from './baseImport'

export interface WorkbookChange { sheet: string; row: number; column: number; value: string | null }
export interface WorkbookPage {
  revision: string; name: string; date_base: string; sheets: string[]; sheet: string
  headers: string[]; columns: string[]; total_rows: number; offset: number; limit: number
  total_columns: number; column_offset: number; column_limit: number
  rows: { row: number; cells: { value: string; editable: boolean; bold: boolean; number_format: string }[] }[]
}
export interface WorkbookValidation {
  can_save: boolean; validation_token: string; change_count: number; issues: ValidationIssue[]
  train_date_changes: { train_course_id: string; before: string; after: string }[]
  summary: { nodes: number; trains: number; events: number }
}
const path = (id: string) => `/base-timetables/${encodeURIComponent(id)}/workbook`
export const baseWorkbookApi = {
  read: (id: string, sheet = '', offset = 0, columnOffset = 0) => request<WorkbookPage>(`${path(id)}?${new URLSearchParams({ ...(sheet ? { sheet } : {}), offset: String(offset), column_offset: String(columnOffset) })}`),
  validate: (id: string, revision: string, changes: WorkbookChange[]) => post<WorkbookValidation>(`${path(id)}/validate`, { revision, changes }),
  save: (id: string, revision: string, changes: WorkbookChange[], validation_token: string, warnings_confirmed: boolean, train_dates_confirmed: boolean) => post<{ saved: boolean; owner_category_id: string }>(`${path(id)}/save`, { revision, changes, validation_token, warnings_confirmed, train_dates_confirmed }),
  async export(id: string, revision: string) {
    const response = await fetch(`/api/v1${path(id)}/export?${new URLSearchParams({ revision })}`)
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(typeof body?.detail === 'string' ? body.detail : `导出失败（HTTP ${response.status}）`)
    }
    if (!response.headers.get('content-type')?.includes('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')) throw new Error('导出响应不是Excel文件，请检查后端与代理配置')
    return response.blob()
  },
}
