<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { CatalogNode } from '../api/client'
import { request, post, formatPath, type MovePreview, type ValidationIssue, type BaseTimetable } from '../api/baseImport'
import CategoryPicker from './CategoryPicker.vue'
const props = defineProps<{ nodes: CatalogNode[] }>()
const emit = defineEmits<{ migrated: [] }>()
interface Legacy { id: string; batch_id: string | null; name: string; run_no: number }
interface Migration { preview_token: string; can_migrate: boolean; target_path: MovePreview['target_path']; issues: ValidationIssue[]; original: { classification_path: MovePreview['source_path']; bindings: { scope_id: string; path: MovePreview['source_path'] }[] }; legacy_binding_changes: { scope_id: string; after: { mode: string; name?: string } }[] }
const items = ref<Legacy[]>([]), current = ref<Legacy | null>(null), target = ref(''), picker = ref(false), preview = ref<Migration | null>(null), confirmed = ref(false), busy = ref(false), error = ref(''), result = ref('')
async function load() { try { items.value = await request<Legacy[]>('/base-timetable-migrations') } catch (e) { error.value = String(e) } }
function choose(item: Legacy) { current.value = item; target.value = item.batch_id || ''; preview.value = null; picker.value = true; confirmed.value = false }
async function inspect(id: string) { picker.value = false; target.value = id; busy.value = true; error.value = ''; confirmed.value = false; try { preview.value = await post<Migration>(`/base-timetable-migrations/${current.value!.id}/preview`, { target_category_id: id }) } catch (e) { error.value = String(e) } finally { busy.value = false } }
async function commit() { if (!preview.value || !confirmed.value) return; busy.value = true; error.value = ''; try { const saved = await post<{ base: BaseTimetable; backup_path: string }>(`/base-timetable-migrations/${current.value!.id}/commit`, { target_category_id: target.value, preview_token: preview.value.preview_token, confirmed: true }); result.value = `${saved.base.name} 已迁移。回退备份：${saved.backup_path}`; preview.value = null; await load(); emit('migrated') } catch (e) { error.value = String(e) } finally { busy.value = false } }
onMounted(load)
</script>
<template><section v-if="items.length || result" class="legacy-migration"><h3>旧基本图迁移（{{ items.length }}）</h3><p>旧数据仍保留。请逐幅明确唯一实际存储类别；迁移前会备份数据库与受管来源，不自动照搬旧的任意绑定。</p><p v-if="error" class="error">{{ error }}</p><p v-if="result" role="status">{{ result }}</p><ul><li v-for="item in items" :key="item.id">{{ item.name }} / 旧 run_{{ item.run_no }} <button :disabled="busy" @click="choose(item)">选择存储类别并预览</button></li></ul>
  <CategoryPicker v-if="picker" :nodes="props.nodes" :current="target" @close="picker = false" @choose="inspect" />
  <div v-if="preview" class="category-context"><p>原存储：{{ formatPath(preview.original.classification_path) || '未分组' }}</p><p>拟存储：{{ formatPath(preview.target_path) }}</p><h4>旧直接绑定</h4><ul><li v-for="binding in preview.original.bindings" :key="binding.scope_id">{{ formatPath(binding.path) }}</li></ul><h4>转换后的来源</h4><ul><li v-for="entry in preview.legacy_binding_changes" :key="entry.scope_id">{{ entry.scope_id }}：{{ entry.after.name || '没有可回溯基本图' }}</li></ul><p v-for="(issue,i) in preview.issues" :key="i" class="error">{{ issue.message }}</p><p v-if="!preview.can_migrate" class="error">目标已占用或存在阻断问题，不能迁移。</p><label class="confirmation"><input v-model="confirmed" type="checkbox" />已核对唯一存储位置和旧引用变化，确认备份并迁移</label><button :disabled="busy || !confirmed || !preview.can_migrate" @click="commit">确认迁移此基本图</button></div>
</section></template>
