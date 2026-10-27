<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { TimetableActionRequest } from '../catalogActions'
import type { CatalogNode } from '../api/client'
import { baseApi, formatPath, type BaseTimetable, type Resolution } from '../api/baseImport'
import TimetableEditor from './TimetableEditor.vue'
const props = defineProps<{ baseId: string; scopePath: string; resolution: Resolution | null; nodes: CatalogNode[]; actionRequest?: TimetableActionRequest }>()
const emit = defineEmits<{ changed: [owner: string | null] }>()
const deletionPanel = ref<HTMLDetailsElement | null>(null)
const detail = ref<BaseTimetable | null>(null), error = ref(''), busy = ref(false), confirmed = ref(false)
const deletion = ref<Awaited<ReturnType<typeof baseApi.deletePreview>> | null>(null)
let generation = 0
async function load() { const version = ++generation; detail.value = null; error.value = ''; deletion.value = null; if (!props.baseId) return; try { const result = await baseApi.base(props.baseId); if (version === generation) detail.value = result } catch (e) { if (version === generation) error.value = String(e) } }
async function changed(owner: string | null) { try { if (props.baseId) detail.value = await baseApi.base(props.baseId); deletion.value = null; emit('changed', owner) } catch (e) { error.value = String(e) } }
async function inspectDelete() {
  const id = props.baseId, version = generation
  busy.value = true; confirmed.value = false; error.value = ''; deletion.value = null
  if (deletionPanel.value) deletionPanel.value.open = true
  await nextTick()
  deletionPanel.value?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  try { const result = await baseApi.deletePreview(id); if (version === generation) deletion.value = result }
  catch (e) { if (version === generation) error.value = String(e) }
  finally { if (version === generation) busy.value = false }
}
let handledAction = 0
watch([() => props.actionRequest, detail], () => {
  const request = props.actionRequest
  if (!request || request.sequence === handledAction || request.kind !== 'base' || request.objectId !== props.baseId || request.action !== 'delete' || !detail.value) return
  handledAction = request.sequence
  void inspectDelete()
}, { flush: 'post', immediate: true })
async function remove() { if (!deletion.value || !confirmed.value || !deletion.value.can_delete) return; busy.value = true; try { await baseApi.deleteBase(props.baseId, deletion.value.preview_token); detail.value = null; emit('changed', null) } catch (e) { error.value = String(e) } finally { busy.value = false } }
watch(() => props.baseId, load, { immediate: true })
</script>
<template><h2>基本图</h2><p>当前查看类别：{{ scopePath }}</p><p v-if="error" class="error" role="alert">{{ error }}</p>
  <template v-if="detail"><p class="category-context">{{ resolution?.effective.mode === 'inherited' ? '回溯使用上级基本图' : '物理绑定' }} · 实际存储位置：{{ formatPath(detail.classification_path) }}</p>
    <dl class="base-info-grid"><dt>基本图</dt><dd>{{ detail.name }} · {{ detail.baseTT_no }}</dd><dt>基准日期</dt><dd>{{ detail.date_base }}</dd><dt>车站 / 列车 / 访问</dt><dd>{{ detail.summary.nodes }} / {{ detail.summary.trains }} / {{ detail.summary.events }}</dd><template v-for="s in detail.source_files" :key="s.id"><dt>受管源文件</dt><dd><a :href="`/api/v1/source-files/${s.id}`">{{ s.filename }}</a><br />{{ s.managed_path }}</dd></template></dl>
    <TimetableEditor :key="detail.id" object-type="base" :object-id="detail.id" :nodes="nodes" :action-request="actionRequest" @changed="changed" />
    <details ref="deletionPanel" class="deletion-panel"><summary>删除此基本图</summary><p>独立删除保留分类；存在继承依赖时须先处理。</p><button :disabled="busy" @click="inspectDelete">预览删除影响</button><template v-if="deletion"><p v-if="!deletion.can_delete" class="error">{{ deletion.blocking_dependencies.length }} 个类别或 run 仍使用该图，暂不能删除。</p><label class="confirmation"><input v-model="confirmed" type="checkbox" />确认永久删除基本图及独占受管文件，原 Excel 不变</label><button class="danger" :disabled="busy || !confirmed || !deletion.can_delete" @click="remove">确认删除基本图</button></template></details>
  </template><p v-else class="empty-state">当前类别没有可用基本图。可在本类别导入，或由最近祖先图提供基准。</p>
</template>
