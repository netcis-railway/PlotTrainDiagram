<script setup lang="ts">
import { theme, setTheme } from '../stores/theme'
</script>
<template>
  <button class="theme-toggle" type="button" :aria-label="theme === 'light' ? '切换深色模式' : '切换浅色模式'" :aria-pressed="theme === 'dark'" @click="setTheme(theme === 'light' ? 'dark' : 'light')">
    <span aria-hidden="true">{{ theme === 'light' ? '☾' : '☀' }}</span> {{ theme === 'light' ? 'Dark 深色' : 'Light 浅色' }}
  </button>
</template>
