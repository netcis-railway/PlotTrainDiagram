<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { post, request, type Change } from '../api/baseImport'
import { initialRepairRows, repairSelections, repairLineState, setRepairLine, setRepairDirection, setRepairLineDirection, setConflictRepairSelection, type RepairContext, type RepairRow, type RepairResult, type RepairIssue } from '../api/trackRepair'
const props = defineProps<{ objectType?: 'base' | 'run'; objectId?: string; revision?: string; changes?: Change[]; dateBase?: string; jobId?: string; filename?: string }>()
const emit = defineEmits<{ close: []; applied: [changes: Change[], warnings: RepairIssue[]]; repaired: [file: File, warnings: number] }>()
const dialog = ref<HTMLDialogElement | null>(null), context = ref<RepairContext | null>(null), rows = ref<RepairRow[]>([])
const busy = ref(false), error = ref(''), result = ref<RepairResult | null>(null), search = ref('')
const repairConflicts = ref(false)
const warnings = computed(() => result.value?.warnings || context.value?.warnings || [])
let cancelled = false, saving: AbortController | null = null
function changeConflictMode() { setConflictRepairSelection(rows.value, repairConflicts.value); result.value = null }
const previousFocus = document.activeElement as HTMLElement | null
const url = props.jobId ? `/ingest/jobs/${props.jobId}/track-repair` : `/track-repair/${props.objectType}/${props.objectId}`
const draft = { revision: props.revision, changes: props.changes || [], date_base: props.dateBase || undefined }
const selections = computed(() => repairSelections(rows.value))
const valid = computed(() => selections.value.length > 0 && selections.value.every(train => train.lines.length > 0 && train.lines.every(line => line.directions.length === 1)))
const lineStates = computed(() => new Map((context.value?.lines || []).map(line => [line.line_ind, repairLineState(rows.value, line.line_ind)])))
function toggleLine(lineInd: number, checked: boolean) { setRepairLine(rows.value, lineInd, checked); result.value = null }
function chooseLineDirection(lineInd: number, direction: 'UB' | 'DB') {
  setRepairLineDirection(rows.value, lineInd, direction); result.value = null
}
function chooseDirection(line: RepairRow['lines'][number], direction: 'UB' | 'DB') {
  setRepairDirection(line, direction); result.value = null
}
const shown = computed(() => rows.value.filter(row => row.train.train_course_id.toLowerCase().includes(search.value.toLowerCase())))
async function load() {
  busy.value = true
  try {
    context.value = props.jobId ? await request<RepairContext>(`${url}/context`) : await post<RepairContext>(`${url}/context`, draft)
    if (!cancelled) rows.value = initialRepairRows(context.value)
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function save() {
  if (!context.value || !valid.value || busy.value || cancelled) return
  busy.value = true; error.value = ''; result.value = null
  saving = new AbortController()
  try {
    const payload = { ...(!props.jobId ? draft : {}), repair_token: context.value.repair_token,
      selections: selections.value, repair_conflicts: repairConflicts.value }
    const response = await fetch('/api/v1' + url + '/apply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: saving.signal,
    })
    if (cancelled) return
    if (response.headers.get('content-type')?.includes('application/json')) {
      const value: RepairResult & { detail?: unknown } = await response.json()
      if (cancelled) return
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail))
      result.value = value
      if (!props.jobId && value.can_apply) emit('applied', value.changes, value.warnings)
    } else {
      if (!response.ok) throw new Error('修复失败 (' + response.status + ')')
      const file = new File([await response.blob()], props.filename || '修复后时刻表.xlsx',
        { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      if (!cancelled) emit('repaired', file, Number(response.headers.get('X-Repair-Warnings') || 0))
    }
  } catch (e) { if (!cancelled) error.value = String(e) }
  finally { busy.value = false; saving = null }
}
function cancel() { cancelled = true; saving?.abort(); emit('close') }
onMounted(async () => { await nextTick(); dialog.value?.showModal(); await load(); dialog.value?.focus(); dialog.value?.scrollTo(0, 0) })
onUnmounted(() => { cancelled = true; saving?.abort(); previousFocus?.focus() })
</script>
<template><dialog ref="dialog" class="track-repair-dialog" tabindex="-1" @cancel.prevent="cancel" aria-labelledby="track-repair-title">
  <h2 id="track-repair-title">修复股道信息</h2>
  <p>默认只补所选列车缺少股道的访问，已有股道保持不变并检查冲突。容量不足或资料未知时告警并保留原值。缺少的 _G 列将自动补入。</p>
  <details class="repair-help"><summary>默认选择与分配规则（奇数下行 DB，偶数上行 UB）</summary>
  <p class="muted">默认选中缺列或空股道列车；线路按途经车站的所属线路选中。车次取第一个“/”之前的编号，奇数选下行 DB，偶数选上行 UB；无法识别时请手动勾选。可同时选择多个线路；同一列车的同一线路下，UB/DB二选一，选中一个时另一个自动取消。取消线路表头勾选会清除整列全部选择（含隐藏列车）；重新勾选只会为途经该线路的列车启用线路，并恢复各车默认方向。线路名下的UB/DB可统一设置本线路所有途经列车的方向，包含搜索隐藏行；同车本线路各车站均按此方向修复。未途经线路的单元格灰显且不可选择。</p>
  <p class="muted">到发相同时或仅有一个时刻时按1秒占用。停站列车优先到发线，通过列车优先正线。已有分配默认只检查并告警；勾选冲突修复后，按本窗口列车从上到下的顺序保留第一个列车，依次尝试调整后续已选冲突列车。未选列车保持不变；容量不足时保留失败访问，其余可修复结果仍可保存。</p></details>
  <p v-if="jobId" class="category-context">修复成功后自动重新预检，仍需确认导入。原 Excel 文件不变。</p><p v-else class="category-context">修复成功后写入当前编辑草稿，请校验并保存。</p>
  <label class="confirmation"><input v-model="repairConflicts" type="checkbox" :disabled="busy" @change="changeConflictMode" />修复有冲突的股道分配</label><p class="muted">启用时自动选中涉及既有冲突的列车，也可手动调整；仅修改已选的后续冲突访问。取消会关闭本窗口，不应用任何结果。</p>
  <p v-if="busy" role="status">正在处理…</p><p v-if="error" class="error" role="alert">{{ error }}</p>
  <template v-if="context"><fieldset :disabled="busy">
    <div class="repair-tools"><label>查找列车<input v-model="search" placeholder="输入车次" /></label><button @click="rows.forEach(row => row.selected = true)">全选列车</button><button @click="rows.forEach(row => row.selected = false)">清空选择</button><span>已选 {{ selections.length }} / {{ rows.length }} 列车</span></div>
    <div class="table-wrap repair-matrix"><table aria-label="股道修复列车线路方向选择"><thead><tr><th>列车</th><th v-for="line in context.lines" :key="line.line_ind"><label class="confirmation" title="取消时清空整列线路、UB、DB；勾选时仅为途经列车启用线路并恢复默认方向"><input type="checkbox" :disabled="lineStates.get(line.line_ind)?.disabled" :checked="lineStates.get(line.line_ind)?.checked || false" :indeterminate="lineStates.get(line.line_ind)?.indeterminate || false" :aria-label="`全部列车 线路 ${line.line_ind}`" @change="toggleLine(line.line_ind, ($event.target as HTMLInputElement).checked)" />线路 {{ line.line_ind }}</label><small>{{ line.line_name_chn }}</small><div class="repair-directions repair-header-directions" :class="{ 'repair-line-unavailable': lineStates.get(line.line_ind)?.disabled }" role="group" :aria-label="`线路 ${line.line_ind} 统一方向`"><label v-for="direction in (['UB', 'DB'] as const)" :key="direction"><input type="radio" :name="`track-repair-header-${line.line_ind}`" :checked="lineStates.get(line.line_ind)?.direction === direction" :disabled="lineStates.get(line.line_ind)?.disabled" :aria-label="`全部途经列车 线路 ${line.line_ind} ${direction}`" @change="chooseLineDirection(line.line_ind, direction)" />{{ direction }}</label></div></th></tr></thead><tbody>
      <tr v-for="row in shown" :key="row.train.id"><th><label class="confirmation"><input v-model="row.selected" type="checkbox" :aria-label="`修复列车 ${row.train.train_course_id}`" />{{ row.train.train_course_id }}</label><small>{{ row.train.missing_g ? '缺少 _G 列' : `空股道 ${row.train.empty_count} / ${row.train.visits}` }}</small></th>
        <td v-for="line in row.lines" :key="line.line_ind" :class="{ 'repair-line-unavailable': !line.available }" :title="!line.available ? '该列车未经过此线路' : undefined" :aria-disabled="!line.available"><label class="confirmation"><input v-model="line.selected" type="checkbox" :disabled="!line.available" :aria-label="`${row.train.train_course_id} 线路 ${line.line_ind}`" />线路 {{ line.line_ind }}</label><div class="repair-directions"><label><input :checked="line.UB" type="radio" :disabled="!line.available" :name="`track-repair-${row.train.id}-${line.line_ind}`" @change="chooseDirection(line, 'UB')" :aria-label="`${row.train.train_course_id} 线路 ${line.line_ind} UB`" />UB</label><label><input :checked="line.DB" type="radio" :disabled="!line.available" :name="`track-repair-${row.train.id}-${line.line_ind}`" @change="chooseDirection(line, 'DB')" :aria-label="`${row.train.train_course_id} 线路 ${line.line_ind} DB`" />DB</label></div></td>
      </tr></tbody></table></div>
    <p v-if="!valid" class="muted">请选择至少一列车，并为每个所选列车勾选线路并选择一个方向（UB或DB）。</p>
    <div v-if="result && !result.can_apply" class="validation-error" role="alert"><p>未应用修复，请调整选择或时刻后重试。</p><ul><li v-for="(issue, i) in result.issues" :key="i">{{ issue.train_course_id }} · {{ issue.node_name_chn }}（{{ issue.node_name }}）：{{ issue.message }}</li></ul></div>
    <div v-if="warnings.length" class="validation-warning"><p>股道修复告警（{{ warnings.length }}条）：</p><ul><li v-for="(issue, i) in warnings" :key="i">{{ issue.train_course_id }} · {{ issue.node_name_chn }}：{{ issue.message }}</li></ul></div>
  </fieldset></template>
  <div class="editor-actions"><button type="button" :disabled="busy || !context || !valid" @click="save">保存</button><button type="button" @click="cancel">取消</button></div>
</dialog></template>
