// CodeMirror 6 lifecycle in one place (Phase 6 / TASK-012), mirroring useEchart's
// pattern: build once on mount, react to prop changes via watch, and destroy() on
// unmount so the view's listeners/DOM are released.
//
// CodeMirror 6 was chosen for the MySQL-Workbench-style editor. Imports are
// granular: the `codemirror` meta-package gives EditorView + basicSetup; keymap
// comes from @codemirror/view, EditorState/Compartment from @codemirror/state, and
// the SQL grammar from @codemirror/lang-sql -- no web workers, clean Vite build.
import { onBeforeUnmount, onMounted, watch } from 'vue'
import type { Ref } from 'vue'
import { EditorView, basicSetup } from 'codemirror'
import { keymap } from '@codemirror/view'
import { EditorState, Compartment } from '@codemirror/state'
import type { Extension } from '@codemirror/state'
import { sql } from '@codemirror/lang-sql'

// The session's single table (ADR-006) described for schema-aware autocomplete: `FROM `
// completes the (UUID-laden) table name so it never has to be typed, and bare
// identifiers complete to its columns. `table` is null before a dataset is loaded.
export interface CodeMirrorSchema {
  table: string | null
  columns: string[]
}

// Imperative handle returned to the host component.
export interface CodeMirrorApi {
  // Insert text at the cursor (or append to the end when the editor isn't focused),
  // then focus. Backs the click-to-insert schema chips so the long table name and the
  // column names land in the query without being typed.
  insert: (text: string) => void
}

/**
 * Mount a CodeMirror SQL editor on `el`, two-way-bound to `doc`.
 *
 * - Edits inside the editor push back into `doc` (updateListener), so the parent's
 *   v-model:sql stays in sync.
 * - External `doc` changes (the AI dropping generated SQL in = the Review Gate) are
 *   dispatched into the editor, but ONLY when the text actually differs -- otherwise
 *   the round-trip (editor edit -> doc -> watch) would fight the user's cursor.
 * - Cmd/Ctrl+Enter runs `onRun` (Workbench-style "execute").
 * - `readOnly` (set while a query is running) is toggled through a Compartment, so we
 *   reconfigure just that facet instead of rebuilding the editor.
 * - `schema` (the session table + its columns) drives autocomplete through its own
 *   Compartment, reconfigured when a new dataset is loaded -- no editor rebuild.
 * - destroy() on unmount frees the view (mirrors useEchart's dispose()).
 */
export function useCodeMirror(
  el: Ref<HTMLElement | null>,
  doc: Ref<string>,
  opts: { onRun: () => void; readOnly: Ref<boolean>; schema?: Ref<CodeMirrorSchema> },
): CodeMirrorApi {
  let view: EditorView | null = null
  const readOnlyComp = new Compartment()
  const sqlComp = new Compartment()

  // Build the SQL language extension. With a loaded table, pass its columns as the
  // completion schema and mark it the defaultTable so unqualified column names also
  // complete; otherwise fall back to bare SQL (keyword completion only).
  function sqlExtension(): Extension {
    const s = opts.schema?.value
    if (s && s.table) {
      return sql({ schema: { [s.table]: s.columns }, defaultTable: s.table })
    }
    return sql()
  }

  function mount(): void {
    const host = el.value
    if (!host || view) return
    const state = EditorState.create({
      doc: doc.value,
      extensions: [
        basicSetup,
        sqlComp.of(sqlExtension()),
        keymap.of([
          {
            key: 'Mod-Enter',
            preventDefault: true,
            run: () => {
              opts.onRun()
              return true
            },
          },
        ]),
        readOnlyComp.of(EditorState.readOnly.of(opts.readOnly.value)),
        EditorView.updateListener.of((u) => {
          if (!u.docChanged) return
          const next = u.state.doc.toString()
          if (next !== doc.value) doc.value = next
        }),
        EditorView.theme({
          '&': { height: '100%' },
          '&.cm-focused': { outline: 'none' },
          '.cm-content': {
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
            fontSize: '13px',
          },
          '.cm-gutters': { fontSize: '12px' },
          '.cm-scroller': { overflow: 'auto' },
        }),
      ],
    })
    view = new EditorView({ state, parent: host })
  }

  onMounted(mount)

  // Push external doc updates (AI-generated SQL) into the editor. Guarded so typing
  // -> doc -> here does not re-dispatch the same text and reset the cursor.
  watch(doc, (next) => {
    if (!view) return
    const current = view.state.doc.toString()
    if (next !== current) {
      view.dispatch({ changes: { from: 0, to: current.length, insert: next } })
    }
  })

  watch(opts.readOnly, (ro) => {
    view?.dispatch({ effects: readOnlyComp.reconfigure(EditorState.readOnly.of(ro)) })
  })

  // Reconfigure autocomplete when the dataset (hence the table + columns) changes.
  if (opts.schema) {
    watch(
      opts.schema,
      () => {
        view?.dispatch({ effects: sqlComp.reconfigure(sqlExtension()) })
      },
      { deep: true },
    )
  }

  onBeforeUnmount(() => {
    view?.destroy()
    view = null
  })

  function insert(text: string): void {
    if (!view) return
    // Insert at the cursor when the editor is the active element -- the chips use
    // mousedown.prevent so clicking one does NOT steal focus, leaving the user's
    // cursor intact. Otherwise (editor never focused) append to the end so a chip
    // clicked cold extends the query instead of landing at column 0 before SELECT.
    // Gating on activeElement (not view.hasFocus) keeps this independent of whether
    // the whole window currently holds OS focus.
    const focused = view.contentDOM.contains(document.activeElement)
    const sel = view.state.selection.main
    const end = view.state.doc.length
    const from = focused ? sel.from : end
    const to = focused ? sel.to : end
    // Add a leading space when butting against a non-space char so tokens don't fuse.
    const prev = from > 0 ? view.state.doc.sliceString(from - 1, from) : ' '
    const payload = /\s/.test(prev) ? text : ` ${text}`
    view.dispatch({
      changes: { from, to, insert: payload },
      selection: { anchor: from + payload.length },
    })
    view.focus()
  }

  return { insert }
}
