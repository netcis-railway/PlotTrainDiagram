import type { CatalogTreeNode } from './types/catalogTree'

export type CatalogActionId = 'import-base' | 'base-diagram' | 'import-run' | 'edit-base' | 'delete-base' | 'edit-run' | 'run-diagram' | 'import-log' | 'open-view' | 'open-analysis' | 'open-log' | 'delay-analysis'
export interface CatalogAction { id: CatalogActionId; label: string; disabled?: boolean; title?: string; danger?: boolean }
export interface TimetableActionRequest { sequence: number; kind: 'base' | 'run'; objectId: string; action: 'edit' | 'diagram' | 'delete' | 'delay' }

// Both entry points use this list, including the same availability rules.
export function catalogActions(node: CatalogTreeNode | undefined, hasBase: boolean): CatalogAction[] {
  if (!node) return []
  if (node.analysisReference) return [{ id: 'open-analysis', label: '查看保存分析' }]
  if (node.logReference) return [{ id: 'open-log', label: '查看求解日志' }]
  if (node.viewReference) return [{ id: 'open-view', label: '查看保存视图' }]
  if (node.baseReference) return [
    { id: 'edit-base', label: '编辑基本图(时刻表)' },
    { id: 'base-diagram', label: '查看基本图(运行图)' },
    { id: 'delete-base', label: '删除基本图', danger: true },
  ]
  if (node.kind === 'run') return [
    { id: 'edit-run', label: '编辑时刻表' },
    { id: 'run-diagram', label: '查看运行图' },
    { id: 'import-log', label: '导入求解日志' },
    { id: 'delay-analysis', label: '延误分析' },
  ]
  if (node.kind === 'batch') return [
    { id: 'import-base', label: '导入基本图' },
    { id: 'import-run', label: '导入时刻表' },
  ]
  return [
    { id: 'import-base', label: '导入基本图' },
    { id: 'base-diagram', label: '查看基本图(运行图)', disabled: !hasBase, title: hasBase ? undefined : '当前类别尚无可用基本图，或正在读取基本图信息' },
  ]
}
