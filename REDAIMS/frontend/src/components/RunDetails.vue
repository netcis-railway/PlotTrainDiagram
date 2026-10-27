<script setup lang="ts">
import TimetableEditor from './TimetableEditor.vue'
import type { CatalogNode } from '../api/client'
import type { DiagramViewSummary } from '../api/diagram'
import type { AnalysisNodeSummary } from '../api/analysis'
import type { TimetableActionRequest } from '../catalogActions'
defineProps<{ runId: string; nodes: CatalogNode[]; actionRequest?: TimetableActionRequest }>()
const emit = defineEmits<{ changed: [owner: string | null]; viewSaved: [view: DiagramViewSummary]; analysisSaved: [node: AnalysisNodeSummary]; logsChanged: [] }>()
</script>
<template><TimetableEditor object-type="run" :object-id="runId" :nodes="nodes" :action-request="actionRequest" @analysis-saved="emit('analysisSaved', $event)" @logs-changed="emit('logsChanged')" @view-saved="emit('viewSaved', $event)" @changed="emit('changed', $event)" /></template>
