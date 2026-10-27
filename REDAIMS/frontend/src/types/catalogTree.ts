import type { CatalogNode } from '../api/client'

// One independent BaseTT item under its physical owner. Inherited items are never added.
export interface CatalogTreeNode extends CatalogNode {
  analysisReference?: { runId: string; nodeId: string; nodeType: 'view' | 'solver-log' | 'delay' }
  logReference?: { runId: string; logId: string }
  viewReference?: { runId: string; viewId: string }
  baseReference?: { scopeId: string; runId: string; inherited: boolean }
}
export const analysisReferenceId = (runId: string, nodeId: string) => `analysis-ref:${runId}:${nodeId}`
export const logReferenceId = (runId: string, logId: string) => `log-ref:${runId}:${logId}`
export const viewReferenceId = (runId: string, viewId: string) => `view-ref:${runId}:${viewId}`
export const baseReferenceId = (scopeId: string, runId: string) => `base-ref:${scopeId}:${runId}`
