// Lightweight toast queue (Batch 1 / Global polish). Additive: a tiny global
// notification bus so transforms, exports, logins and uploads give the user closure
// instead of only inline errors. No UI framework — App.vue renders the queue.
import { ref } from 'vue'

export type ToastKind = 'success' | 'error' | 'info'
export interface Toast {
  id: number
  kind: ToastKind
  message: string
  // optional action (e.g. "Undo") — kept simple; the renderer shows a button if present.
  actionLabel?: string
  onAction?: () => void
}

const toasts = ref<Toast[]>([])
let seq = 0

export function pushToast(
  message: string,
  kind: ToastKind = 'info',
  opts: { duration?: number; actionLabel?: string; onAction?: () => void } = {},
): number {
  const id = ++seq
  toasts.value.push({
    id,
    kind,
    message,
    actionLabel: opts.actionLabel,
    onAction: opts.onAction,
  })
  const duration = opts.duration ?? (kind === 'error' ? 6000 : 3500)
  if (duration > 0) {
    setTimeout(() => dismissToast(id), duration)
  }
  return id
}

export function dismissToast(id: number): void {
  const i = toasts.value.findIndex((t) => t.id === id)
  if (i !== -1) toasts.value.splice(i, 1)
}

export function useToasts() {
  return { toasts, pushToast, dismissToast }
}
