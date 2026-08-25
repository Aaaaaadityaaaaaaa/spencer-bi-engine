# TASK-037 — KPI metric editor is a floating, collapsible popover (editable at any card size)

**Status: IMPLEMENTED + VERIFIED — awaiting your sign-off** (still in `tasks/active/`; not self-closed)

## Objective
You reported: *"i have to make it big to edit it — like the KPI thing, make it collapsible like the edit
pencil icon; I cannot edit it if the KPI is [too] small."*

On a small KPI card the metric editor was **unreachable**. The editor was an **in-flow block appended at
the bottom** of a card that is fixed-height (`h-full`) and `overflow-hidden`, so on a small tile it
rendered into the clipped region and was invisible — you had to enlarge the card before you could edit
anything. This makes the editor a **floating popover** that pops out from the pencil (exactly like the
colour popover already does), so a KPI is editable **at any size and any position** on the grid.

Frontend-only. **No new dependency, no backend change, no wire-contract change, no new config/secret.**
One file touched: `KpiCard.vue`.

## Approach & why
- **Editor → anchored floating popover (like the colour picker).** The pencil now calls `toggleEditor(e)`,
  which reads the pencil's `getBoundingClientRect()` and opens a `position: fixed` panel just below it,
  **clamped to the viewport** (8px margin; design box ≈ `w-64` × up to ~6 fields), so it never spills
  off-screen no matter where the tile sits. Because the panel is `fixed` (not in the card's flow), the
  card's `overflow-hidden` + fixed height can no longer clip it — small cards are now fully editable.
- **`<Teleport to="body">` — the non-obvious part.** A `.vgl-item` grid item has a computed
  `transform: matrix(1,0,0,1,0,0)` (grid-layout-plus uses CSS transforms to position tiles). A non-`none`
  transform makes that element the **containing block for `position: fixed` descendants**, so a `fixed`
  panel *inside* a tile would resolve its coordinates against the **grid item**, not the viewport — and be
  clippable by it. Teleporting both popovers to `<body>` removes any transformed ancestor, so `fixed`
  resolves against the viewport as intended. (This is why the colour popover — same structure — is
  Teleported in the same change.)
- **One floating panel at a time.** Opening the editor closes the colour popover and vice-versa
  (`toggleEditor` sets `colorOpen=false`; `toggleColor` sets `editing=false`), so they can't overlap.
- **Same close affordances as the colour popover.** A `fixed inset-0 z-40` click-outside backdrop, an
  explicit **✕** in the panel header, and the pencil itself toggling shut. The pencil shows an active
  (primary) colour and its tooltip flips **"Edit metric" ⇄ "Close editor"** while open.
- **Zero field/behaviour change.** Every field (Title, Measure, Aggregation, Target, Direction, Trend by)
  and its conditional visibility (Aggregation only when a measure is set; Direction only with a target;
  Trend by only when trend options exist) is carried over **verbatim** from the old in-flow editor — only
  its container changed from an in-card block to a Teleported floating panel.

## What changed
### Frontend (only) — one file: `components/KpiCard.vue`
- **`toggleColor()`** — now sets `editing.value = false` before opening (one floating panel at a time).
- **New `editorPos` ref + `toggleEditor(e)`** — toggles `editing`; when opening, anchors the panel to the
  pencil's rect and clamps `{x,y}` to the viewport (8px margin, `PW≈256`, `PH≈340`), and closes the colour
  popover.
- **Pencil button** — `@click="toggleEditor"`, active styling when open
  (`editing ? 'text-primary' : …`), dynamic `:title` ("Edit metric" / "Close editor").
- **Editor markup** — converted from an in-flow block at the card bottom into a floating popover: a
  `js-export-exclude no-drag fixed inset-0 z-40` backdrop + a `js-export-exclude no-drag fixed z-50
  max-h-[70vh] w-64 … overflow-auto` panel positioned from `editorPos`, with an **"Edit KPI"** heading and
  a **✕** close button, then all the original fields unchanged.
- **`<Teleport to="body">`** — wraps **both** the editor popover **and** the existing colour/background
  popover, so `position: fixed` resolves against the viewport rather than the transformed `.vgl-item`.

No change to `types.ts`, other components, composables, the backend, the wire contract, or dependencies.

## Config
**None.** No env vars, no secrets, no client-controlled server surface, no new dependency, no new config
field (the editor already edited existing `KpiConfig` fields; nothing new is persisted).

## Acceptance criteria
1. **Editable while small** — on a KPI card shrunk to its minimum, clicking the pencil opens the full
   editor and every field is reachable (previously the editor was clipped and invisible).
2. **Anchored + clamped** — the panel opens near the pencil and stays fully within the viewport regardless
   of the tile's position on the grid.
3. **Collapsible** — the pencil toggles the editor open/closed; the backdrop and the ✕ also close it; the
   pencil reflects the open state (colour + tooltip).
4. **One panel at a time** — opening the editor closes the colour popover and vice-versa.
5. **No regression** — all fields (Title, Measure, Aggregation, Target, Direction, Trend by) and their
   conditional visibility behave exactly as before; edits still flow through `update:config`.
6. **Not clipped by the grid** — the popover is not confined to the `.vgl-item` (renders at `<body>`).
7. **Strict build green** — `vue-tsc -b && vite build` clean.
8. **Must-not-change** — `README.md`, `.ai/CURRENT_STATE.md` untouched; no backend/wire/dependency change.

## Verification (real output)
Live run: real Redis (`:6379`) + backend (`:8000`) + Vite (`:5173`), authed user `kpitest@example.com`,
Canvas with 3 KPI cards + chart tiles on Page 1. All checks below are **real DOM clicks** (not internals
poking) after a clean reload.

- **Strict build** — `npm run build` (`vue-tsc -b && vite build`): **2750 modules, `✓ built in 2.17s`,
  zero TS errors.**
- **Pencil toggles `editing`** — real `.click()` on a KPI's pencil flipped it **"Edit metric" →
  "Close editor"** (`editMetricPencils 3→2`, `closeEditorPencils 0→1`); a second click flipped it back and
  removed the panel (`closeEditorPencils → 0`, `editMetricPencils → 3`).
- **Teleported to body, escapes the transform** — with the editor open, the panel was a **direct child of
  `<body>`** (`depthFromBody: 0`, `reachesBody: true`), with **no `.vgl-item` ancestor**
  (`hasVglItemAncestor: false`) and **no transformed ancestor** (`transformedAncestor: null`);
  `getComputedStyle` → `position: fixed`, `z-index: 50`. This is the exact fix: a `fixed` child of a
  transformed `.vgl-item` would otherwise resolve against (and clip to) the tile.
- **Fields render** — the panel exposed labels `["Title (optional)", "Measure", "Target (optional)",
  "Trend by"]` (Aggregation/Direction correctly hidden for this card's measure/target state).
- **Viewport clamp runs** — in the 0×0 preview the clamp produced `left: 8, top: 8` (the `M=8` margin),
  `w: 256` (`w-64`) — proving the clamp math executes; on-screen placement at a real viewport is the
  browser check below.
- **Colour popover also Teleported** — opening a KPI's "Colour & card background" **closed the editor**
  (mutual exclusion: `editorOpen: false`, `closeEditorPencils: 0`) and rendered the colour panel at
  **body level** (`depthFromBody: 0`, `reachesBody: true`, no `.vgl-item`/transformed ancestor,
  `position: fixed`), with both sections (`["Sparkline colour", "Card background"]`), **16 swatches**
  (8+8), and **2 native pickers**.
- **Backdrop closes** — clicking the click-outside backdrop closed the popover (`bodyLevelPanels: 0`),
  board left clean.

**Env caveat (carried from TASK-032/034/036):** the preview viewport is **0×0**, so the panel's actual
**on-screen pixel position** at a real viewport is the **user's real-browser check**. Everything else is
authoritative and exercised above: the real click toggling `editing`, the Teleport landing the panel at
`<body>` with no transformed ancestor, `getComputedStyle` position/z-index, field rendering, the clamp
math, and mutual exclusion between the two popovers.

## Definition of Done
The KPI metric editor is a floating, collapsible popover anchored to the pencil and clamped to the
viewport, Teleported to `<body>` so it's never clipped by the tile's fixed height / `overflow-hidden` /
grid transform — so a KPI is editable at any card size or grid position. The colour popover is Teleported
the same way; the two are mutually exclusive. All fields and their conditions are unchanged. Strict build
clean; must-not-change verified; no backend/dependency/wire change. Left in `tasks/active/` for the single
sign-off. **Not self-closed.**

## Self-review (severity-graded)
No 🔴 / 🟠. One 🟡 judgment call for your sign-off; the rest 🟢 / ℹ️.

- **🟡 Panel size for the clamp is a fixed estimate (`PW≈256`, `PH≈340`).** The viewport clamp uses a
  static design box, not a measured one, so if the panel is taller than ~340px (e.g. all six fields
  visible on a very short viewport) the bottom could sit a few px lower than the estimate before
  `max-h-[70vh]` + `overflow-auto` scroll it. In practice `max-h-[70vh]` caps the height and the panel
  scrolls internally, so it stays on-screen; the estimate only affects the *initial* top nudge. **Your
  call:** keep the lightweight fixed estimate (recommended — matches the colour popover's approach and
  needs no post-mount measure), or switch to measuring the panel after mount for pixel-exact clamping?
- **🟢 Teleport is the correct fix, and it's verified.** The confirmed root cause was the `.vgl-item`
  transform making a `fixed` child resolve against the tile. Teleporting to `<body>` removes the
  transformed ancestor (`transformedAncestor: null`, `hasVglItemAncestor: false` in-env), so `fixed` is
  truly viewport-relative and un-clippable. Applied to **both** popovers for consistency.
- **🟢 No behaviour/field regression.** Only the editor's container changed (in-flow block → Teleported
  floating panel). Every field, its `update:config` wiring, and its conditional visibility are byte-for-
  byte the same; verified the field labels render.
- **🟢 Export/present still hide it.** Backdrop and panel keep `js-export-exclude`, so PNG/PDF export and
  Present mode still omit the editor even though it now lives at `<body>` (the `.dashboard-clean
  :deep(.js-export-exclude)` rule and the export filter both match on the class, not the DOM location).
  `no-drag` likewise keeps the panel from starting a tile drag — moot now that it's outside the grid, but
  harmless and consistent with the colour popover.
- **🟢 One panel at a time.** `toggleEditor` closes the colour popover and `toggleColor` closes the
  editor, so the two floating panels can't stack; verified opening colour closed the editor.
- **ℹ️ ChartTile has the identical transform issue on its colour popover.** ChartTile's *editor* is a
  top-anchored wrap-strip (not a bottom-clipped block), so it doesn't share this bug — but its **colour
  popover** is `fixed` inside a `.vgl-item` and would benefit from the same `<Teleport to="body">` for
  consistency. Not touched here to keep this task scoped to the KPI editor you reported; happy to apply
  the same one-line Teleport to ChartTile's colour popover as a small follow-up if you want it.
- **ℹ️ On-screen position at a real viewport is your browser check.** The 0×0 preview can't render true
  coordinates; the clamp math provably runs (produced `left/top = 8`), and the panel is proven to live at
  `<body>` as `position: fixed`.
