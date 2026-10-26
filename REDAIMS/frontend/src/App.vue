<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { auth } from './api/auth'
import LoginView from './views/LoginView.vue'
import WorkspaceView from './views/WorkspaceView.vue'
import ThemeToggle from './components/ThemeToggle.vue'
import TimetableWindowView from './views/TimetableWindowView.vue'
import { dockChannel, editorHash, forgetTransfer, readRoute, receiveDock } from './editorWindow'
const session = ref(auth.restore())
const route = ref(readRoute())
function routeChanged() { route.value = readRoute(); if (route.value?.mode === 'workspace') view.value = 'catalog' }
function onDock(event: MessageEvent) {
  if (!session.value || route.value?.mode === 'timetable') return
  try {
    const target = receiveDock(event)
    if (!target) return
    window.location.hash = editorHash('workspace', target)
    routeChanged()
    window.focus()
    ;(event.source as Window).postMessage({ channel: dockChannel, action: 'docked', transfer: target.transfer }, window.location.origin)
    if (target.transfer) forgetTransfer(target.transfer)
  } catch (e) { error.value = `未能嵌回编辑器：${String(e)}` }
}
window.addEventListener('hashchange', routeChanged)
window.addEventListener('message', onDock)
onUnmounted(() => { window.removeEventListener('hashchange', routeChanged); window.removeEventListener('message', onDock) })
const busy = ref(false)
const error = ref('')
const collapsed = ref(false)
const view = ref<'catalog' | 'import' | 'run-import'>('catalog')
function showImportedRun(id: string) { view.value = 'catalog'; window.location.hash = editorHash('workspace', { kind: 'run', id }) }
async function login(name: string) {
  busy.value = true; error.value = ''
  try { session.value = await auth.login(name); view.value = 'catalog' }
  catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function logout() {
  busy.value = true; error.value = ''
  try { await auth.logout(); session.value = null; view.value = 'catalog'; collapsed.value = false }
  catch (e) { error.value = String(e) } finally { busy.value = false }
}
</script>
<template>
  <LoginView v-if="!session" :busy="busy" :error="error" @login="login" />
  <div v-else-if="route?.mode === 'timetable'" class="standalone-editor">
    <header class="app-header"><strong>REDAMS · 时刻表独立编辑</strong><div class="header-right"><ThemeToggle /><span class="user-name">{{ session.displayName }}</span><button class="header-button" :disabled="busy" @click="logout">退出登录</button></div></header>
    <TimetableWindowView :target="route" />
  </div>
  <div v-else class="app-shell" :class="{ collapsed }">
    <aside class="app-sidebar">
      <div class="sidebar-brand"><span class="brand-mark">R</span><span v-if="!collapsed">REDAMS<small>运行图分析系统</small></span></div>
      <nav aria-label="功能导航">
        <button :class="{ active: view === 'catalog' }" :aria-current="view === 'catalog' ? 'page' : undefined" title="分类管理" @click="view = 'catalog'"><span class="nav-icon" aria-hidden="true">▦</span><span v-if="!collapsed">分类管理</span></button>
        <button :class="{ active: view === 'import' }" :aria-current="view === 'import' ? 'page' : undefined" title="基本图导入 / 预览" @click="view = 'import'"><span class="nav-icon" aria-hidden="true">▤</span><span v-if="!collapsed">基本图导入 / 预览</span></button>
        <button :class="{ active: view === 'run-import' }" :aria-current="view === 'run-import' ? 'page' : undefined" title="run 导入 / 预检" @click="view = 'run-import'"><span class="nav-icon" aria-hidden="true">▥</span><span v-if="!collapsed">run 导入 / 预检</span></button>
      </nav>
      <div v-if="!collapsed" class="sidebar-footer">RAILWAY RESEARCH<br />工作区 · V0.1</div>
    </aside>
    <div class="app-body">
      <header class="app-header">
        <div class="header-left"><button class="header-button" :aria-expanded="!collapsed" :aria-label="collapsed ? '展开导航' : '折叠导航'" @click="collapsed = !collapsed">☰</button><span class="breadcrumb">工作区 / {{ view === 'catalog' ? '分类管理' : view === 'import' ? '基本图导入 / 预览' : 'run 导入 / 预检' }}</span></div>
        <div class="header-right"><ThemeToggle /><span class="user-name">{{ session.displayName }}</span><button class="header-button" :disabled="busy" @click="logout">退出登录</button></div>
      </header>
      <div class="app-content"><p v-if="error" role="alert" class="error">{{ error }}</p><WorkspaceView :view="view" :editor-target="route?.mode === 'workspace' ? route : undefined" @open-import="view = 'import'" @open-run-import="view = 'run-import'" @show-catalog="showImportedRun" /></div>
    </div>
  </div>
</template>
