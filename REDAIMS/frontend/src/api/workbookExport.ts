export interface ExportOptions {
  revision: string; filename: string; defaults: string[]
  sheets: { key: string; name: string; label: string; rows: number }[]
}
interface Writable { write(value: Blob): Promise<void>; close(): Promise<void>; abort?(): Promise<void> }
export interface WorkbookHandle { name: string; getFile(): Promise<File>; createWritable(): Promise<Writable> }
interface FilePickers {
  showOpenFilePicker?: (options: object) => Promise<WorkbookHandle[]>
  showSaveFilePicker?: (options: object) => Promise<WorkbookHandle>
}
export const filePickers = () => window as unknown as FilePickers
const types = [{ description: 'Excel 工作簿', accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] } }]
export function chooseOriginal() {
  return filePickers().showOpenFilePicker!({ types, multiple: false, excludeAcceptAllOption: true })
}
export function chooseDestination(filename: string) {
  return filePickers().showSaveFilePicker!({ types, suggestedName: filename, excludeAcceptAllOption: true })
}
export async function digest(file: File) {
  const value = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(value), b => b.toString(16).padStart(2, '0')).join('')
}
export async function renderWorkbook(url: string, options: ExportOptions, selected: string[], original?: File) {
  if (original && (original.size > 32 * 1024 * 1024 || !original.name.toLowerCase().endsWith('.xlsx'))) throw new Error('请选择不超过32 MB的XLSX文件')
  const params = new URLSearchParams({ revision: options.revision, sheets: selected.join(','), replace: String(!!original) })
  const response = await fetch(`/api/v1${url}/export?${params}`, { method: 'POST', body: original })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `导出失败（${response.status}）`)
  }
  return response.blob()
}
export async function writeWorkbook(handle: WorkbookHandle, data: Blob, originalDigest?: string) {
  if (originalDigest && await digest(await handle.getFile()) !== originalDigest) throw new Error('源文件在导出期间发生变化，请重新选择后导出')
  const writer = await handle.createWritable()
  try {
    if (originalDigest && await digest(await handle.getFile()) !== originalDigest) throw new Error('源文件在授权期间发生变化，请重新选择后导出')
    await writer.write(data); await writer.close()
  }
  catch (e) { try { await writer.abort?.() } catch { /* retain the original error */ }; throw e }
}
export function downloadWorkbook(data: Blob, filename: string) {
  const address = URL.createObjectURL(data), link = document.createElement('a')
  link.href = address; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(address), 30000)
}
