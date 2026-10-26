<script setup lang="ts">
import TimetableEditor from './TimetableEditor.vue'
import type { CatalogNode } from '../api/client'
defineProps<{ runId: string; nodes: CatalogNode[] }>()
const emit = defineEmits<{ changed: [owner: string | null] }>()
</script>
<template><TimetableEditor object-type="run" :object-id="runId" :nodes="nodes" @changed="emit('changed', $event)" /></template>
