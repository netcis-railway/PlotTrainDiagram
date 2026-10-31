import type { CatalogNode } from '../api/client'
import type { Experiment } from '../api/experiments'
import type { AnalysisNodeType } from '../api/analysis'

// One independent BaseTT item under its physical owner. Inherited items are never added.
export interface CatalogTreeNode extends CatalogNode {
  experimentReference?: { experimentId: string; ownerId: string; virtual: boolean; runId?: string }
  analysisReference?: { runId: string; nodeId: string; nodeType: AnalysisNodeType }
  logReference?: { runId: string; logId: string }
  viewReference?: { runId: string; viewId: string }
  baseReference?: { scopeId: string; runId: string; inherited: boolean }
}
export const analysisReferenceId = (runId: string, nodeId: string) => `analysis-ref:${runId}:${nodeId}`
export const logReferenceId = (runId: string, logId: string) => `log-ref:${runId}:${logId}`
export const viewReferenceId = (runId: string, viewId: string) => `view-ref:${runId}:${viewId}`
export const baseReferenceId = (scopeId: string, runId: string) => `base-ref:${scopeId}:${runId}`
export const experimentEntityId = (id: string) => `experiment:${id}`
export const experimentRunReferenceId = (runId: string, id: string) => `experiment-ref:${runId}:${id}`
export function experimentTreeNodes(experiments: Experiment[], runIds: Set<string>): CatalogTreeNode[] {
  return experiments.flatMap(experiment => [
    { id: experimentEntityId(experiment.id), parent_id: experiment.owner_category_id,
      name: `实验：${experiment.name}`, kind: 'run' as const, notes: experiment.notes,
      experimentReference: { experimentId: experiment.id, ownerId: experiment.owner_category_id, virtual: false } },
    ...experiment.member_ids.filter(id => runIds.has(id)).map(runId => ({
      id: experimentRunReferenceId(runId, experiment.id), parent_id: runId,
      name: `实验：${experiment.name}`, kind: 'run' as const, notes: '',
      experimentReference: { experimentId: experiment.id, ownerId: experiment.owner_category_id, virtual: true, runId },
    })),
  ])
}
