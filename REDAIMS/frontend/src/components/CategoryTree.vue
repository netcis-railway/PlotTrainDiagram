<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Kind } from '../api/client'
import type { CatalogTreeNode } from '../types/catalogTree'
const props = defineProps<{ nodes: CatalogTreeNode[]; selected: string; labels: Record<Kind, string>; path: (id: string) => string; contextMenu?: boolean }>()
const emit = defineEmits<{ select: [node: CatalogTreeNode]; contextmenu: [node: CatalogTreeNode, event: MouseEvent | KeyboardEvent] }>()
const storageKey = 'redams.catalog-collapsed'
function restore(): Set<string> {
  try {
    const ids: unknown = JSON.parse(localStorage.getItem(storageKey) || '[]')
    return new Set(Array.isArray(ids) ? ids.filter((id): id is string => typeof id === 'string') : [])
  } catch { return new Set() }
}
const collapsed = ref(restore())
const root = ref<HTMLElement | null>(null)
const children = computed(() => {
  const result = new Map<string | null, CatalogTreeNode[]>()
  for (const node of props.nodes) {
    const siblings = result.get(node.parent_id) || []
    siblings.push(node); result.set(node.parent_id, siblings)
  }
  return result
})
const rows = computed(() => {
  const result: { node: CatalogTreeNode; depth: number; expandable: boolean }[] = []
  const visited = new Set<string>()
  function visit(parent: string | null, depth: number) {
    for (const node of children.value.get(parent) || []) {
      if (visited.has(node.id)) continue
      visited.add(node.id)
      const expandable = !!children.value.get(node.id)?.length
      result.push({ node, depth, expandable })
      if (!collapsed.value.has(node.id)) visit(node.id, depth + 1)
    }
  }
  visit(null, 0)
  return result
})
function persist() {
  try { localStorage.setItem(storageKey, JSON.stringify([...collapsed.value])) } catch { /* in-memory fallback */ }
}
function toggle(id: string) {
  const next = new Set(collapsed.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  collapsed.value = next; persist()
}
function expandAll() { collapsed.value = new Set(); persist() }
function collapseAll() { collapsed.value = new Set(props.nodes.filter(n => children.value.has(n.id)).map(n => n.id)); persist() }
watch([() => props.selected, () => props.nodes.find(n => n.id === props.selected)?.parent_id], ([id]) => {
  // Reveal selections made by the parent dropdown or by creating a new category.
  const next = new Set(collapsed.value)
  const visited = new Set<string>()
  let parent = props.nodes.find(n => n.id === id)?.parent_id
  while (parent && !visited.has(parent)) {
    visited.add(parent); next.delete(parent)
    parent = props.nodes.find(n => n.id === parent)?.parent_id
  }
  collapsed.value = next; persist()
}, { immediate: true })
function analysisLetter(node: CatalogTreeNode) {
  if (node.logReference || node.analysisReference?.nodeType === 'solver-log') return 'S'
  if (node.analysisReference?.nodeType === 'delay') return 'D'
  if (node.viewReference || node.analysisReference?.nodeType === 'view') return 'V'
  return ''
}
function focusRow(index: number) { root.value?.querySelectorAll<HTMLElement>('[data-tree-row]')[index]?.focus() }
function contextmenu(node: CatalogTreeNode, event: MouseEvent | KeyboardEvent) {
  if (!props.contextMenu) return
  event.preventDefault(); (event.currentTarget as HTMLElement)?.focus(); emit('contextmenu', node, event)
}
function keydown(event: KeyboardEvent, index: number) {
  const row = rows.value[index]
  if (!row) return
  const { node, expandable } = row
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) { contextmenu(node, event); return }
  switch (event.key) {
    case 'ArrowDown': event.preventDefault(); focusRow(Math.min(index + 1, rows.value.length - 1)); break
    case 'ArrowUp': event.preventDefault(); focusRow(Math.max(index - 1, 0)); break
    case 'Home': event.preventDefault(); focusRow(0); break
    case 'End': event.preventDefault(); focusRow(rows.value.length - 1); break
    case 'ArrowRight':
      event.preventDefault()
      if (expandable) { if (collapsed.value.has(node.id)) toggle(node.id); else focusRow(index + 1) }
      break
    case 'ArrowLeft':
      event.preventDefault()
      if (expandable && !collapsed.value.has(node.id)) toggle(node.id)
      else { const parentIndex = rows.value.findIndex(r => r.node.id === node.parent_id); if (parentIndex >= 0) focusRow(parentIndex) }
      break
    case 'Enter': case ' ': event.preventDefault(); emit('select', node); break
  }
}
</script>
<template>
  <div class="tree-toolbar"><button type="button" :disabled="!nodes.length" @click="expandAll">全部展开</button><button type="button" :disabled="!nodes.length" @click="collapseAll">全部折叠</button></div>
  <div ref="root" class="category-tree" role="tree" aria-label="工作区分类">
    <div v-for="(row, index) in rows" :key="row.node.id" role="treeitem" data-tree-row tabindex="0"
      :aria-level="row.depth + 1" :aria-selected="selected === row.node.id" :aria-expanded="row.expandable ? !collapsed.has(row.node.id) : undefined"
      class="category-tree-row" :class="{ active: selected === row.node.id }" :style="{ paddingLeft: `${8 + row.depth * 16}px` }" :title="path(row.node.id)"
      @contextmenu="contextmenu(row.node, $event)" @click="emit('select', row.node)" @dblclick="row.expandable && toggle(row.node.id)" @keydown.self="keydown($event, index)">
      <button v-if="row.expandable" class="tree-chevron" type="button" tabindex="-1" :aria-label="`${collapsed.has(row.node.id) ? '展开' : '折叠'} ${row.node.name}`" @click.stop="toggle(row.node.id)" @dblclick.stop>
        <svg viewBox="0 0 16 16" aria-hidden="true" :class="{ expanded: !collapsed.has(row.node.id) }"><path d="m6 3 5 5-5 5" /></svg>
      </button><span v-else class="tree-chevron-placeholder" aria-hidden="true" />
      <svg v-if="row.node.kind === 'run' || row.node.baseReference || analysisLetter(row.node)" class="tree-diagram" :class="{ 'tree-base': !!row.node.baseReference, 'tree-analysis-view': analysisLetter(row.node) === 'V', 'tree-analysis-delay': analysisLetter(row.node) === 'D', 'tree-analysis-log': analysisLetter(row.node) === 'S' }" viewBox="0 0 20 18" aria-hidden="true">
        <template v-if="row.node.experimentReference">
          <rect x="3" y="1" width="14" height="16" />
          <text class="tree-document-letter" x="10" y="13.5" text-anchor="middle">E</text>
          <path v-if="row.node.experimentReference.virtual" d="M12 14h6m-2-2 2 2-2 2" />
        </template>
        <template v-else-if="row.node.baseReference">
          <rect x="3" y="1" width="14" height="16" />
          <text class="tree-document-letter" x="10" y="13.5" text-anchor="middle">B</text>
        </template>
        <template v-else-if="analysisLetter(row.node) === 'V'">
          <path d="M3 1h9l5 5v11H3Z M12 1v5h5" />
          <path d="M6 13l3-4 3 3 3-4" />
        </template>
        <template v-else-if="analysisLetter(row.node)">
          <path d="M3 1h9l5 5v11H3Z M12 1v5h5" />
          <text class="tree-document-letter" x="10" y="13.5" text-anchor="middle">{{ analysisLetter(row.node) }}</text>
        </template>
        <template v-else>
          <path d="M8 1h9v16H3V6Z M3 6h5V1" />
          <g class="tree-timetable-grid"><rect x="5" y="8" width="10" height="7.5" /><path d="M10 8v7.5 M5 10.5h10 M5 13h10" /></g>
        </template>
      </svg>
      <svg v-else class="tree-folder" viewBox="0 0 20 18" aria-hidden="true"><path v-if="row.expandable && !collapsed.has(row.node.id)" d="M2 6V3h6l2 2h7v2M2 7h17l-3 9H2Z" /><path v-else d="M2 3h6l2 2h8v11H2Z" /></svg>
      <span class="tree-name">{{ row.node.name }}</span><small class="tree-kind">{{ row.node.experimentReference ? (row.node.experimentReference.virtual ? '实验引用' : '实验实体') : row.node.logReference ? '求解日志' : row.node.analysisReference ? ({ view: '视图', 'solver-log': '求解日志', delay: '延误分析' })[row.node.analysisReference.nodeType] : row.node.viewReference ? '视图' : row.node.baseReference ? '基本图' : labels[row.node.kind] }}</small>
    </div>
  </div>
</template>
