<script setup lang="ts">
import { ref } from 'vue'
interface SheetPreview { name: string; rows: number; trains: string[]; headers: string[]; issues: { cell: string; message: string }[]; preview: (string | null)[][] }
interface Inspection { message: string; sheets: SheetPreview[]; available_sheets: string[]; requires_sheet_selection: boolean }
const file = ref<File | null>(null)
const result = ref<Inspection | null>(null)
const sheet = ref('')
const error = ref('')
const busy = ref(false)
function choose(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  result.value = null; error.value = ''; sheet.value = ''
}
async function inspect() {
  if (!file.value) return
  busy.value = true; error.value = ''; result.value = null
  try {
    if (file.value.size > 32 * 1024 * 1024) throw new Error('文件超过 32 MB 限制')
    const suffix = sheet.value ? `?sheet=${encodeURIComponent(sheet.value)}` : ''
    const response = await fetch(`/api/v1/ingest/inspect${suffix}`, { method: 'POST', body: file.value })
    const body = await response.json()
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '预览失败')
    result.value = body
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
</script>
<template>
  <article><h2>Excel 结构预览</h2><p>选择本地 XLSX，查看 TTT 表头、车次四列组和前 20 行。此步骤不会写入运行数据。</p>
    <form @submit.prevent="inspect">
      <label>Excel 文件<input type="file" accept=".xlsx" :disabled="busy" @change="choose" /></label>
      <label v-if="result">手动选择 Sheet<select v-model="sheet"><option value="">自动识别 TTT 表</option><option v-for="name in result.available_sheets" :key="name" :value="name">{{ name }}</option></select></label>
      <button :disabled="busy || !file">{{ busy ? '正在预览…' : '检查结构' }}</button>
    </form>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <template v-if="result"><p>{{ result.message }}</p><p v-if="result.requires_sheet_selection">未找到 TTT 表，请手动选择 Sheet 后重新检查。</p>
      <div v-for="entry in result.sheets" :key="entry.name"><h3>{{ entry.name }} · {{ entry.rows }} 行 · {{ entry.trains.length }} 趟列车</h3>
        <ul v-if="entry.issues.length"><li v-for="(issue, i) in entry.issues" :key="i" class="error">{{ issue.cell }}：{{ issue.message }}</li></ul>
        <p v-else>表头结构检查通过，尚需后续业务校验。</p>
        <div class="table-wrap"><table><thead><tr><th v-for="(header, i) in entry.headers" :key="i">{{ header }}</th></tr></thead><tbody><tr v-for="(row, i) in entry.preview" :key="i"><td v-for="(value, j) in row" :key="j">{{ value ?? '—' }}</td></tr></tbody></table></div>
      </div>
    </template>
  </article>
</template>
