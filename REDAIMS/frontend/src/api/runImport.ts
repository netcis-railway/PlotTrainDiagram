import { request, post, type EditorData, type EffectiveBase, type ClassificationEntry, type PreviewTable, type Train, type ValidationIssue } from './baseImport'

export interface RunImportOptions {
  batch_id: string; name: string; run_no: number; date_base: string
  date_mode: 'rebase' | 'preserve'; sheet: string | null
  write_mode: 'create' | 'replace'; target_run_id: string | null
}
export interface RunJobSummary { job_id: string; filename: string; state: string; run_id: string | null; error: string | null }
export interface RunImportJob extends RunJobSummary {
  report: {
    can_commit: boolean; preview_token: string; options: RunImportOptions
    classification_path: ClassificationEntry[]; effective_base: EffectiveBase
    replacement: (EditorData['object'] & { summary: Record<string, number> }) | null
    issues: ValidationIssue[]; summary: Record<string, number>; trains: Train[]
    previews: PreviewTable[]; available_sheets: string[]
  }
}
export const runImportApi = {
  preview: (params: URLSearchParams, file: File) => request<RunImportJob>(`/runs/import/preview?${params}`, { method: 'POST', body: file }),
  jobs: () => request<RunJobSummary[]>('/runs/import/jobs'),
  job: (id: string) => request<RunImportJob>(`/runs/import/jobs/${id}`),
  cancel: (id: string) => request(`/runs/import/jobs/${id}`, { method: 'DELETE' }),
  commit: (id: string, body: object) => post<EditorData['object']>(`/runs/import/${id}/commit`, body),
}
