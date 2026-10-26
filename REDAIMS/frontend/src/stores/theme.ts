import { ref } from 'vue'
export type Theme = 'light' | 'dark'
function initial(): Theme {
  try { return localStorage.getItem('redams.theme') === 'dark' ? 'dark' : 'light' }
  catch { return 'light' }
}
export const theme = ref<Theme>(initial())
export function setTheme(value: Theme) {
  theme.value = value
  document.documentElement.dataset.theme = value
  try { localStorage.setItem('redams.theme', value) } catch { /* apply without persistence */ }
}
setTheme(theme.value)
