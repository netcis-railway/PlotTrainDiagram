<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { analysisApi, type RunMetadata } from '../api/analysis'
const props = defineProps<{ runId: string }>()
const emit = defineEmits<{ saved: [value: RunMetadata] }>()
const name = ref(''), notes = ref(''), loading = ref(false), busy = ref(false), error = ref(''), status = ref(''), ready = ref(false)
let generation = 0
async function load() {
  const version = ++generation, id = props.runId
  loading.value = true; ready.value = false; error.value = ''; status.value = ''
  try {
    const value = await analysisApi.runMetadata(id)
    if (version !== generation) return
    name.value = value.name; notes.value = value.notes; ready.value = true
  } catch (e) { if (version === generation) error.value = String(e) }
  finally { if (version === generation) loading.value = false }
}
async function save() {
  if (!ready.value || busy.value || loading.value || !name.value.trim()) return
  const version = generation, id = props.runId
  busy.value = true; error.value = ''; status.value = ''
  try {
    const value = await analysisApi.updateRun(id, { name: name.value.trim(), notes: notes.value })
    if (version !== generation) return
    name.value = value.name; notes.value = value.notes; status.value = 'run名称和备注已保存。'; emit('saved', value)
  } catch (e) { if (version === generation) error.value = String(e) }
  finally { if (version === generation) busy.value = false }
}
watch(() => props.runId, () => { busy.value = false; void load() }, { immediate: true })
onUnmounted(() => { generation++; ready.value = false })
</script>
<template>
  <form class="saved-item-metadata run-metadata" aria-label="编辑run基本信息" @submit.prevent="save">
    <label>run名称<input v-model="name" required maxlength="200" :disabled="loading || busy || !ready" /></label>
    <label>run备注<textarea v-model="notes" rows="2" maxlength="20000" :disabled="loading || busy || !ready" /></label>
    <button :disabled="loading || busy || !ready || !name.trim()">{{ busy ? '正在保存…' : '保存run基本信息' }}</button>
    <p v-if="loading" role="status">正在读取run基本信息…</p>
    <p v-if="error" class="error" role="alert">{{ error }} <button v-if="!ready" type="button" :disabled="loading" @click="load">重试</button></p>
    <p v-if="status" role="status">{{ status }}</p>
  </form>
</template>
