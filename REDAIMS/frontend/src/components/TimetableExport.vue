<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { request } from '../api/baseImport'
import { chooseDestination, chooseOriginal, digest, downloadWorkbook, filePickers, renderWorkbook, writeWorkbook, type ExportOptions, type WorkbookHandle } from '../api/workbookExport'
const props = defineProps<{ url: string; revision: string; objectType: 'base' | 'run' }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null), options = ref<ExportOptions | null>(null)
const selected = ref<string[]>([]), mode = ref('new'), filename = ref(''), source = ref<File | null>(null)
const busy = ref(false), error = ref(''), status = ref('')
const nativeOverwrite = typeof filePickers().showOpenFilePicker === 'function'
const canExport = computed(() => options.value && selected.value.length && !busy.value && (mode.value === 'replace' || (filename.value.trim().toLowerCase().endsWith('.xlsx') && !/[\\/:*?"<>|]/.test(filename.value))))
onMounted(async () => {
  await nextTick(); dialog.value?.showModal()
  try {
    const result = await request<ExportOptions>(`${props.url}/export-options`)
    if (result.revision !== props.revision) throw new Error('数据已变化，请关闭窗口并刷新编辑器后导出')
    options.value = result; selected.value = result.defaults; filename.value = result.filename
  } catch (e) { error.value = String(e) }
})
async function exportFile() {
  if (!options.value || !canExport.value) return
  // File pickers run directly from this click, before asynchronous rendering.
  busy.value = true; error.value = ''; status.value = ''
  try {
    let handle: WorkbookHandle | undefined, original: File | undefined, fingerprint: string | undefined
    if (mode.value === 'replace') {
      if (nativeOverwrite) {
        [handle] = await chooseOriginal()
        if (!handle) return
        original = await handle.getFile()
      } else original = source.value || undefined
      if (!original) throw new Error('请先选择要替换表单的源Excel文件')
      if (original.size > 32 * 1024 * 1024) throw new Error('源文件超过32 MB限制')
      const names = options.value.sheets.filter(s => selected.value.includes(s.key)).map(s => s.name).join('、')
      if (!confirm(`确认替换 ${original.name} 中的表单：${names}？其他表单保留。`)) return
      fingerprint = await digest(original)
    } else if (filePickers().showSaveFilePicker) handle = await chooseDestination(filename.value)
    const result = await renderWorkbook(props.url, options.value, selected.value, original)
    if (handle) { await writeWorkbook(handle, result, fingerprint); status.value = `已导出：${handle.name}` }
    else {
      downloadWorkbook(result, mode.value === 'replace' && original ? original.name : filename.value)
      status.value = mode.value === 'replace' ? '已下载合并后的文件，请手动替换原文件；浏览器未直接覆盖磁盘文件。' : '已生成下载文件；保存位置由浏览器下载设置选择。'
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') status.value = '已取消导出。'
    else error.value = String(e)
  } finally { busy.value = false }
}
</script>
<template><dialog ref="dialog" class="category-picker export-dialog" aria-labelledby="export-title" @cancel.prevent="!busy && emit('close')">
  <h2 id="export-title">导出 Excel</h2>
  <p>导出已保存的完整数据；车站和列车显示筛选不限制导出范围。</p>
  <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
  <fieldset :disabled="busy" class="import-fields"><legend>选择要导出的表单</legend>
    <label v-for="sheet in options?.sheets" :key="sheet.key" class="confirmation"><input v-model="selected" type="checkbox" :value="sheet.key" />{{ sheet.name }} · {{ sheet.label }}（{{ sheet.rows }} 行）</label>
    <p class="muted">{{ objectType === 'base' ? '基本图默认导出时刻表及三张基础表。' : 'run默认仅导出时刻表；基础表可勾选，来自当前有效基本图。' }}</p>
    <strong>是否覆盖原有Excel文件中的所选表单？</strong>
    <label class="confirmation"><input v-model="mode" type="radio" value="new" />否，另存为新的Excel文件</label>
    <label class="confirmation"><input v-model="mode" type="radio" value="replace" />是，选择源文件并替换其中的同名表单</label>
    <label v-if="mode === 'new'">新文件名<input v-model="filename" maxlength="180" /></label>
    <p v-if="mode === 'replace'" class="muted">上传时未保存原磁盘路径，请重新选中源文件。仅替换勾选的同名表单，保留未选表单、公式及工作簿其他内容。</p>
    <template v-if="mode === 'replace' && !nativeOverwrite"><p>当前浏览器不支持直接写回原文件。选择源文件后将下载合并结果，由您手动替换。</p><label>源Excel文件<input type="file" accept=".xlsx" @change="source = ($event.target as HTMLInputElement).files?.[0] || null" /></label></template>
  </fieldset>
  <div class="editor-actions"><button :disabled="!canExport" @click="exportFile">{{ busy ? '正在导出…' : mode === 'replace' ? '选择源文件并导出' : '选择保存位置并导出' }}</button><button :disabled="busy" @click="emit('close')">关闭</button></div>
</dialog></template>
