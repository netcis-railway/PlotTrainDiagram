import type { CatalogNode } from '../api/client'

// One independent BaseTT item under its physical owner. Inherited items are never added.
export interface CatalogTreeNode extends CatalogNode {
  baseReference?: { scopeId: string; runId: string; inherited: boolean }
}
export const baseReferenceId = (scopeId: string, runId: string) => `base-ref:${scopeId}:${runId}`
