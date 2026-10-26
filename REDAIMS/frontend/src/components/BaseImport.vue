<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { CatalogNode } from '../api/client'
import { baseApi, formatIssueNode, formatPath, labels, type ImportJob, type BaseTimetable, type ValidationIssue } from '../api/baseImport'
import CategoryPicker from './CategoryPicker.vue'
import TrackRepair from './TrackRepair.vue'
import SequenceRepair from './SequenceRepair.vue'
const repairOpen = ref(false), sequenceOpen = ref(false), repairStatus = ref('')
const props = defineProps<{ nodes: CatalogNode[]; initialCategoryId: string }>()
const emit = defineEmits<{ imported: [] }>()
const owner = ref(props.initialCategoryId), name = ref('基本图'), dateBase = ref('2026-01-01'), dateMode = ref<'rebase' | 'preserve'>('rebase'), sheet = ref('')
const file = ref<File | null>(null), job = ref<ImportJob | null>(null), jobs = ref<ImportJob[]>([]), saved = ref<BaseTimetable | null>(null)
const busy = ref(false), error = ref(''), picker = ref(false), activeSheet = ref(''), severity = ref('all')
const dateConfirmed = ref(false), trainsConfirmed = ref(false), warningsConfirmed = ref(false), confirmed = ref(false), replaceConfirmed = ref(false)
const category = computed(() => props.nodes.find(n => n.id === owner.value))
const table = computed(() => job.value?.report.previews.find(t => t.name === activeSheet.value))
const issues = computed(() => job.value?.report.issues.filter(i => severity.value === 'all' || i.severity === severity.value) || [])
const errors = computed(() => job.value?.report.issues.filter(i => i.severity === 'error').length || 0)
const canCommit = computed(() => job.value?.report.can_commit && confirmed.value && dateConfirmed.value && trainsConfirmed.value && (!job.value.report.replacement || replaceConfirmed.value) && (!job.value.report.issues.some(i => i.severity === 'warning') || warningsConfirmed.value))
function path(id: string) { const result: string[] = []; const seen = new Set<string>(); let n = props.nodes.find(n => n.id === id); while (n && !seen.has(n.id)) { seen.add(n.id); result.unshift(`${labels[n.kind]}：${n.name}`); n = props.nodes.find(item => item.id === n?.parent_id) }; return result.join(' → ') }
function reset() { dateConfirmed.value = false; trainsConfirmed.value = false; warningsConfirmed.value = false; confirmed.value = false; replaceConfirmed.value = false }
watch(() => props.initialCategoryId, id => { if (id) owner.value = id })
watch([owner, name, dateBase, dateMode, sheet, file], () => { job.value = null; saved.value = null; reset() }, { flush: 'sync' })
async function loadJobs() { try { jobs.value = await baseApi.jobs() } catch (e) { error.value = String(e) } }
async function inspect() {
  if (!file.value || !owner.value) return
  busy.value = true; error.value = ''; saved.value = null; job.value = null; reset()
  try { if (file.value.size > 32 * 1024 * 1024) throw new Error('文件超过32 MB限制'); const params = new URLSearchParams({ owner_category_id: owner.value, name: name.value, filename: file.value.name, date_base: dateBase.value, date_mode: dateMode.value }); if (sheet.value) params.set('sheet', sheet.value); job.value = await baseApi.preview(params, file.value); activeSheet.value = job.value.report.previews[0]?.name || '' }
  catch (e) { error.value = String(e) } finally { busy.value = false; await loadJobs() }
}
async function repaired(repairedFile: File, warnings: number) {
  repairOpen.value = false; sequenceOpen.value = false
  file.value = repairedFile
  repairStatus.value = `已使用修复后的 ${repairedFile.name} 重新预检。${warnings ? `有 ${warnings} 条未选列车股道缺失或无效，其占用尚不能核查。` : ''}`
  await inspect()
}
async function commit() {
  if (!job.value || !canCommit.value) return
  busy.value = true; error.value = ''
  try { saved.value = await baseApi.commit(job.value.job_id, { confirmed: true, preview_token: job.value.report.preview_token, date_confirmed: true, train_dates_confirmed: true, warnings_confirmed: warningsConfirmed.value, replace_confirmed: replaceConfirmed.value }); job.value = null; emit('imported') }
  catch (e) { error.value = String(e) } finally { busy.value = false; await loadJobs() }
}
async function resume(id: string) { busy.value = true; error.value = ''; reset(); try { const restored = await baseApi.job(id); const o = restored.report.options; if (!o) throw new Error('该任务没有可恢复预检'); owner.value = o.owner_category_id; name.value = o.name; dateBase.value = o.date_base; dateMode.value = o.date_mode; sheet.value = o.sheet || ''; job.value = restored; activeSheet.value = restored.report.previews[0]?.name || '' } catch (e) { error.value = String(e) } finally { busy.value = false } }
async function cancel(id: string) { busy.value = true; try { await baseApi.cancel(id); if (job.value?.job_id === id) job.value = null; await loadJobs() } catch (e) { error.value = String(e) } finally { busy.value = false } }
async function locate(issue: ValidationIssue) {
  if (!issue.sheet) return
  activeSheet.value = issue.sheet
  await nextTick()
  const row = issue.row || Number(issue.cell?.match(/\d+$/)?.[0])
  document.getElementById(`preview-row-${row}`)?.scrollIntoView({ block: 'center', inline: 'nearest' })
}
function cellIssue(row: number, column: number) {
  return job.value?.report.issues.find(issue => {
    if (issue.sheet !== activeSheet.value || issue.row !== row) return false
    const letters = issue.cell?.match(/^[A-Z]+/i)?.[0].toUpperCase()
    if (letters) return [...letters].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0) === column + 1
    return issue.field === table.value?.headers[column]
  })
}
onMounted(loadJobs)
</script>
<template><article><h2>导入独立基本图</h2><p>选择实际存储类别 → 四表预检 → 确认保存并自动物理绑定。基本图使用独立 baseTT_no，不创建 run。</p>
  <p v-if="repairStatus" role="status">{{ repairStatus }}</p>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <form @submit.prevent="inspect"><fieldset :disabled="busy" class="import-fields">
    <div><strong>存储类别：</strong>{{ category ? `${labels[category.kind]} ${category.name}` : '尚未选择' }} <button type="button" @click="picker = true">选择存储类别</button><p class="category-context">{{ path(owner) }}</p></div>
    <label>基本图名称<input v-model="name" maxlength="200" required /></label><p class="muted">独立编号在首次保存时生成；覆盖或移动保留编号。仅本级已有物理图时需要覆盖确认。</p>
    <label>Excel 文件<input type="file" accept=".xlsx" @change="file = ($event.target as HTMLInputElement).files?.[0] || null" /></label>
    <div class="form-columns"><label>运行基准日<input v-model="dateBase" type="date" min="2020-01-01" required /></label><label>日期解释<select v-model="dateMode"><option value="rebase">源最早日期对齐基准日，保留日偏移</option><option value="preserve">保留现代源日期</option></select></label></div>
    <p class="muted">京沪样例使用 2025-05-25 并对齐源日期。DB_TRACKS/UB_TRACKS 可用 [10,11,12]（全部为到发线，无正线）或 [5,6,7]/6（6号兼作正线和到发线）。空单元格表示资料未知；按线路与车站分别校验。</p>
    <label>TTT 表选择（可空）<input v-model="sheet" placeholder="留空自动识别，或填写 Sheet 名" /></label><button :disabled="!owner || !file || !name.trim()">{{ busy ? '正在处理…' : '四表预检' }}</button>
  </fieldset></form>
  <CategoryPicker v-if="picker" :nodes="nodes" :current="owner" @close="picker = false" @choose="owner = $event; picker = false" />
  <SequenceRepair v-if="sequenceOpen && job" :job-id="job.job_id" :filename="job.filename" @close="sequenceOpen = false" @repaired="repaired" />
  <TrackRepair v-if="repairOpen && job" :job-id="job.job_id" :filename="job.filename" @close="repairOpen = false" @repaired="repaired" />
  <div v-if="job"><button :disabled="busy" @click="sequenceOpen = true">修复SEQ信息</button> <button :disabled="busy" @click="repairOpen = true">修复股道信息</button><h3>预检：{{ job.filename }}</h3><p>{{ job.report.summary }}</p><p v-if="errors" class="error">预检未通过：共 {{ errors }} 项阻断错误。请按具体问题修正后重新预检。</p>
    <div v-if="job.report.replacement" class="replacement-preview"><h3>将覆盖 {{ job.report.replacement.name }} 已存储的基本图</h3><p>{{ job.report.replacement.baseTT_no }} · {{ formatPath(job.report.replacement.classification_path) }}</p><p>原 {{ job.report.replacement.summary.events }} 条访问 → 新 {{ job.report.summary.events }} 条访问</p><label class="confirmation"><input v-model="replaceConfirmed" type="checkbox" :disabled="busy" />确认覆盖本级基本图的四表及受管副本；保留身份与位置，原 Excel 不变</label></div>
    <p v-else class="category-context">本级尚未存储基本图，正常导入后自动物理绑定。{{ job.report.effective_before.name ? `当前回溯图：${job.report.effective_before.name}，不会覆盖它。` : '' }} 下级自有基本图保持不变。</p>
    <details><summary>生效来源变化（{{ job.report.impact.length }} 个对象）</summary><ul><li v-for="r in job.report.impact" :key="r.kind + r.id">{{ r.name }}：{{ r.before.name || '无' }} → {{ r.after.name || '无' }}</li></ul></details>
    <label>问题筛选<select v-model="severity"><option value="all">全部</option><option value="error">阻断错误</option><option value="warning">警告</option></select></label><div class="validation-list"><button v-for="(issue,i) in issues" :key="i" :class="issue.severity === 'error' ? 'validation-error' : 'validation-warning'" @click="locate(issue)">{{ issue.severity === 'error' ? '错误' : '警告' }} · {{ issue.sheet || '导入设置' }} {{ issue.cell || issue.row || '' }} / {{ issue.field }}{{ formatIssueNode(issue) }}：{{ issue.message }}</button></div>
    <label>表格预览<select v-model="activeSheet"><option v-for="t in job.report.previews" :key="t.name">{{ t.name }}</option></select></label><div v-if="table" class="table-wrap"><table><thead><tr><th>源行</th><th v-for="(h,i) in table.headers" :key="i">{{ h }}</th></tr></thead><tbody><tr v-for="row in table.rows" :id="`preview-row-${row.row}`" :key="row.row"><th>{{ row.row }}</th><td v-for="(v,i) in row.values" :key="i" :class="cellIssue(row.row,i)?.severity === 'error' ? 'validation-error' : cellIssue(row.row,i) ? 'validation-warning' : ''" :title="cellIssue(row.row,i)?.message">{{ v ?? '—' }}</td></tr></tbody></table></div>
    <h3>列车实例基准日</h3><div class="table-wrap"><table><thead><tr><th>车次</th><th>基准日</th><th>采用 SEQ</th><th>核验</th></tr></thead><tbody><tr v-for="t in job.report.trains" :key="t.train_course_id"><td>{{ t.train_course_id }}</td><td>{{ t.train_base_date }}</td><td>{{ t.adopted_seq }}</td><td>{{ t.fallback ? '首条缺发车，需核验' : '首条发车日期' }}</td></tr></tbody></table></div>
    <label class="confirmation"><input v-model="dateConfirmed" type="checkbox" :disabled="busy" />已核对运行基准日及日期解释</label><label class="confirmation"><input v-model="trainsConfirmed" type="checkbox" :disabled="busy" />已核对列车实例基准日</label><label class="confirmation"><input v-model="warningsConfirmed" type="checkbox" :disabled="busy" />已阅读并接受警告</label><label class="confirmation"><input v-model="confirmed" type="checkbox" :disabled="busy" />确认存储类别及上述影响，保存基本图工作状态</label>
    <button :disabled="busy || !canCommit" @click="commit">{{ job.report.replacement ? '确认覆盖基本图' : '确认导入基本图' }}</button> <button :disabled="busy" @click="cancel(job.job_id)">取消并清理暂存</button>
  </div><div v-if="saved" role="status"><h3>导入成功：{{ saved.name }}</h3><p>{{ saved.baseTT_no }} · {{ formatPath(saved.classification_path) }}</p><p>已自动物理绑定，{{ saved.summary.events }} 条访问；未自动归档。</p></div>
</article><article><h2>最近独立基本图导入任务</h2><button :disabled="busy" @click="loadJobs">刷新</button><ul><li v-for="item in jobs" :key="item.job_id">{{ item.filename }} · {{ item.state }} {{ item.error }} <button v-if="item.state === 'preview'" :disabled="busy" @click="resume(item.job_id)">恢复预检</button> <button v-if="['preview','failed'].includes(item.state)" :disabled="busy" @click="cancel(item.job_id)">清理暂存</button></li></ul></article></template>
