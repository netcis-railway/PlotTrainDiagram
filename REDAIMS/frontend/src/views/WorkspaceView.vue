<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import ImportPreview from '../components/ImportPreview.vue'
import CatalogSplitter from '../components/CatalogSplitter.vue'
import BaseDiagramInfo from '../components/BaseDiagramInfo.vue'
import { baseReferenceId, type CatalogTreeNode } from '../types/catalogTree'
import CategoryTree from '../components/CategoryTree.vue'
import BaseImport from '../components/BaseImport.vue'
import LegacyBaseMigration from '../components/LegacyBaseMigration.vue'
import RunDetails from '../components/RunDetails.vue'
import RunImport from '../components/RunImport.vue'
import { baseApi, type BaseTimetable, type Resolution } from '../api/baseImport'
import DeleteCategory from '../components/DeleteCategory.vue'
import { deletionApi, type UngroupedRun } from '../api/client'
import { api, type CatalogNode, type Kind } from '../api/client'

const props = defineProps<{ view: 'catalog' | 'import' | 'run-import'; editorTarget?: import('../editorWindow').EditorTarget }>()
const editorKey = computed(() => props.editorTarget?.transfer || '')
const emit = defineEmits<{ openImport: []; openRunImport: []; showCatalog: [id: string] }>()
const bases = ref<BaseTimetable[]>([])
const resolution = ref<Resolution | null>(null)
const tabs = [
  { id: 'view', title: '查看编辑' }, { id: 'new', title: '新建' },
  { id: 'delete', title: '删除' }, { id: 'base', title: '基本图' },
] as const
type Tab = typeof tabs[number]['id']
const activeTab = ref<Tab>('view')
function restoreWidth() {
  try {
    const width = Number(localStorage.getItem('redams.catalog-width') || 280)
    return Number.isFinite(width) ? Math.max(180, Math.min(520, width)) : 280
  } catch { return 280 }
}
const sidebarWidth = ref(restoreWidth())
watch(sidebarWidth, width => {
  try { localStorage.setItem('redams.catalog-width', String(width)) } catch { /* in-memory fallback */ }
})
function tabKeydown(event: KeyboardEvent, index: number) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
  activeTab.value = tabs[next]!.id
  const target = event.currentTarget as HTMLElement
  target.parentElement?.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus()
}

type CreationKind = Kind | 'run'
const labels: Record<CreationKind, string> = { user: '研究员', network: '路网', scenario: '场景', case: '案例', algorithm: '算法', batch: '批次', run: 'run' }
const parents: Record<CreationKind, Kind | null> = { user: null, network: 'user', scenario: 'network', case: 'scenario', algorithm: 'case', batch: 'algorithm', run: 'batch' }
const nodes = ref<CatalogNode[]>([])
const ungrouped = ref<UngroupedRun[]>([])
const selected = ref('')
const kind = ref<CreationKind>('user')
const parentId = ref('')
const name = ref('')
const notes = ref('')
const draftNotes = ref('')
const status = ref('正在连接')
const error = ref('')
const busy = ref(false)
const current = computed(() => nodes.value.find(n => n.id === selected.value) || (ungrouped.value.some(r => r.id === selected.value) ? { id: selected.value, kind: 'run' as const, parent_id: null, name: ungrouped.value.find(r => r.id === selected.value)!.name, notes: '' } : undefined))
const currentBaseId = computed(() => resolution.value?.effective.base_tt_id || '')
const treeNodes = computed<CatalogTreeNode[]>(() => {
  const items: CatalogTreeNode[] = bases.value.map(base => ({
    id: baseReferenceId(base.owner_category_id, base.id), parent_id: base.owner_category_id,
    name: `基本图：${base.name}`, kind: 'run', notes: '',
    baseReference: { scopeId: base.owner_category_id, runId: base.id, inherited: false },
  }))
  return [...items, ...nodes.value]
})
const selectedTreeId = computed(() => activeTab.value === 'base' && resolution.value?.local_base?.base_tt_id
  ? baseReferenceId(selected.value, resolution.value.local_base.base_tt_id) : selected.value)
function treePath(id: string): string {
  const item = treeNodes.value.find(n => n.id === id)?.baseReference
  if (!item) return categoryPath(id)
  return `${categoryPath(item.scopeId)} → 基本图：${bases.value.find(b => b.id === item.runId)?.name || ''}`
}
function categoryPath(id: string): string {
  const parts: string[] = []
  const visited = new Set<string>()
  let node = nodes.value.find(item => item.id === id)
  while (node && !visited.has(node.id)) {
    visited.add(node.id)
    parts.unshift(`${labels[node.kind]}：${node.name}`)
    node = nodes.value.find(item => item.id === node?.parent_id)
  }
  return parts.join(' → ')
}
const currentPath = computed(() => current.value ? categoryPath(current.value.id) : '尚未选择分类')
const creationParentNodes = computed(() => {
  const chain: CatalogNode[] = []
  const visited = new Set<string>()
  let node = parents[kind.value] ? nodes.value.find(item => item.id === parentId.value) : undefined
  while (node && !visited.has(node.id)) {
    visited.add(node.id)
    chain.unshift(node)
    node = nodes.value.find(item => item.id === node?.parent_id)
  }
  return chain
})
const creationParentPath = computed(() => !parents[kind.value]
  ? '根目录（新建研究员）'
  : parentId.value ? categoryPath(parentId.value) : '请先选择上级分类')
const parentOptions = computed(() => nodes.value.filter(n => n.kind === parents[kind.value]))
let resolutionVersion = 0
async function refreshResolution() {
  const version = ++resolutionVersion
  resolution.value = null
  const node = current.value
  const id = node?.kind === 'run' ? node.parent_id : node?.id
  if (!id) return
  try {
    const value = await baseApi.resolution(id)
    if (version === resolutionVersion) {
      if (node?.kind === 'run') { value.local_base = null; if (value.effective.base_tt_id) value.effective.mode = 'inherited' }
      resolution.value = value
    }
  } catch (e) { if (version === resolutionVersion) error.value = String(e) }
}
watch(selected, refreshResolution)
async function refresh() {
  try {
    const [, catalog, ordinaryRuns, baseItems, ungroupedRuns] = await Promise.all([
      api.health(), api.catalog(), baseApi.runs(), baseApi.bases(), deletionApi.ungrouped(),
    ])
    nodes.value = [...catalog, ...ordinaryRuns.filter(r => r.batch_id).map(r => ({
      id: r.id, parent_id: r.batch_id, name: `${r.name} / run_${r.run_no}`, kind: 'run' as const, notes: '',
    }))]
    bases.value = baseItems; ungrouped.value = ungroupedRuns
    if (selected.value && !current.value) { selected.value = ''; parentId.value = ''; kind.value = 'user' }
    status.value = '服务已连接'; error.value = ''; await refreshResolution()
  } catch (e) { status.value = '连接失败'; error.value = String(e) }
}
async function afterRunImported(id: string) {
  await refresh()
  const run = nodes.value.find(node => node.id === id)
  if (run) select(run)
  activeTab.value = 'view'; status.value = 'run 导入成功，可查阅和编辑时刻表'
  emit('showCatalog', id)
}
async function afterDataChanged(owner: string | null) {
  const wasBase = activeTab.value === 'base'
  await refresh()
  if (wasBase && owner) { selected.value = owner; await refreshResolution() }
}
async function createNode() {
  if (kind.value === 'run') return
  busy.value = true; error.value = ''
  try {
    const node = await api.create({ kind: kind.value, parent_id: parents[kind.value] ? parentId.value : null, name: name.value, notes: notes.value })
    nodes.value.push(node); select(node); name.value = ''; notes.value = ''; activeTab.value = 'view'; await refreshResolution()
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
function setCurrent(node: CatalogNode) {
  selected.value = node.id
  draftNotes.value = node.notes
}
function select(entry: CatalogTreeNode) {
  const node = entry.baseReference ? nodes.value.find(n => n.id === entry.baseReference!.scopeId) : entry
  if (!node) return
  setCurrent(node)
  if (entry.baseReference) activeTab.value = 'base'

  const children: Record<CreationKind, CreationKind> = {
    user: 'network', network: 'scenario', scenario: 'case', case: 'algorithm',
    algorithm: 'batch', batch: 'run', run: 'run',
  }
  kind.value = children[node.kind]
  parentId.value = node.kind === 'run' ? node.parent_id || '' : node.id
}
function selectParent() {
  const parent = nodes.value.find(node => node.id === parentId.value)
  if (parent) setCurrent(parent)
}
function changeKind() {
  // Reuse the matching ancestor of the selected node, without changing creation type.
  let ancestor = current.value
  const expected = parents[kind.value]
  while (ancestor && ancestor.kind !== expected) {
    ancestor = nodes.value.find(node => node.id === ancestor?.parent_id)
  }
  parentId.value = ancestor?.id ?? ''
  if (ancestor) setCurrent(ancestor)
}
async function saveNotes() {
  if (!current.value) return
  busy.value = true; error.value = ''
  const targetId = current.value.id
  const value = draftNotes.value
  try {
    await api.notes(targetId, value)
    const target = nodes.value.find(node => node.id === targetId)
    if (target) target.notes = value
  }
  catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function afterDelete() { selected.value = ''; parentId.value = ''; kind.value = 'user'; activeTab.value = 'view'; await refresh() }
let targetVersion = 0
async function openRequestedEditor() {
  const version = ++targetVersion
  const target = props.editorTarget
  if (!target) return
  await refresh()
  if (version !== targetVersion) return
  if (target.kind === 'base') {
    const base = bases.value.find(b => b.id === target.id)
    if (!base) { error.value = '拟嵌回的基本图已不存在'; return }
    selected.value = base.owner_category_id
    activeTab.value = 'base'
    await refreshResolution()
  } else {
    if (!nodes.value.some(n => n.id === target.id && n.kind === 'run') && !ungrouped.value.some(r => r.id === target.id)) { error.value = '拟嵌回的 run 已不存在'; return }
    selected.value = target.id; activeTab.value = 'view'
  }
}
watch(() => props.editorTarget, openRequestedEditor)
onMounted(() => { if (props.editorTarget) void openRequestedEditor(); else void refresh() })
</script>

<template>
  <div class="workspace-status"><span>工作区</span><span role="status">{{ status }}</span></div>
  <main class="workspace" :class="{ 'import-workspace': view !== 'catalog' }" :style="{ '--catalog-width': `${sidebarWidth}px` }">
    <aside v-show="view === 'catalog'" id="catalog-navigation" class="category-sidebar">
      <div class="category-sidebar-heading"><h2>项目分类</h2><button @click="refresh" :disabled="busy">刷新</button></div>
      <p v-if="!nodes.length">尚无分类，请点击“新建”创建研究员。</p>
      <CategoryTree :nodes="treeNodes" :selected="selectedTreeId" :labels="labels" :path="treePath" @select="select" />
    </aside>
    <CatalogSplitter v-show="view === 'catalog'" v-model="sidebarWidth" />
    <section>
      <p v-if="error" role="alert" class="error">{{ error }}</p>
      <div v-if="view === 'catalog'" class="catalog-editor">
        <div class="catalog-tabs" role="tablist" aria-label="分类管理操作">
          <button v-for="(tab, index) in tabs" :id="`catalog-tab-${tab.id}`" :key="tab.id" type="button" role="tab"
            :aria-selected="activeTab === tab.id" :aria-controls="`catalog-panel-${tab.id}`" :tabindex="activeTab === tab.id ? 0 : -1"
            :class="{ active: activeTab === tab.id }" @click="activeTab = tab.id" @keydown="tabKeydown($event, index)">{{ tab.title }}</button>
        </div>
        <article v-if="activeTab === 'view'" id="catalog-panel-view" role="tabpanel" aria-labelledby="catalog-tab-view" tabindex="0">
          <template v-if="current">
            <h2>查看编辑：{{ labels[current.kind] }} {{ current.name }}</h2>
            <p class="category-context"><strong>完整分类路径：</strong>{{ currentPath }}</p>
            <form v-if="current.kind !== 'run'" @submit.prevent="saveNotes">
              <label>分类备注<textarea v-model="draftNotes" maxlength="20000" /></label><button :disabled="busy">保存备注</button>
            </form>
            <RunDetails v-if="current.kind === 'run'" :key="current.id + editorKey" :run-id="current.id" :nodes="nodes" @changed="afterDataChanged" />
            <div v-else class="category-context"><p>当前有效基本图：{{ resolution?.effective.name || '无' }} <span v-if="resolution?.effective.base_tt_id">（{{ resolution.effective.mode === 'physical' ? '本级存储' : '回溯上级' }}）</span></p><button @click="activeTab = 'base'">查看基本图</button> <button @click="emit('openImport')">在当前类别导入基本图</button> <button v-if="current.kind === 'batch'" @click="emit('openRunImport')">在当前批次导入 run</button></div>
          </template>
          <div v-else class="empty-state"><h2>查看编辑</h2><p>从左侧选择分类查看和编辑，或创建新的分类。</p><button @click="activeTab = 'new'">新建分类</button></div>
          <details class="ungrouped-runs"><summary>未分组 run（{{ ungrouped.length }}）</summary><p v-if="!ungrouped.length">暂无未分组 run。</p><ul><li v-for="run in ungrouped" :key="run.id">{{ run.name }} / {{ run.run_no }} · 原归属：{{ run.origin_path.map(n => n.name).join(' → ') }}</li></ul></details>
        </article>
      <article v-if="activeTab === 'new'" id="catalog-panel-new" role="tabpanel" aria-labelledby="catalog-tab-new" tabindex="0"><h2>新建分类：{{ labels[kind] }}</h2><p>按研究员 → 路网 → 场景 → 案例 → 算法 → 批次 → run 组织运行方案。当前新建级别：<strong>{{ labels[kind] }}</strong>。</p>
        <div class="category-context" aria-live="polite">
          <p><strong>当前选中分类路径：</strong>{{ currentPath }}</p>
          <p><strong>新分类归属路径：</strong>{{ creationParentPath }}</p>
        </div>
        <form @submit.prevent="createNode">
          <div v-if="parents[kind]" class="parent-selector">
            <label for="creation-parent">上级类别</label>
            <div v-if="creationParentNodes.length" class="parent-path-table-wrap">
              <table class="parent-path-table" aria-label="上级分类完整路径">
                <thead><tr><th v-for="node in creationParentNodes" :key="node.id" scope="col">{{ labels[node.kind] }}</th></tr></thead>
                <tbody><tr><td v-for="node in creationParentNodes" :key="node.id">{{ node.name }}</td></tr></tbody>
              </table>
            </div>
            <p v-else class="muted">请先选择上级分类</p>
            <select id="creation-parent" v-model="parentId" required @change="selectParent"><option disabled value="">请选择上级分类</option><option v-for="node in parentOptions" :key="node.id" :value="node.id">{{ node.name }}</option></select>
          </div>
          <label>新建类别 类型<select v-model="kind" @change="changeKind"><option v-for="(label, key) in labels" :key="key" :value="key">{{ label }}</option></select></label>
          <p v-if="kind === 'run'" class="muted" role="status">run 通过导入 Excel 时刻表创建，并归属上面选定的批次；基本图仍独立管理。</p>
          <button v-if="kind === 'run'" type="button" :disabled="!parentId" @click="emit('openRunImport')">导入 run 时刻表</button>
          <template v-if="kind !== 'run'"><label>名称<input v-model="name" required maxlength="200" /></label>
          <label>备注<textarea v-model="notes" maxlength="20000" /></label>
          <button :disabled="busy || !name.trim()">{{ busy ? '正在保存…' : '创建分类' }}</button></template>
        </form>
      </article>
        <article v-if="activeTab === 'delete'" id="catalog-panel-delete" role="tabpanel" aria-labelledby="catalog-tab-delete" tabindex="0">
          <DeleteCategory v-if="current && current.kind !== 'run'" :key="current.id" :node="current" :nodes="nodes" @deleted="afterDelete" />
          <template v-else><h2>删除分类</h2><p class="empty-state">{{ current?.kind === 'run' ? '当前选中的是 run。请选中所属批次或上级分类，再预览删除范围和 run 处理方式。' : '请从左侧选择要删除的分类。' }}</p></template>
        </article>
        <article v-if="activeTab === 'base'" id="catalog-panel-base" role="tabpanel" aria-labelledby="catalog-tab-base" tabindex="0">
          <BaseDiagramInfo v-if="current" :key="editorKey" :base-id="currentBaseId" :scope-path="currentPath" :resolution="resolution" :nodes="nodes" @changed="afterDataChanged" @imported="emit('openImport')" />
          <template v-else><h2>基本图</h2><p class="empty-state">请从左侧选择分类或基本图条目。</p></template>
        </article>
      </div>
      <LegacyBaseMigration v-if="view !== 'run-import'" :nodes="nodes" @migrated="refresh" />
      <RunImport v-if="view === 'run-import'" :nodes="nodes" :initial-batch-id="current?.kind === 'run' ? current.parent_id || '' : current?.kind === 'batch' ? current.id : ''" @imported="afterRunImported" />
      <div v-show="view === 'import'"><BaseImport :nodes="nodes" :initial-category-id="current?.kind === 'run' ? current.parent_id || '' : current?.id || ''" @imported="refresh" /><details><summary>独立的 Excel 结构预览</summary><ImportPreview /></details></div>
    </section>
  </main>
</template>
