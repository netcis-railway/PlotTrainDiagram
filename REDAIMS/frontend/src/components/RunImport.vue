<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import importDefaults from '../../import-defaults.json'
import type { CatalogNode } from '../api/client'
import { baseApi, formatIssueNode, request, formatPath, type OrdinaryRun, type ValidationIssue } from '../api/baseImport'
import { runImportApi, type RunImportJob, type RunJobSummary } from '../api/runImport'
import CategoryPicker from './CategoryPicker.vue'
import TrackRepair from './TrackRepair.vue'
import SequenceRepair from './SequenceRepair.vue'
const repairOpen = ref(false), sequenceOpen = ref(false), repairStatus = ref('')
const props = defineProps<{ nodes: CatalogNode[]; initialBatchId: string }>()
const emit = defineEmits<{ imported: [id: string] }>()
const batch = ref(props.initialBatchId), name = ref(''), runNo = ref('')
const mode = ref<'create' | 'replace'>('create'), target = ref('')
const dateBase = ref(importDefaults.runDateBase), dateMode = ref<'rebase' | 'preserve'>('rebase'), sheet = ref('')
const file = ref<File | null>(null), availableSheets = ref<string[]>([]), picker = ref(false)
const job = ref<RunImportJob | null>(null), jobs = ref<RunJobSummary[]>([]), runs = ref<OrdinaryRun[]>([])
const busy = ref(false), error = ref(''), activeSheet = ref(''), severity = ref('all')
const dateConfirmed = ref(false), trainsConfirmed = ref(false), warningsConfirmed = ref(false), confirmed = ref(false), replaceConfirmed = ref(false)
const batchName = computed(() => props.nodes.find(n => n.id === batch.value)?.name || '尚未选择批次')
const targets = computed(() => runs.value.filter(run => run.batch_id === batch.value))
const table = computed(() => job.value?.report.previews.find(t => t.name === activeSheet.value))
const issues = computed(() => job.value?.report.issues.filter(i => severity.value === 'all' || i.severity === severity.value) || [])
const errors = computed(() => job.value?.report.issues.filter(i => i.severity === 'error').length || 0)
const canCommit = computed(() => job.value?.report.can_commit && confirmed.value && dateConfirmed.value && trainsConfirmed.value && (!job.value.report.replacement || replaceConfirmed.value) && (!job.value.report.issues.some(i => i.severity === 'warning') || warningsConfirmed.value))
let formVersion = 0
function reset() { dateConfirmed.value = false; trainsConfirmed.value = false; warningsConfirmed.value = false; confirmed.value = false; replaceConfirmed.value = false }
function path(id: string) { const parts: string[] = [], seen = new Set<string>(); let node = props.nodes.find(n => n.id === id); while (node && !seen.has(node.id)) { seen.add(node.id); parts.unshift(node.name); node = props.nodes.find(n => n.id === node?.parent_id) }; return parts.join(' → ') }
watch(() => props.initialBatchId, id => { if (id) batch.value = id })
watch([batch, mode], () => { target.value = ''; runNo.value = '' }, { flush: 'sync' })
watch([batch, name, runNo, mode, target, dateBase, dateMode, sheet, file], () => { formVersion++; job.value = null; reset() }, { flush: 'sync' })
function chooseTarget() { const run = targets.value.find(r => r.id === target.value); if (run) { name.value = run.name; runNo.value = String(run.run_no) } }
async function loadJobs() { try { [jobs.value, runs.value] = await Promise.all([runImportApi.jobs(), baseApi.runs()]) } catch (e) { error.value = String(e) } }
async function chooseFile(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] || null; availableSheets.value = []; sheet.value = ''; error.value = ''
  if (!file.value) return
  if (!name.value && mode.value === 'create') name.value = file.value.name.replace(/\.xlsx$/i, '')
  busy.value = true
  try { if (file.value.size > 32 * 1024 * 1024) throw new Error('文件超过32 MB限制'); const result = await request<{ available_sheets: string[] }>('/ingest/inspect', { method: 'POST', body: file.value }); availableSheets.value = result.available_sheets }
  catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function inspect() {
  if (!file.value || !batch.value) return
  busy.value = true; error.value = ''; reset(); job.value = null
  const version = formVersion
  try {
    const params = new URLSearchParams({ batch_id: batch.value, name: name.value, filename: file.value.name, date_base: dateBase.value, date_mode: dateMode.value, write_mode: mode.value })
    if (runNo.value) params.set('run_no', runNo.value)
    if (sheet.value) params.set('sheet', sheet.value)
    if (mode.value === 'replace') params.set('target_run_id', target.value)
    const value = await runImportApi.preview(params, file.value)
    if (version === formVersion) { job.value = value; activeSheet.value = value.report.previews[0]?.name || ''; availableSheets.value = value.report.available_sheets }
  } catch (e) { error.value = String(e) } finally { busy.value = false; await loadJobs() }
}
async function repaired(repairedFile: File, warnings: number) {
  repairOpen.value = false; sequenceOpen.value = false
  file.value = repairedFile
  repairStatus.value = `已使用修复后的 ${repairedFile.name} 重新预检。${warnings ? `有 ${warnings} 条股道修复告警，请核对资料未知的访问、未修复股道及无法核查的占用。` : ''}`
  await inspect()
}
async function commit() {
  if (!job.value || !canCommit.value) return
  busy.value = true; error.value = ''
  try {
    const value = await runImportApi.commit(job.value.job_id, { confirmed: true, preview_token: job.value.report.preview_token, date_confirmed: true, train_dates_confirmed: true, warnings_confirmed: warningsConfirmed.value, replace_confirmed: replaceConfirmed.value })
    job.value = null; emit('imported', value.id)
  } catch (e) { error.value = String(e) } finally { busy.value = false; await loadJobs() }
}
async function resume(id: string) {
  busy.value = true; error.value = ''; reset()
  try {
    const restored = await runImportApi.job(id), options = restored.report.options
    if (!options) throw new Error('该任务没有可恢复预检')
    batch.value = options.batch_id; mode.value = options.write_mode; target.value = options.target_run_id || ''
    name.value = options.name; runNo.value = String(options.run_no); dateBase.value = options.date_base; dateMode.value = options.date_mode; sheet.value = options.sheet || ''
    availableSheets.value = restored.report.available_sheets; job.value = restored; activeSheet.value = restored.report.previews[0]?.name || ''
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function cancel(id: string) { busy.value = true; error.value = ''; try { await runImportApi.cancel(id); if (job.value?.job_id === id) job.value = null; await loadJobs() } catch (e) { error.value = String(e) } finally { busy.value = false } }
async function locate(issue: ValidationIssue) { if (!issue.sheet) return; activeSheet.value = issue.sheet; await nextTick(); document.getElementById(`run-preview-row-${issue.row}`)?.scrollIntoView({ block: 'center', inline: 'nearest' }) }
function cellIssue(row: number, column: number) {
  return job.value?.report.issues.find(issue => { if (issue.sheet !== activeSheet.value || issue.row !== row) return false; const letters = issue.cell?.match(/^[A-Z]+/i)?.[0].toUpperCase(); return letters ? [...letters].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0) === column + 1 : issue.field === table.value?.headers[column] })
}
onMounted(loadJobs)
</script>
<template><article><h2>导入普通 run 时刻表</h2><p>选择所属批次 → 上传时刻表 → 预检确认 → 查阅编辑。只导入 TTT，源文件中的基础数据表不参与导入。</p>
  <p v-if="repairStatus" role="status">{{ repairStatus }}</p>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <form @submit.prevent="inspect"><fieldset :disabled="busy" class="import-fields">
    <div><strong>所属批次：</strong>{{ batchName }} <button type="button" @click="picker = true">选择所属批次</button><p class="category-context">{{ path(batch) || '请选择批次' }}</p></div>
    <label>写入方式<select v-model="mode"><option value="create">新建 run</option><option value="replace">覆盖已有 run 时刻表</option></select></label>
    <label v-if="mode === 'replace'">覆盖目标<select v-model="target" required @change="chooseTarget"><option disabled value="">请选择当前批次中的 run</option><option v-for="run in targets" :key="run.id" :value="run.id">{{ run.name }} / run_{{ run.run_no }}</option></select></label>
    <div class="form-columns"><label>run 名称<input v-model="name" maxlength="200" :readonly="mode === 'replace'" required /></label><label>run 编号<input v-model="runNo" inputmode="numeric" pattern="0|[1-9][0-9]*" maxlength="10" :readonly="mode === 'replace'" :required="mode === 'replace'" placeholder="留空自动分配，从1开始" /></label></div>
    <label>run Excel 文件<input type="file" accept=".xlsx" @change="chooseFile" /></label>
    <label>时刻表表单<select v-model="sheet"><option value="">自动识别所有 TTT 表</option><option v-for="title in availableSheets" :key="title" :value="title">{{ title }}</option></select></label>
    <p class="muted">每个文件导入一个 run。可指定非 TTT 命名的表单，但表头仍须符合时刻表格式。同车跨表片段合并将另行提供。</p>
    <div class="form-columns"><label>run 运行基准日<input v-model="dateBase" type="date" min="2020-01-01" max="9999-12-31" required /></label><label>run 日期解释<select v-model="dateMode"><option value="rebase">源最早日期对齐基准日，保留日偏移</option><option value="preserve">保留现代源日期</option></select></label></div>
    <button :disabled="!batch || !file || !name.trim() || (mode === 'replace' && !target)">{{ busy ? '正在处理…' : 'run 时刻表预检' }}</button>
  </fieldset></form>
  <CategoryPicker v-if="picker" :nodes="nodes" :current="batch" batch-only @close="picker = false" @choose="batch = $event; picker = false" />
  <SequenceRepair v-if="sequenceOpen && job" :job-id="job.job_id" :filename="job.filename" @close="sequenceOpen = false" @repaired="repaired" />
  <TrackRepair v-if="repairOpen && job" :job-id="job.job_id" :filename="job.filename" @close="repairOpen = false" @repaired="repaired" />
  <div v-if="job"><button :disabled="busy" @click="sequenceOpen = true">修复SEQ信息</button> <button :disabled="busy" @click="repairOpen = true">修复股道信息</button><h3>run 预检：{{ job.filename }}</h3>
    <p>拟{{ job.report.replacement ? '覆盖' : '新建' }}：{{ job.report.options.name }} / run_{{ job.report.options.run_no }} · 基准日 {{ job.report.options.date_base }}</p>
    <p>{{ formatPath(job.report.classification_path) }}</p><p>车站 {{ job.report.summary.nodes }} · 列车 {{ job.report.summary.trains }} · 访问 {{ job.report.summary.events }}</p>
    <div class="category-context"><p>当前有效基本图：{{ job.report.effective_base.name || '无' }} <span v-if="job.report.effective_base.baseTT_no">（{{ job.report.effective_base.baseTT_no }}）</span></p><p>{{ formatPath(job.report.effective_base.owner_path || []) }}</p><p>run 按所属批次回溯使用基本图，导入不会复制或修改基本图。</p></div>
    <p v-if="errors" class="error">预检未通过：共 {{ errors }} 项阻断错误，请按问题位置修正后重新预检。</p>
    <div v-if="job.report.replacement" class="replacement-preview"><h3>将覆盖：{{ job.report.replacement.name }} / run_{{ job.report.replacement.run_no }}</h3><p>原 {{ job.report.replacement.summary.events }} 条访问 → 新 {{ job.report.summary.events }} 条访问。替换该 run 全部时刻表和受管源副本，包含此前已保存的编辑；保留 run 身份、名称、编号及所属批次。</p><label class="confirmation"><input v-model="replaceConfirmed" type="checkbox" :disabled="busy" />确认覆盖原 run 时刻表及已有编辑</label></div>
    <label>run 问题筛选<select v-model="severity"><option value="all">全部</option><option value="error">阻断错误</option><option value="warning">警告</option></select></label>
    <div class="validation-list"><button v-for="(issue,i) in issues" :key="i" :class="issue.severity === 'error' ? 'validation-error' : 'validation-warning'" @click="locate(issue)">{{ issue.severity === 'error' ? '错误' : '警告' }} · {{ issue.sheet || '导入设置' }} {{ issue.cell || issue.row || '' }} / {{ issue.field }}{{ formatIssueNode(issue) }}：{{ issue.message }}</button></div>
    <label>run 表格预览<select v-model="activeSheet"><option v-for="t in job.report.previews" :key="t.name" :value="t.name">{{ t.name }}</option></select></label>
    <div v-if="table" class="table-wrap run-preview-table" tabindex="0" role="region" aria-label="run 表格预览，源行和 NODE_NAME_CHN 固定"><table><thead><tr><th class="preview-source" scope="col">源行</th><th v-for="(h,i) in table.headers" :key="i" scope="col" :class="{ 'preview-station': String(h).trim().toUpperCase() === 'NODE_NAME_CHN' }">{{ h }}</th></tr></thead><tbody><tr v-for="row in table.rows" :id="`run-preview-row-${row.row}`" :key="row.row"><th class="preview-source" scope="row">{{ row.row }}</th><td v-for="(v,i) in row.values" :key="i" :class="[{ 'preview-station': String(table.headers[i]).trim().toUpperCase() === 'NODE_NAME_CHN' }, cellIssue(row.row,i)?.severity === 'error' ? 'validation-error' : cellIssue(row.row,i) ? 'validation-warning' : '']" :title="cellIssue(row.row,i)?.message">{{ v ?? '—' }}</td></tr></tbody></table></div>
    <h3>run 列车实例基准日</h3><div class="table-wrap"><table><thead><tr><th>车次</th><th>基准日</th><th>采用 SEQ</th><th>核验</th></tr></thead><tbody><tr v-for="t in job.report.trains" :key="t.train_course_id"><td>{{ t.train_course_id }}</td><td>{{ t.train_base_date }}</td><td>{{ t.adopted_seq }}</td><td>{{ t.fallback ? '首条缺发车，需核验' : '首条发车日期' }}</td></tr></tbody></table></div>
    <label class="confirmation"><input v-model="dateConfirmed" type="checkbox" :disabled="busy" />已核对 run 运行基准日及日期解释</label>
    <label class="confirmation"><input v-model="trainsConfirmed" type="checkbox" :disabled="busy" />已核对 run 列车实例基准日</label>
    <label class="confirmation"><input v-model="warningsConfirmed" type="checkbox" :disabled="busy" />已阅读并接受 run 预检警告</label>
    <label class="confirmation"><input v-model="confirmed" type="checkbox" :disabled="busy" />确认所属批次及导入内容，保存 run 工作状态</label>
    <button :disabled="busy || !canCommit" @click="commit">{{ job.report.replacement ? '确认覆盖 run' : '确认导入 run' }}</button> <button :disabled="busy" @click="cancel(job.job_id)">取消 run 预检并清理暂存</button>
  </div>
</article><article><h2>最近普通 run 导入任务</h2><button :disabled="busy" @click="loadJobs">刷新 run 任务</button><ul><li v-for="item in jobs" :key="item.job_id">{{ item.filename }} · {{ item.state }} {{ item.error }} <button v-if="item.state === 'preview'" :disabled="busy" @click="resume(item.job_id)">恢复 run 预检</button> <button v-if="['preview','failed'].includes(item.state)" :disabled="busy" @click="cancel(item.job_id)">清理 run 暂存</button></li></ul></article></template>
