<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type { CatalogNode } from '../api/client'
import { formatPath } from '../api/baseImport'
import { experimentApi, type Experiment, type ExperimentRun } from '../api/experiments'
import RunAnalysis from './RunAnalysis.vue'

const props = defineProps<{ nodes: CatalogNode[]; experiments: Experiment[]; experimentId: string; initialOwnerId: string }>()
const emit = defineEmits<{ changed: [experiment: Experiment | null, sourceId: string, reveal: boolean]; select: [id: string]; openRun: [id: string]; logsChanged: [] }>()
const detail = ref<Experiment | null>(null), candidates = ref<ExperimentRun[]>([])
const name = ref(''), notes = ref(''), ownerId = ref('')
const selectedRuns = ref<string[]>([]), selectedBatches = ref<string[]>([]), removals = ref<string[]>([])
const search = ref(''), busy = ref(false), loading = ref(false), error = ref(''), status = ref(''), deleteConfirmed = ref(false)
const analysisExperiment = ref<Experiment | null>(null), analysisOpening = ref(false)
let generation = 0
const categories = computed(() => props.nodes.filter(n => n.kind !== 'run'))
function path(id: string) {
  const result: string[] = [], seen = new Set<string>()
  let node = props.nodes.find(n => n.id === id)
  while (node && !seen.has(node.id)) { seen.add(node.id); result.unshift(node.name); node = props.nodes.find(n => n.id === node?.parent_id) }
  return result.join(' → ')
}
const memberIds = computed(() => new Set(detail.value?.member_ids || []))
function unavailable(run: ExperimentRun) {
  if (run.unavailable_reason) return run.unavailable_reason
  if (detail.value?.status === 'invalid') return '请先移除不兼容成员，再加入run'
  if (detail.value?.base_tt_id && run.effective_base.base_tt_id !== detail.value.base_tt_id) return '实际基本图与实验成员不同'
  if (detail.value?.date_base && run.date_base !== detail.value.date_base) return '运行基准日与实验成员不同'
  return ''
}
const filteredRuns = computed(() => candidates.value.filter(run => !memberIds.value.has(run.id) && `${run.name} ${formatPath(run.classification_path)}`.toLowerCase().includes(search.value.toLowerCase())))
const batches = computed(() => categories.value.filter(n => n.kind === 'batch').map(node => {
  const runs = candidates.value.filter(r => r.batch_id === node.id && !memberIds.value.has(r.id))
  return { ...node, count: runs.length, reason: runs.map(unavailable).find(Boolean) || '' }
}))
function adopt(value: Experiment) {
  detail.value = value; name.value = value.name; notes.value = value.notes; ownerId.value = value.owner_category_id
  selectedRuns.value = []; selectedBatches.value = []; removals.value = []; deleteConfirmed.value = false
}
async function load() {
  const version = ++generation, id = props.experimentId
  loading.value = true; error.value = ''; status.value = ''; detail.value = null
  analysisExperiment.value = null; analysisOpening.value = false
  selectedRuns.value = []; selectedBatches.value = []; removals.value = []; deleteConfirmed.value = false
  name.value = ''; notes.value = ''; ownerId.value = props.initialOwnerId
  try {
    const [runs, experiment] = await Promise.all([experimentApi.runs(), id ? experimentApi.detail(id) : Promise.resolve(null)])
    if (version !== generation) return
    candidates.value = runs
    if (experiment) adopt(experiment)
  } catch (e) { if (version === generation) error.value = String(e) }
  finally { if (version === generation) loading.value = false }
}
watch(() => [props.experimentId, props.initialOwnerId], load, { immediate: true })
onUnmounted(() => { generation++ })
async function mutate(action: () => Promise<Experiment | null>, message: string) {
  if (busy.value || loading.value) return
  const version = generation, sourceId = props.experimentId
  busy.value = true; error.value = ''; status.value = ''
  try {
    const value = await action()
    // Always publish a successful write, even if the user has since navigated away.
    emit('changed', value, sourceId, version === generation)
    if (version === generation) { if (value) adopt(value); status.value = message }
  } catch (e) { if (version === generation) error.value = String(e) }
  finally { busy.value = false }
}
function save() {
  const id = props.experimentId, revision = detail.value?.revision
  const data = { name: name.value.trim(), owner_category_id: ownerId.value, notes: notes.value }
  if (!data.name || !data.owner_category_id || (id && !revision)) return
  return mutate(() => id ? experimentApi.update(id, { ...data, revision: revision! }) : experimentApi.create(data), id ? '实验修改已保存' : '实验已创建')
}
function add() {
  const value = detail.value
  if (!value || (!selectedRuns.value.length && !selectedBatches.value.length)) return
  const data = { revision: value.revision, run_ids: [...selectedRuns.value], batch_ids: [...selectedBatches.value] }
  return mutate(() => experimentApi.add(value.id, data), '所选成员已加入；后续新增run不会自动加入')
}
function remove() {
  const value = detail.value
  if (!value || !removals.value.length) return
  const data = { revision: value.revision, run_ids: [...removals.value] }
  return mutate(() => experimentApi.remove(value.id, data), '已移除成员，run保留在原分类下')
}
function deleteExperiment() {
  const value = detail.value
  if (!value || !deleteConfirmed.value) return
  return mutate(async () => { await experimentApi.delete(value.id, value.revision); return null }, '实验已删除，所有run均保留')
}
async function openAnalysis() {
  if (busy.value || loading.value || analysisOpening.value || !detail.value) return
  const version = generation, id = detail.value.id
  analysisOpening.value = true; error.value = ''
  try {
    const value = await experimentApi.detail(id)
    if (version !== generation) return
    if (value.status !== 'ready' || !value.members.length) { error.value = `实验尚不能分析：${value.issues.join('；') || '请先加入成员run'}`; return }
    analysisExperiment.value = value
    emit('changed', value, id, false)
  } catch (e) { if (version === generation) error.value = String(e) }
  finally { if (version === generation) analysisOpening.value = false }
}
</script>

<template>
  <div class="experiment-manager">
    <h2>Experiment 实验管理</h2>
    <div class="experiment-toolbar"><label>选择实验<select :value="experimentId" :disabled="busy" @change="emit('select', ($event.target as HTMLSelectElement).value)"><option value="">新建实验</option><option v-for="item in experiments" :key="item.id" :value="item.id">{{ item.name }} · {{ item.member_count }} 个run</option></select></label><button type="button" :disabled="busy || loading" @click="load">刷新实验与可选run</button></div>
    <p>实验实体存放在所选类别下；成员run下的实验条目是指向同一实体的虚拟入口。当前采用固定成员模式。</p>
    <p v-if="loading" role="status">正在读取实验…</p><p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
    <form v-if="!loading && (!experimentId || detail)" aria-label="编辑实验" @submit.prevent="save">
      <fieldset :disabled="busy"><label>实验名称<input v-model="name" required maxlength="200" /></label>
        <label>实体存放类别<select v-model="ownerId" required><option disabled value="">请选择类别</option><option v-for="node in categories" :key="node.id" :value="node.id">{{ path(node.id) }}</option></select></label>
        <label>实验备注<textarea v-model="notes" maxlength="20000" /></label><button :disabled="!name.trim() || !ownerId">{{ experimentId ? '保存实验修改' : '创建实验' }}</button>
      </fieldset>
    </form>
    <template v-if="detail && !loading">
      <div class="catalog-actions"><button type="button" :disabled="busy || analysisOpening || detail.status !== 'ready'" :title="detail.status === 'ready' ? '打开实验成员运行图、求解日志和延误预览' : '请先加入使用同一基本图和基准日的成员run'" @click="openAnalysis">{{ analysisOpening ? '正在打开…' : '实验数据分析' }}</button></div>
      <p><strong>实体完整路径：</strong>{{ formatPath(detail.classification_path) }} → 实验：{{ detail.name }}</p>
      <p><strong>成员状态：</strong>{{ ({empty:'暂无成员',ready:'基本图和基准日一致',invalid:'成员不可比较'})[detail.status] }} · {{ detail.member_count }} 个run</p>
      <p v-if="detail.base_tt_id">共同基本图：{{ detail.members[0]?.effective_base.baseTT_no }} · 基准日：{{ detail.date_base }}</p>
      <ul v-if="detail.issues.length" class="error"><li v-for="issue in detail.issues" :key="issue">{{ issue }}</li></ul>
      <section aria-label="实验成员"><h3>当前成员</h3><p v-if="!detail.members.length">从下方逐个选择run或整批加入。</p>
        <div v-else class="experiment-table"><table><thead><tr><th>移除选择</th><th>run</th><th>完整分类路径</th><th>实际基本图</th><th>基准日</th></tr></thead><tbody><tr v-for="run in detail.members" :key="run.id"><td><input v-model="removals" type="checkbox" :value="run.id" :disabled="busy" :aria-label="`选择移除 ${run.name}`" /></td><td><button type="button" :disabled="busy" @click="emit('openRun', run.id)">{{ run.name }} / run_{{ run.run_no }}</button></td><td>{{ formatPath(run.classification_path) }}</td><td>{{ run.effective_base.baseTT_no || '无' }}</td><td>{{ run.date_base || '无' }}<small v-if="run.unavailable_reason" class="error">{{ run.unavailable_reason }}</small></td></tr></tbody></table></div>
        <button type="button" :disabled="busy || !removals.length" @click="remove">移除所选成员</button>
      </section>
      <section aria-label="添加实验成员"><h3>跨类别选择run</h3><label>搜索名称或分类路径<input v-model="search" type="search" /></label>
        <div class="experiment-candidates"><label v-for="run in filteredRuns" :key="run.id" :title="unavailable(run)"><input v-model="selectedRuns" type="checkbox" :value="run.id" :disabled="busy || !!unavailable(run)" /><span>{{ run.name }} / run_{{ run.run_no }}<small>{{ formatPath(run.classification_path) }}</small><small>{{ run.effective_base.baseTT_no || '无基本图' }} · {{ run.date_base || '无基准日' }} <span v-if="unavailable(run)" class="error">{{ unavailable(run) }}</span></small></span></label><p v-if="!filteredRuns.length">没有符合搜索条件的待加入run。</p></div>
        <h3>整批加入</h3><p>加入提交时批次中的全部当前run；后续新增run需再次加入。任一成员不兼容时，整次加入失败。</p>
        <div class="experiment-candidates"><label v-for="batch in batches" :key="batch.id"><input v-model="selectedBatches" type="checkbox" :value="batch.id" :disabled="busy || !batch.count || !!batch.reason" /><span>{{ path(batch.id) }} · {{ batch.count }} 个待加入run<small v-if="batch.reason" class="error">{{ batch.reason }}</small></span></label></div>
        <button type="button" :disabled="busy || (!selectedRuns.length && !selectedBatches.length)" @click="add">加入所选run及批次</button>
      </section>
      <details><summary>删除实验</summary><p>删除实验实体及其虚拟入口，保留所有成员run及其时刻表。</p><label class="confirmation"><input v-model="deleteConfirmed" type="checkbox" :disabled="busy" />确认删除实验“{{ detail.name }}”</label><button type="button" class="danger" :disabled="busy || !deleteConfirmed" @click="deleteExperiment">删除实验</button></details>
    </template>
  </div>
  <RunAnalysis v-if="analysisExperiment" :key="analysisExperiment.id" :run-id="analysisExperiment.members[0]!.id" :experiment="analysisExperiment" @close="analysisExperiment = null" @logs-changed="emit('logsChanged')" />
</template>
