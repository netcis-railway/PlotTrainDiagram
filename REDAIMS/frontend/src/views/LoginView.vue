<script setup lang="ts">
import { ref } from 'vue'
import ThemeToggle from '../components/ThemeToggle.vue'
defineProps<{ busy: boolean; error: string }>()
const emit = defineEmits<{ login: [displayName: string] }>()
const displayName = ref('')
const dots = Array.from({ length: 20 }, (_, i) => ({
  left: `${(i * 37 + 7) % 100}%`, top: `${(i * 23 + 11) % 100}%`,
  animationDelay: `${i % 5}s`, width: `${2 + i % 4}px`, height: `${2 + i % 4}px`,
}))
</script>
<template>
  <div class="login-page">
    <div class="login-background" aria-hidden="true"><span v-for="(dot, i) in dots" :key="i" class="floating-dot" :style="dot" /></div>
    <div class="login-toolbar"><ThemeToggle /></div>
    <div class="login-brand"><span class="brand-kicker">RAILWAY TIMETABLE & DOCUMENT MANAGEMENT</span><h1>运行图分析和文档管理系统</h1><p>REDAMS</p></div>
    <section class="login-card" aria-labelledby="login-title">
      <div class="login-emblem" aria-hidden="true">R</div><h2 id="login-title">欢迎使用</h2><p class="muted">进入你的运行方案工作区</p>
      <form @submit.prevent="emit('login', displayName)">
        <label>显示名称（选填）<input v-model="displayName" maxlength="80" autocomplete="nickname" placeholder="本地用户" :disabled="busy" /></label>
        <p class="login-hint">当前无需账号或密码，点击登录即可进入。</p>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <button class="login-button" :disabled="busy">{{ busy ? '正在进入…' : '登录 · 进入主界面' }}</button>
      </form>
    </section>
    <footer class="login-footer">REDAMS V0.1 · 铁路运行方案研究</footer>
  </div>
</template>
