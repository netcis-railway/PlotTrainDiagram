<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { analysisApi, type AnalysisSection, type AnalysisNodeSummary, type RunMetadata, type SolverLogSummary } from '../api/analysis'
import { diagramApi, type DiagramViewSummary } from '../api/diagram'
const props = defineProps<{ runId: string; section: AnalysisSection; targetId?: string; targetKind?: 'node' | 'view' | 'log'; initial?: string | null }>()
const emit = defineEmits<{ logUpdated: [value: SolverLogSummary]; runUpdated: [value: RunMetadata]; saved: [value: AnalysisNodeSummary]; viewUpdated: [value: DiagramViewSummary] }>()
const child = computed(() => !!props.targetId && !!props.targetKind)
const labels = { diagram: '运行图', log: '求解日志', delay: '延误预览' }
const inherited = ref(props.initial == null), local = ref(props.initial || ''), parent = ref('')
const busy = ref(false), loading = ref(false), ready = ref(false), error = ref(''), status = ref('')
const value = computed({ get: () => child.value && inherited.value ? parent.value : local.value, set: note => { local.value = note; status.value = '' } })
let generation = 0
async function load() {
  const version = ++generation
  loading.value = true; ready.value = false; error.value = ''
  try {
    const [metadata, logs] = await Promise.all([analysisApi.runMetadata(props.runId), props.targetKind === 'log' ? analysisApi.runLogs(props.runId) : Promise.resolve(null)])
    if (version !== generation) return
    if (logs) {
      const log = logs.find(item => item.id === props.targetId)
      if (!log) throw Error('求解日志不存在')
      const note = log.section_notes?.[props.section]
      inherited.value = note == null; local.value = note || ''
    }
    parent.value = metadata.analysis_notes[props.section] || ''
    if (!child.value) local.value = parent.value
    ready.value = true
  } catch (e) { if (version === generation) error.value = String(e) }
  finally { if (version === generation) loading.value = false }
}
function changeInheritance(event: Event) {
  const useParent = (event.target as HTMLInputElement).checked
  if (!useParent && inherited.value) local.value = parent.value
  inherited.value = useParent; status.value = ''
}
async function save() {
  if (busy.value || loading.value || !ready.value) return
  const version = generation, run = props.runId, section = props.section
  busy.value = true; error.value = ''; status.value = ''
  try {
    if (!child.value) {
      const result = await analysisApi.runSectionNote(run, section, local.value)
      if (version !== generation) return
      parent.value = result.analysis_notes[section] || ''; emit('runUpdated', result)
    } else {
      const note = inherited.value ? null : local.value
      if (props.targetKind === 'node') {
        const result = await analysisApi.nodeSectionNote(run, props.targetId!, section, note)
        if (version !== generation) return
        emit('saved', result)
      } else if (props.targetKind === 'log') {
        const result = await analysisApi.logSectionNote(run, props.targetId!, section, note)
        if (version !== generation) return
        emit('logUpdated', result)
      } else {
        const result = await diagramApi.viewSectionNote(run, props.targetId!, section, note)
        if (version !== generation) return
        emit('viewUpdated', result)
      }
    }
    status.value = '本小节备注已保存。'
  } catch (e) { if (version === generation) error.value = String(e) }
  finally { if (version === generation) busy.value = false }
}
watch(() => [props.runId, props.targetKind, props.targetId, props.section], () => {
  inherited.value = props.initial == null; local.value = props.initial || ''; busy.value = false; status.value = ''; void load()
}, { immediate: true })
onUnmounted(() => { generation++; ready.value = false })
</script>
<template>
  <form class="analysis-section-notes" :aria-label="labels[section] + '备注'" @submit.prevent="save">
    <label v-if="child" class="confirmation"><input type="checkbox" :checked="inherited" :disabled="busy || loading || !ready" @change="changeInheritance" />使用run的{{ labels[section] }}备注</label>
    <label>{{ labels[section] }}备注<textarea v-model="value" rows="2" maxlength="20000" :readonly="child && inherited" :disabled="busy || loading || !ready" /></label>
    <div class="catalog-actions"><span class="muted">{{ child ? (inherited ? '当前继承所属run的备注' : '本项目备注将覆盖run备注，允许留空') : '保存到run，供未设置自定义备注的子节点继承' }}</span><button :disabled="busy || loading || !ready">{{ busy ? '正在保存…' : '保存本小节备注' }}</button></div>
    <p v-if="error" class="error" role="alert">{{ error }} <button v-if="!ready" type="button" :disabled="loading" @click="load">重试</button></p>
    <p v-if="status" role="status">{{ status }}</p>
  </form>
</template>
