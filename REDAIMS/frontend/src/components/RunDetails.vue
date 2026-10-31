<script setup lang="ts">
import { computed, ref } from 'vue'
import TimetableEditor from './TimetableEditor.vue'
import type { CatalogNode } from '../api/client'
import type { DiagramViewSummary } from '../api/diagram'
import type { AnalysisNodeSummary, RunMetadata } from '../api/analysis'
import type { TimetableActionRequest } from '../catalogActions'
defineProps<{ runId: string; nodes: CatalogNode[]; actionRequest?: TimetableActionRequest }>()
const emit = defineEmits<{ changed: [owner: string | null]; viewSaved: [view: DiagramViewSummary]; analysisSaved: [node: AnalysisNodeSummary]; runUpdated: [value: RunMetadata]; logsChanged: [] }>()
const editor = ref<InstanceType<typeof TimetableEditor> | null>(null)
defineExpose({canTimeShift:computed(()=>editor.value?.canTimeShift || false),openTimeShift:()=>editor.value?.openTimeShift()})
</script>
<template><TimetableEditor ref="editor" object-type="run" :object-id="runId" :nodes="nodes" :action-request="actionRequest" @analysis-saved="emit('analysisSaved', $event)" @logs-changed="emit('logsChanged')" @view-saved="emit('viewSaved', $event)" @changed="emit('changed', $event)" @run-updated="emit('runUpdated', $event)" /></template>
