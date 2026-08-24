// A one-shot handoff from the Table section's auto-EDA panel (#26) to the Query Engine.
// Clicking a suggested question stashes it here and routes to /query, where QueryConsole
// reads-and-clears it (fills the NL box + generates SQL) exactly once. Module-scoped
// singleton like useSession / useQueryHistory, so the producer (SuggestedQuestions) and
// the consumer (QueryConsole) share ONE reactive slot without prop-drilling across routes.
import { reactive, toRefs } from 'vue'

interface HandoffState {
  // The question waiting to be picked up by the Query Engine, or null when nothing is
  // pending. Kept deliberately tiny: this is a transient courier, not persisted state.
  pendingQuestion: string | null
}

const state = reactive<HandoffState>({ pendingQuestion: null })

// Producer: stash a question and (the caller then) navigate to /query.
function askInQueryEngine(question: string): void {
  const q = question.trim()
  if (q) state.pendingQuestion = q
}

// Consumer: read-and-clear. A handoff must fire ONCE, not on every re-activation of the
// kept-alive Query Engine view, so reading it also consumes it.
function takePendingQuestion(): string | null {
  const q = state.pendingQuestion
  state.pendingQuestion = null
  return q
}

export function useQuestionHandoff() {
  return { ...toRefs(state), askInQueryEngine, takePendingQuestion }
}
