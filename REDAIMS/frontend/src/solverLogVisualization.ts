import { markRaw, shallowRef, type Component } from 'vue'

// Register the future log visualizer here. It receives text, filename and state,
// and emits update:state with JSON display settings, which are saved with the node.
export interface SolverLogVisualizationProps { text: string; filename: string; state: Record<string, unknown> }
export const solverLogVisualizer = shallowRef<Component | null>(null)
export function registerSolverLogVisualizer(component: Component | null) {
  solverLogVisualizer.value = component ? markRaw(component) : null
}
