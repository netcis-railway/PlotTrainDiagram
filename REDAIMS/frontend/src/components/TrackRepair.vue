<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { post, request, type Change } from '../api/baseImport'
import { initialRepairRows, repairSelections, repairLineState, setRepairLine, type RepairContext, type RepairRow, type RepairResult, type RepairIssue } from '../api/trackRepair'
const props = defineProps<{ objectType?: 'base' | 'run'; objectId?: string; revision?: string; changes?: Change[]; dateBase?: string; jobId?: string; filename?: string }>()
const emit = defineEmits<{ close: []; applied: [changes: Change[], warnings: RepairIssue[]]; repaired: [file: File, warnings: number] }>()
const dialog = ref<HTMLDialogElement | null>(null), context = ref<RepairContext | null>(null), rows = ref<RepairRow[]>([])
const busy = ref(false), error = ref(''), result = ref<RepairResult | null>(null), search = ref('')
const previousFocus = document.activeElement as HTMLElement | null
const url = props.jobId ? `/ingest/jobs/${props.jobId}/track-repair` : `/track-repair/${props.objectType}/${props.objectId}`
const draft = { revision: props.revision, changes: props.changes || [], date_base: props.dateBase || undefined }
const selections = computed(() => repairSelections(rows.value))
const valid = computed(() => selections.value.length > 0 && selections.value.every(train => train.lines.length > 0 && train.lines.every(line => line.directions.length > 0)))
const lineStates = computed(() => new Map((context.value?.lines || []).map(line => [line.line_ind, repairLineState(rows.value, line.line_ind)])))
function toggleLine(lineInd: number, checked: boolean) { setRepairLine(rows.value, lineInd, checked); result.value = null }
const shown = computed(() => rows.value.filter(row => row.train.train_course_id.toLowerCase().includes(search.value.toLowerCase())))
async function load() {
  busy.value = true
  try {
    context.value = props.jobId ? await request<RepairContext>(`${url}/context`) : await post<RepairContext>(`${url}/context`, draft)
    rows.value = initialRepairRows(context.value)
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function confirm() {
  if (!context.value || !valid.value) return
  busy.value = true; error.value = ''; result.value = null
  try {
    const payload = { ...(!props.jobId ? draft : {}), repair_token: context.value.repair_token, selections: selections.value }
    if (props.jobId) {
      const response = await fetch(`/api/v1${url}/apply`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      if (response.headers.get('content-type')?.includes('application/json')) {
        const value = await response.json()
        if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail))
        result.value = value
      } else {
        if (!response.ok) throw new Error(`修复失败 (${response.status})`)
        emit('repaired', new File([await response.blob()], props.filename || '修复后时刻表.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }), Number(response.headers.get('X-Repair-Warnings') || 0))
      }
    } else {
      result.value = await post<RepairResult>(`${url}/apply`, payload)
      if (result.value.can_apply) emit('applied', result.value.changes, result.value.warnings)
    }
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
onMounted(async () => { await nextTick(); dialog.value?.showModal(); await load(); dialog.value?.focus(); dialog.value?.scrollTo(0, 0) })
onUnmounted(() => previousFocus?.focus())
</script>
<template><dialog ref="dialog" class="track-repair-dialog" tabindex="-1" @cancel.prevent="!busy && emit('close')" aria-labelledby="track-repair-title">
  <h2 id="track-repair-title">修复股道信息</h2>
  <p>勾选列车、线路和方向，确认后重新分配所选列车的全部股道。缺少的 _G 列将自动补入。</p>
  <details class="repair-help"><summary>默认选择与分配规则（奇数下行 DB，偶数上行 UB）</summary>
  <p class="muted">默认选中缺列或空股道列车；线路按途经车站的所属线路选中。车次取第一个“/”之前的编号，奇数选下行 DB，偶数选上行 UB；无法识别时请手动勾选。可同时选择多个线路或方向。取消线路表头勾选会清除整列全部选择（含隐藏列车）；重新勾选会为全部列车启用该线路，并恢复各车默认方向。</p>
  <p class="muted">同站同股道的占用不重叠；到发相同时或仅有一个时刻时按 1 秒占用。停止列车优先到发线，通过列车优先正线。未选列车的已填股道保持固定并参与避让；未选列车若缺少股道，将提示其占用尚不能核查。</p></details>
  <p v-if="jobId" class="category-context">修复成功后自动重新预检，仍需确认导入。原 Excel 文件不变。</p><p v-else class="category-context">修复成功后写入当前编辑草稿，请校验并保存。</p>
  <p v-if="busy" role="status">正在处理…</p><p v-if="error" class="error" role="alert">{{ error }}</p>
  <template v-if="context"><fieldset :disabled="busy">
    <div class="repair-tools"><label>查找列车<input v-model="search" placeholder="输入车次" /></label><button @click="rows.forEach(row => row.selected = true)">全选列车</button><button @click="rows.forEach(row => row.selected = false)">清空选择</button><span>已选 {{ selections.length }} / {{ rows.length }} 列车</span></div>
    <div class="table-wrap repair-matrix"><table aria-label="股道修复列车线路方向选择"><thead><tr><th>列车</th><th v-for="line in context.lines" :key="line.line_ind"><label class="confirmation" title="取消时清空整列线路、UB、DB；勾选时为全部列车启用线路并恢复默认方向"><input type="checkbox" :checked="lineStates.get(line.line_ind)?.checked || false" :indeterminate="lineStates.get(line.line_ind)?.indeterminate || false" :aria-label="`全部列车 线路 ${line.line_ind}`" @change="toggleLine(line.line_ind, ($event.target as HTMLInputElement).checked)" />线路 {{ line.line_ind }}</label><small>{{ line.line_name_chn }}</small></th></tr></thead><tbody>
      <tr v-for="row in shown" :key="row.train.id"><th><label class="confirmation"><input v-model="row.selected" type="checkbox" :aria-label="`修复列车 ${row.train.train_course_id}`" />{{ row.train.train_course_id }}</label><small>{{ row.train.missing_g ? '缺少 _G 列' : `空股道 ${row.train.empty_count} / ${row.train.visits}` }}</small></th>
        <td v-for="line in row.lines" :key="line.line_ind"><label class="confirmation"><input v-model="line.selected" type="checkbox" :aria-label="`${row.train.train_course_id} 线路 ${line.line_ind}`" />线路 {{ line.line_ind }}</label><div class="repair-directions"><label><input v-model="line.UB" type="checkbox" :aria-label="`${row.train.train_course_id} 线路 ${line.line_ind} UB`" />UB</label><label><input v-model="line.DB" type="checkbox" :aria-label="`${row.train.train_course_id} 线路 ${line.line_ind} DB`" />DB</label></div></td>
      </tr></tbody></table></div>
    <p v-if="!valid" class="muted">请选择至少一列车，并为每个所选列车勾选线路及 UB/DB。</p>
    <div v-if="result && !result.can_apply" class="validation-error" role="alert"><p>未应用修复，请调整选择或时刻后重试。</p><ul><li v-for="(issue, i) in result.issues" :key="i">{{ issue.train_course_id }} · {{ issue.node_name_chn }}（{{ issue.node_name }}）：{{ issue.message }}</li></ul></div>
    <div v-if="result?.warnings.length" class="validation-warning"><p>需核对的未选列车：</p><ul><li v-for="(issue, i) in result.warnings" :key="i">{{ issue.train_course_id }} · {{ issue.node_name_chn }}：{{ issue.message }}</li></ul></div>
    <div class="editor-actions"><button :disabled="!valid" @click="confirm">确认</button><button @click="emit('close')">取消</button></div>
  </fieldset></template><button v-else :disabled="busy" @click="emit('close')">关闭</button>
</dialog></template>
