import type { Change } from './api/baseImport'

export type ObjectType = 'base' | 'run'
export interface EditorTarget { kind: ObjectType; id: string; transfer?: string }
export interface EditorSnapshot {
  revision: string
  dateBase?: string
  changes: Record<string, Change>
  view?: {
    stations: string[]; trains: string[]; hiddenTrains: string[]
    showTracks: boolean; showSeq: boolean
    selectedLine?: string; stationOrder?: 'original' | 'down' | 'up'; trainSort?: 'original' | 'arrival' | 'departure'; sortStation?: string
  }
}
interface Transfer { target: EditorTarget; snapshot: EditorSnapshot }
export const dockChannel = '.timetable.dock.v1'
const children = new Map<string, Window>()
const transferKey = (nonce: string) => `redaims.editor-transfer.${nonce}`
export const draftKey = (kind: ObjectType, id: string) => `redaims.editor.${kind}.${id}`

export function readRoute(hash = window.location.hash): (EditorTarget & { mode: 'timetable' | 'workspace' }) | null {
  const [mode, query = ''] = hash.replace(/^#/, '').split('?')
  const params = new URLSearchParams(query)
  const kind = params.get('kind'), id = params.get('id')
  if ((mode !== 'timetable' && mode !== 'workspace') || (kind !== 'base' && kind !== 'run') || !id) return null
  return { mode, kind, id, transfer: params.get('transfer') || undefined }
}
export function editorHash(mode: 'timetable' | 'workspace', target: EditorTarget) {
  const params = new URLSearchParams({ kind: target.kind, id: target.id })
  if (target.transfer) params.set('transfer', target.transfer)
  return `#${mode}?${params}`
}
export function writeTransfer(nonce: string, target: EditorTarget, snapshot: EditorSnapshot) {
  localStorage.setItem(transferKey(nonce), JSON.stringify({ target, snapshot }))
}
export function readTransfer(nonce: string, target: EditorTarget): EditorSnapshot | null {
  try {
    const item = JSON.parse(localStorage.getItem(transferKey(nonce)) || 'null') as Transfer | null
    return item?.target.kind === target.kind && item.target.id === target.id && item.snapshot?.changes ? item.snapshot : null
  } catch { return null }
}
export function launchEditor(target: EditorTarget, snapshot: EditorSnapshot) {
  const nonce = crypto.randomUUID()
  writeTransfer(nonce, target, snapshot)
  const url = new URL(window.location.href)
  url.hash = editorHash('timetable', { ...target, transfer: nonce })
  const child = window.open(url.href, '_blank')
  if (!child) { localStorage.removeItem(transferKey(nonce)); throw new Error('浏览器未打开编辑标签页，请允许本网站打开新标签页后重试。') }
  children.set(nonce, child)
  return { nonce, child }
}
export function forgetTransfer(nonce: string) {
  children.delete(nonce)
  try { localStorage.removeItem(transferKey(nonce)) } catch { /* a retained draft is harmless */ }
}
// Main-window docking accepts only a same-origin request matching its stored transfer.
export function receiveDock(event: MessageEvent): EditorTarget | null {
  const message = event.data
  if (event.origin !== window.location.origin || !event.source || message?.channel !== dockChannel || message.action !== 'dock') return null
  const target = message.target as EditorTarget | undefined
  if (!target || (target.kind !== 'base' && target.kind !== 'run') || typeof target.id !== 'string' || !target.transfer) return null
  const child = children.get(target.transfer)
  if (child && event.source !== child) return null
  const snapshot = readTransfer(target.transfer, target)
  if (!snapshot) return null
  sessionStorage.setItem(draftKey(target.kind, target.id), JSON.stringify(snapshot))
  return target
}
