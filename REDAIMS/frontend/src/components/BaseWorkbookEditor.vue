<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { baseWorkbookApi, type WorkbookChange, type WorkbookPage, type WorkbookValidation } from '../api/baseWorkbook'
import type { ValidationIssue } from '../api/baseImport'
import { chooseDestination, downloadWorkbook, filePickers, writeWorkbook, type WorkbookHandle } from '../api/workbookExport'
const props = defineProps<{ baseId: string }>()
const emit = defineEmits<{ saved: [owner: string]; draftChanged: [dirty: boolean]; backupUpdated: [] }>()
const data = ref<WorkbookPage | null>(null), changes = ref<Record<string, WorkbookChange>>({}), revision = ref('')
const busy = ref(false), error = ref(''), status = ref(''), stale = ref(false)
const validation = ref<WorkbookValidation | null>(null), warningsConfirmed = ref(false), datesConfirmed = ref(false)
const dirty = computed(() => Object.keys(changes.value).length > 0)
const storageKey = computed(() => `redaims-base-workbook:${props.baseId}`)
const hasWarnings = computed(() => validation.value?.issues.some(i => i.severity === 'warning'))
const key = (sheet: string, row: number, column: number) => JSON.stringify([sheet, row, column])
const sourceColumn = (index: number) => (data.value?.column_offset || 0) + index + 1
let generation = 0, closed = false
function persist() {
  try {
    if (dirty.value) sessionStorage.setItem(storageKey.value, JSON.stringify({ revision: revision.value, changes: changes.value }))
    else sessionStorage.removeItem(storageKey.value)
  } catch { error.value = '浏览器无法暂存四表草稿，请在离开页面前保存修改。' }
}
function record(row: number, column: number, text: string, original: string) {
  if (!data.value || busy.value || stale.value) return
  const location = key(data.value.sheet, row, column)
  if (text === original) delete changes.value[location]
  else changes.value[location] = { sheet: data.value.sheet, row, column, value: text || null }
  validation.value = null; warningsConfirmed.value = false; datesConfirmed.value = false; status.value = ''
  persist()
}
function value(row: number, column: number, original: string) {
  const edit = data.value && changes.value[key(data.value.sheet, row, column)]
  return edit ? edit.value ?? '' : original
}
async function load(sheet = '', offset = 0, initial = false, columnOffset = 0) {
  const version = ++generation
  busy.value = true; error.value = ''
  try {
    const result = await baseWorkbookApi.read(props.baseId, sheet, offset, columnOffset)
    if (closed || version !== generation) return
    if (initial) {
      try {
        const draft = JSON.parse(sessionStorage.getItem(storageKey.value) || 'null')
        if (draft && typeof draft.revision === 'string' && draft.changes && typeof draft.changes === 'object') {
          changes.value = draft.changes; revision.value = draft.revision
        }
      } catch { error.value = '未能恢复四表草稿。' }
    }
    if (dirty.value && revision.value !== result.revision) {
      stale.value = true; error.value = '基本图已变化，旧版草稿仍保留；请核对后放弃旧稿并重新载入。'
      if (!data.value) data.value = result
      return
    }
    data.value = result; revision.value = result.revision; stale.value = false
  } catch (e) { if (!closed && version === generation) error.value = String(e) }
  finally { if (!closed && version === generation) busy.value = false }
}
function showIssue(issue: ValidationIssue) {
  if (!issue.sheet) return
  const match = issue.cell?.match(/^\$?([A-Z]+)\$?(\d+)/i)
  const column = match ? [...match[1].toUpperCase()].reduce((n, char) => n * 26 + char.charCodeAt(0) - 64, 0) : 1
  const row = issue.row || (match ? Number(match[2]) : 2)
  const rows = data.value?.limit || 25, columns = data.value?.column_limit || 40
  void load(issue.sheet, Math.floor(Math.max(0, row - 2) / rows) * rows, false, Math.floor((column - 1) / columns) * columns)
}
async function validate() {
  if (!dirty.value || busy.value || stale.value) return
  const version = generation
  busy.value = true; error.value = ''; validation.value = null
  try {
    const result = await baseWorkbookApi.validate(props.baseId, revision.value, Object.values(changes.value))
    if (!closed && version === generation) { validation.value = result; warningsConfirmed.value = false; datesConfirmed.value = false }
  } catch (e) { if (!closed && version === generation) error.value = String(e) }
  finally { if (!closed && version === generation) busy.value = false }
}
async function save() {
  if (!dirty.value || busy.value || stale.value) return
  if (!validation.value) await validate()
  if (closed || !validation.value?.can_save || (hasWarnings.value && !warningsConfirmed.value) || (validation.value.train_date_changes.length && !datesConfirmed.value)) return
  const version = generation
  busy.value = true; error.value = ''
  try {
    const result = await baseWorkbookApi.save(props.baseId, revision.value, Object.values(changes.value), validation.value.validation_token, warningsConfirmed.value, datesConfirmed.value)
    if (closed || version !== generation) return
    changes.value = {}; validation.value = null; persist(); emit('saved', result.owner_category_id)
    await load(data.value?.sheet || '', data.value?.offset || 0, false, data.value?.column_offset || 0)
    status.value = '四表已保存，数据库和受管Excel工作副本已同步更新。'
  } catch (e) { if (!closed && version === generation) { error.value = String(e); validation.value = null } }
  finally { if (!closed) busy.value = false }
}
async function discard() {
  if (dirty.value && !confirm('放弃四个工作表中全部未保存修改，并重新载入？')) return
  changes.value = {}; revision.value = ''; validation.value = null; stale.value = false; persist(); status.value = ''
  await load(data.value?.sheet || '', data.value?.offset || 0, false, data.value?.column_offset || 0)
}
async function exportFile() {
  if (!data.value || dirty.value || busy.value || stale.value) return
  const version = generation, id = props.baseId, current = revision.value
  const filename = `${data.value.name.replace(/[\\/:*?"<>|]/g, '_')}_${data.value.date_base}.xlsx`
  busy.value = true; error.value = ''; status.value = ''
  try {
    let handle: WorkbookHandle | undefined
    if (filePickers().showSaveFilePicker) handle = await chooseDestination(filename)
    if (closed || version !== generation) return
    const result = await baseWorkbookApi.export(id, current)
    if (closed || version !== generation) return
    const refreshed = await baseWorkbookApi.read(id, data.value.sheet, data.value.offset, data.value.column_offset)
    if (closed || version !== generation) return
    data.value = refreshed; revision.value = refreshed.revision
    emit('backupUpdated')
    if (handle) { await writeWorkbook(handle, result); if (!closed) status.value = `已导出：${handle.name}` }
    else { downloadWorkbook(result, filename); status.value = '已生成Excel下载文件，保存位置由浏览器下载设置选择。' }
  } catch (e) {
    if (!closed && version === generation) {
      if (e instanceof DOMException && e.name === 'AbortError') status.value = '已取消导出。'
      else error.value = String(e)
    }
  } finally { if (!closed && version === generation) busy.value = false }
}
watch(dirty, value => emit('draftChanged', value), { immediate: true })
watch(() => props.baseId, () => { data.value = null; changes.value = {}; revision.value = ''; validation.value = null; status.value = ''; void load('', 0, true) }, { immediate: true })
onUnmounted(() => { closed = true; generation++ })
</script>
<template>
  <section class="base-workbook-editor" aria-label="基本图四表原始数据编辑">
    <h3>基本图四表 · Excel格式预览与编辑</h3>
    <p>按原工作表的行列和表头查看当前已保存的数据。宽表按列分组加载，可用“前一组列”“后一组列”查看全部列；切换表单、行页或列组会保留草稿。时间可填写 YYYY/MM/DD hh:mm:ss 或累计 HH:mm:ss。</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
    <div class="editor-actions">
      <label v-if="data">工作表<select :value="data.sheet" :disabled="busy" @change="load(($event.target as HTMLSelectElement).value)"><option v-for="sheet in data.sheets" :key="sheet">{{ sheet }}</option></select></label>
      <button :disabled="!dirty || busy || stale" @click="validate">校验四表</button>
      <button :disabled="!dirty || busy || stale" @click="save">保存</button>
      <button :disabled="busy" @click="discard">{{ dirty ? '放弃本次修改' : '刷新数据' }}</button>
      <button :disabled="!data || dirty || busy || stale" @click="exportFile">导出基本图和线路数据</button>
      <span v-if="dirty">{{ Object.keys(changes).length }} 个单元格未保存</span>
    </div>
    <p v-if="busy" role="status">正在处理…</p>
    <div v-if="validation" class="workbook-validation">
      <p>{{ validation.can_save ? '四表校验通过' : '存在阻断错误，请修改后重新校验' }} · {{ validation.summary.nodes }} 个车站 / {{ validation.summary.trains }} 趟列车 / {{ validation.summary.events }} 条访问</p>
      <div class="validation-list"><button v-for="(issue,i) in validation.issues" :key="i" :class="issue.severity === 'error' ? 'validation-error' : 'validation-warning'" @click="showIssue(issue)">{{ issue.severity === 'error' ? '错误' : '警告' }} · {{ issue.sheet }} {{ issue.cell || issue.row }} / {{ issue.field }}：{{ issue.message }}</button></div>
      <label v-if="hasWarnings" class="confirmation"><input v-model="warningsConfirmed" type="checkbox" :disabled="busy" />已核对并接受四表校验警告</label>
      <template v-if="validation.train_date_changes.length"><p v-for="change in validation.train_date_changes" :key="change.train_course_id">{{ change.train_course_id }}：{{ change.before }} → {{ change.after }}</p><label class="confirmation"><input v-model="datesConfirmed" type="checkbox" :disabled="busy" />确认列车基准日变化</label></template>
    </div>
    <template v-if="data">
      <div v-if="data.total_columns > data.column_limit" class="editor-actions" aria-label="工作表列分页">
        <button :disabled="busy || data.column_offset === 0" @click="load(data.sheet,data.offset,false,Math.max(0,data.column_offset-data.column_limit))">前一组列</button>
        <span>{{ data.columns[0] }}–{{ data.columns[data.columns.length-1] }} 列（{{ data.column_offset+1 }}–{{ data.column_offset+data.columns.length }} / {{ data.total_columns }} 列）</span>
        <button :disabled="busy || data.column_offset+data.columns.length >= data.total_columns" @click="load(data.sheet,data.offset,false,data.column_offset+data.column_limit)">后一组列</button>
      </div>
      <div class="table-wrap workbook-table-wrap"><table class="workbook-table"><thead><tr><th>Excel行</th><th v-for="(header,i) in data.headers" :key="i"><span class="muted">{{ data.columns[i] }}</span><br />{{ header || '（空表头）' }}</th></tr></thead><tbody><tr v-for="row in data.rows" :key="row.row"><th>{{ row.row }}</th><td v-for="(cell,i) in row.cells" :key="sourceColumn(i)" :class="{ 'workbook-cell-changed': !!changes[key(data.sheet,row.row,sourceColumn(i))] }"><input :value="value(row.row,sourceColumn(i),cell.value)" :disabled="busy || stale || !cell.editable" :style="{ fontWeight: cell.bold ? 'bold' : undefined }" :aria-label="`${data.sheet} ${data.columns[i]}${row.row} ${data.headers[i]}`" :title="`${data.columns[i]}${row.row} · ${cell.number_format}`" @input="record(row.row,sourceColumn(i),($event.target as HTMLInputElement).value,cell.value)" /></td></tr></tbody></table></div>
      <div class="editor-actions"><button :disabled="busy || data.offset === 0" @click="load(data.sheet,Math.max(0,data.offset-data.limit),false,data.column_offset)">上一页</button><span>{{ data.total_rows ? data.offset+1 : 0 }}–{{ Math.min(data.offset+data.rows.length,data.total_rows) }} / {{ data.total_rows }} 行（不含表头）</span><button :disabled="busy || data.offset+data.rows.length >= data.total_rows" @click="load(data.sheet,data.offset+data.limit,false,data.column_offset)">下一页</button></div>
    </template>
  </section>
</template>
