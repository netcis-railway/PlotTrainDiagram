export type Kind = 'user' | 'network' | 'scenario' | 'case' | 'algorithm' | 'batch' | 'run'
export interface CatalogNode { id: string; kind: Kind; parent_id: string | null; name: string; notes: string }

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, options)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}
export const api = {
  health: () => request<{ status: string }>('/health'),
  catalog: () => request<CatalogNode[]>('/catalog'),
  create: (node: Omit<CatalogNode, 'id'>) => request<CatalogNode>('/catalog', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(node),
  }),
  notes: (id: string, notes: string) => request(`/catalog/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ notes }),
  }),
  update: (id: string, changes: { name?: string; notes?: string }) => request<CatalogNode>(`/catalog/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(changes),
  }),
}

export interface DeletionPreview {
  owned_experiments?: { id: string; name: string; owner_category_id: string }[];
  member_experiments?: { id: string; name: string; run_id: string }[];
  node_count: number; run_count: number; preview_token: string; can_delete: boolean; physical_base_timetables: { id: string; name: string; owner_category_id: string }[]; legacy_base_ids: string[];
  nodes: { id: string; name: string; kind: Kind }[];
  runs: { id: string; name: string; run_no: number }[];
  eligible_batches: { id: string; name: string }[];
}
export interface UngroupedRun { id: string; name: string; run_no: number; notes?: string; origin_path: { name: string }[] }
export const deletionApi = {
  preview: (id: string) => request<DeletionPreview>(`/catalog/${id}/deletion-preview`),
  remove: (id: string, payload: { action: 'delete' | 'ungroup' | 'move'; target_batch_id: string | null; preview_token: string; confirmed: true }) =>
    request(`/catalog/${id}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
  ungrouped: () => request<UngroupedRun[]>('/runs/ungrouped'),
}
