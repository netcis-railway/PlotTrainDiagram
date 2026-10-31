<script setup lang="ts">
defineProps<{ typeLabel: string; name: string; notes: string; busy: boolean; error: string; status: string }>()
const emit = defineEmits<{ 'update:name': [value: string]; 'update:notes': [value: string]; save: [] }>()
</script>
<template>
  <form class="saved-item-metadata" aria-label="已保存项目属性" @submit.prevent="emit('save')">
    <div class="saved-item-identification">
    <label>子节点类型<input :value="typeLabel" readonly /></label>
    <label>名称<input :value="name" required maxlength="200" :disabled="busy" @input="emit('update:name', ($event.target as HTMLInputElement).value)" /></label>
    </div>
    <label class="saved-item-notes">备注<textarea :value="notes" rows="2" maxlength="20000" :disabled="busy" @input="emit('update:notes', ($event.target as HTMLTextAreaElement).value)" /></label>
    <button type="submit" :disabled="busy || !name.trim()">{{ busy ? '正在保存…' : '保存名称和备注' }}</button>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="status" role="status">{{ status }}</p>
  </form>
</template>
