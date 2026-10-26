<script setup lang="ts">
import { ref, watch } from 'vue'
import { deletionApi, type CatalogNode, type DeletionPreview, type Kind } from '../api/client'
const labels: Record<Kind, string> = { user: '研究员', network: '路网', scenario: '场景', case: '案例', algorithm: '算法', batch: '批次', run: 'run' }
const props = defineProps<{ node: CatalogNode; nodes: CatalogNode[] }>()
const emit = defineEmits<{ deleted: [] }>()
const preview = ref<DeletionPreview | null>(null)
const action = ref<'' | 'delete' | 'ungroup' | 'move'>('')
const target = ref('')
const confirmed = ref(false)
const busy = ref(false)
const error = ref('')
watch(() => props.node.id, () => { preview.value = null; action.value = ''; confirmed.value = false; error.value = '' })
function path(id: string) {
  const names: string[] = []
  let node = props.nodes.find(n => n.id === id)
  while (node) { names.unshift(node.name); node = props.nodes.find(n => n.id === node?.parent_id) }
  return names.join(' → ')
}
async function inspect() {
  busy.value = true; error.value = ''; confirmed.value = false; action.value = ''; target.value = ''
  try { preview.value = await deletionApi.preview(props.node.id) }
  catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function remove() {
  if (!preview.value || !action.value || !confirmed.value) return
  busy.value = true; error.value = ''
  try {
    await deletionApi.remove(props.node.id, { action: action.value, target_batch_id: action.value === 'move' ? target.value : null, preview_token: preview.value.preview_token, confirmed: true })
    preview.value = null; emit('deleted')
  } catch (e) { error.value = String(e); confirmed.value = false }
  finally { busy.value = false }
}
</script>
<template>
  <div class="deletion-panel"><h3>删除分类：{{ labels[node.kind] }} {{ node.name }}</h3>
    <p class="deletion-path"><strong>拟删除分类的完整路径：</strong>{{ path(node.id) }}</p><p>删除“{{ node.name }}”及其全部子类别。请先预览影响，再选择 run 的去向。</p>
    <button type="button" :disabled="busy" @click="inspect">预览删除影响</button>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <form v-if="preview" @submit.prevent="remove">
      <p v-if="!preview.can_delete" class="error">范围内有 {{ preview.physical_base_timetables.length }} 幅独立基本图、{{ preview.legacy_base_ids.length }} 幅旧基本图。请先移动/单独删除独立图，或明确迁移旧图；run 的去向选项不处理基本图。</p>
      <ul v-if="preview.physical_base_timetables.length"><li v-for="base in preview.physical_base_timetables" :key="base.id">基本图：{{ base.name }} · {{ path(base.owner_category_id) }}</li></ul>
      <p>将删除 {{ preview.node_count }} 个分类，涉及 {{ preview.run_count }} 个 run。分类删除不可撤销。</p>
      <details><summary>查看受影响分类和 run</summary><ul><li v-for="item in preview.nodes" :key="item.id">{{ path(item.id) }}</li><li v-for="run in preview.runs" :key="run.id">run：{{ run.name }} / {{ run.run_no }}</li></ul></details>
      <label>下属 run 的处理方式<select v-model="action" required :disabled="busy" @change="confirmed = false"><option disabled value="">请选择处理方式</option><option value="ungroup">保留，归入未分组</option><option value="move">保留，转入其他批次</option><option value="delete">彻底删除（不可恢复）</option></select></label>
      <label v-if="action === 'move'">目标批次<select v-model="target" required :disabled="busy" @change="confirmed = false"><option disabled value="">请选择删除范围以外的批次</option><option v-for="batch in preview.eligible_batches" :key="batch.id" :value="batch.id">{{ path(batch.id) }}</option></select></label>
      <p v-if="action === 'move' && !preview.eligible_batches.length">没有可用目标批次，请取消并先在删除范围之外创建批次。</p>
      <p v-if="action === 'delete'" class="error">所列 run 将被永久删除，不可恢复。</p>
      <label class="confirmation"><input v-model="confirmed" type="checkbox" :disabled="busy" />我已核对删除范围及 run 处理方式，确认执行。</label>
      <div><button type="submit" class="danger" :disabled="busy || !preview.can_delete || !confirmed || !action || (action === 'move' && !target)">{{ busy ? '正在删除…' : '确认删除分类及子类别' }}</button> <button type="button" :disabled="busy" @click="preview = null">取消</button></div>
    </form>
  </div>
</template>
