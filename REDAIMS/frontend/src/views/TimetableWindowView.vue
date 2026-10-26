<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type CatalogNode } from '../api/client'
import type { EditorTarget } from '../editorWindow'
import TimetableEditor from '../components/TimetableEditor.vue'

defineProps<{ target: EditorTarget }>()
const nodes = ref<CatalogNode[]>([]), error = ref('')
async function refresh() {
  try { nodes.value = await api.catalog(); error.value = '' }
  catch (e) { error.value = String(e) }
}
onMounted(refresh)
</script>
<template><main class="standalone-content">
  <p v-if="error" role="alert" class="error">{{ error }} <button @click="refresh">重试加载类别</button></p>
  <TimetableEditor :key="target.kind + target.id + (target.transfer || '')" :object-type="target.kind" :object-id="target.id" :nodes="nodes" standalone :transfer="target.transfer" @changed="refresh" />
</main></template>
