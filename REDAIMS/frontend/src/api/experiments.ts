import { post, request, type ClassificationEntry, type EffectiveBase } from './baseImport'

export interface ExperimentRun {
  id: string; batch_id: string | null; name: string; run_no: number;
  classification_path: ClassificationEntry[]; effective_base: EffectiveBase;
  date_base: string | null; unavailable_reason: string;
}
export interface Experiment {
  id: string; name: string; notes: string; owner_category_id: string; revision: number;
  classification_path: ClassificationEntry[]; member_mode: 'fixed';
  member_ids: string[]; member_count: number; members: ExperimentRun[];
  status: 'empty' | 'ready' | 'invalid'; issues: string[];
  base_tt_id: string | null; date_base: string | null;
}
const url = (id: string) => `/experiments/${encodeURIComponent(id)}`
const json = (method: string, body: object) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const experimentApi = {
  list: () => request<Experiment[]>('/experiments'),
  runs: () => request<ExperimentRun[]>('/experiments/runs'),
  detail: (id: string) => request<Experiment>(url(id)),
  create: (data: { name: string; owner_category_id: string; notes: string }) => post<Experiment>('/experiments', data),
  update: (id: string, data: { revision: number; name: string; owner_category_id: string; notes: string }) => request<Experiment>(url(id), json('PATCH', data)),
  add: (id: string, data: { revision: number; run_ids: string[]; batch_ids: string[] }) => post<Experiment>(url(id) + '/members', data),
  remove: (id: string, data: { revision: number; run_ids: string[] }) => request<Experiment>(url(id) + '/members', json('DELETE', data)),
  delete: (id: string, revision: number) => request(url(id), json('DELETE', { revision, confirmed: true })),
}
