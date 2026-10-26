<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import CategoryTree from './CategoryTree.vue'
import type { CatalogNode } from '../api/client'
import { labels } from '../api/baseImport'
const props = defineProps<{ nodes: CatalogNode[]; current: string | null; batchOnly?: boolean }>()
const emit = defineEmits<{ choose: [id: string]; close: [] }>()
const selected = ref(props.current || '')
const dialog = ref<HTMLDialogElement | null>(null)
const previousFocus = document.activeElement as HTMLElement | null
const categories = computed(() => props.nodes.filter(n => n.kind !== 'run'))
const allowed = computed(() => categories.value.some(n => n.id === selected.value && (!props.batchOnly || n.kind === 'batch')))
function path(id: string) { const parts: string[] = []; const seen = new Set<string>(); let node = categories.value.find(n => n.id === id); while (node && !seen.has(node.id)) { seen.add(node.id); parts.unshift(`${labels[node.kind]}：${node.name}`); node = categories.value.find(n => n.id === node?.parent_id) }; return parts.join(' → ') }
onMounted(async () => { await nextTick(); dialog.value?.showModal() })
onUnmounted(() => previousFocus?.focus())
</script>
<template><dialog ref="dialog" class="category-picker" @cancel.prevent="emit('close')" aria-labelledby="category-picker-title">
  <h2 id="category-picker-title">选择所属类别</h2><p>{{ batchOnly ? 'run 请选择目标批次，可展开浏览全部类别。' : '选择基本图实际存储的类别。' }}</p>
  <div class="picker-tree"><CategoryTree :nodes="categories" :selected="selected" :labels="labels" :path="path" @select="selected = $event.id" /></div>
  <p class="category-context">拟选择：{{ path(selected) || '尚未选择' }}</p>
  <div class="editor-actions"><button :disabled="!allowed" @click="emit('choose', selected)">选定类别</button><button @click="emit('close')">取消</button></div>
</dialog></template>
