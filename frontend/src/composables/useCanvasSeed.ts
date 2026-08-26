// A one-shot courier from the Query Engine's "Send to Canvas" action to the Canvas view.
// "Send to Canvas" materializes the current result as a new table (useSession.materializeResult
// switches the active table to it) and routes to /canvas; this flag tells ChartCanvas to drop
// in a fresh blank chart tile on arrival, so the user lands on a ready-to-configure chart over
// the just-created table. Module-scoped singleton like useQuestionHandoff, so the producer
// (QueryConsole) and the consumer (ChartCanvas) share ONE reactive slot across the route change
// without prop-drilling. Read-and-cleared so it fires EXACTLY once — not on every keep-alive
// re-activation of the Canvas view.
import { reactive, toRefs } from 'vue'

interface CanvasSeedState {
  // True when a freshly-materialized result is waiting for the Canvas to seed a chart tile.
  pendingChartSeed: boolean
}

const state = reactive<CanvasSeedState>({ pendingChartSeed: false })

// Producer: arm the seed, then (the caller) navigate to /canvas.
function seedChartOnCanvas(): void {
  state.pendingChartSeed = true
}

// Consumer: read-and-clear. Returns true at most once per "Send to Canvas".
function takePendingSeed(): boolean {
  const pending = state.pendingChartSeed
  state.pendingChartSeed = false
  return pending
}

export function useCanvasSeed() {
  return { ...toRefs(state), seedChartOnCanvas, takePendingSeed }
}
