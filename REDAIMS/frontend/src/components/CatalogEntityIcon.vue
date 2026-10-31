<script setup lang="ts">
defineProps<{ kind: 'base' | 'run' | 'experiment'; virtual?: boolean }>()
</script>
<template>
  <svg class="tree-diagram" :class="{ 'tree-base': kind === 'base', 'tree-experiment': kind === 'experiment' }" viewBox="0 0 20 18" aria-hidden="true">
    <template v-if="kind === 'experiment'">
      <g class="tree-test-tubes">
        <path d="M2.5 1.5h4 M8 1.5h4 M13.5 1.5h4 M3 1.5V13.5a1.5 1.5 0 0 0 3 0V1.5 M8.5 1.5V13.5a1.5 1.5 0 0 0 3 0V1.5 M14 1.5V13.5a1.5 1.5 0 0 0 3 0V1.5" />
        <path class="tree-test-liquid" d="M3.6 10h1.8v3.5a.9.9 0 0 1-1.8 0Z M9.1 10h1.8v3.5a.9.9 0 0 1-1.8 0Z M14.6 10h1.8v3.5a.9.9 0 0 1-1.8 0Z" />
        <path d="M1 6v9.5h18V6 M1 8h18 M.5 17h19" />
      </g>
      <template v-if="virtual"><circle class="tree-reference-badge" cx="16.5" cy="14.5" r="3.1" /><path d="M14.5 14.5h4m-1.8-1.8 1.8 1.8-1.8 1.8" /></template>
    </template>
    <template v-else-if="kind === 'base'"><rect x="3" y="1" width="14" height="16" /><text class="tree-document-letter" x="10" y="13.5" text-anchor="middle">B</text></template>
    <template v-else><path d="M8 1h9v16H3V6Z M3 6h5V1" /><g class="tree-timetable-grid"><rect x="5" y="8" width="10" height="7.5" /><path d="M10 8v7.5 M5 10.5h10 M5 13h10" /></g></template>
  </svg>
</template>
