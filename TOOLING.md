# Development Tooling

Optional Claude Code assistant tooling used while developing this repository. **None of this
is required to build or run Spencer** — see [`README.md`](README.md) and the backend/frontend
READMEs for that. This file documents the MCP servers declared in [`.mcp.json`](.mcp.json) and
the editor plugins used during development, so the setup is reproducible and the choices are
on the record.

_Last verified: 2026-08-21 (Node v22.20.0, npm 11.6.2)._

## MCP servers (`.mcp.json`)

[`.mcp.json`](.mcp.json) at the repo root declares two stdio MCP servers for Claude Code. They
are **project-scoped**, so on first open Claude Code prompts for explicit approval before
launching them (a security boundary — approve them once).

| Server | Package | Why it's here |
|---|---|---|
| `context7` | `@upstash/context7-mcp` | Pulls version-correct, up-to-date library docs on demand. This stack is bleeding-edge (Vue 3.5, Vite 8, TS 6, Tailwind, TanStack, DuckDB, FastAPI, Ibis, sqlglot) and version drift is a real risk here — a Tailwind v4/v3 mismatch already broke a build once. No API key required. |
| `playwright` | `@playwright/mcp` | Scripted browser automation for frontend E2E checks, beyond the interactive preview browser. |

Both launch via `cmd /c npx -y <package>@latest` — the `cmd /c` wrapper is the reliable form on
Windows (a bare `npx` can fail with `ENOENT` because it resolves to `npx.cmd`). Packages are
pinned to `@latest`; at time of writing they resolve to Context7 `4.0.3` and Playwright MCP
`0.0.79`.

**Activation**
1. Restart the Claude Code desktop app so it detects `.mcp.json`.
2. Approve both servers when prompted.
3. First run fetches each package via `npx` (one-time download); tools then appear as
   `mcp__context7__*` and `mcp__playwright__*`.
4. Playwright browsers: if a Playwright tool reports a missing browser, run once:
   ```bash
   npx playwright install
   ```

## Claude Code plugins (optional)

Plugins are **not** MCP servers and are not in `.mcp.json` — they install from the desktop
`/plugin` menu. The commands below are typed into the Claude Code prompt (not a shell). Each
marketplace only needs registering once.

### Official Anthropic marketplace

Registers the marketplace `claude-code-plugins`:

```
/plugin marketplace add anthropics/claude-code
```

- **`pr-review-toolkit`** _(recommended)_ — multi-agent PR review bundling `code-reviewer`,
  `code-simplifier`, and test / type-design / error-handling agents. Complements this repo's
  severity-graded self-review discipline (`.ai/CODING_STANDARDS.md`, AP-5). Covers both a code
  reviewer and a code simplifier in one plugin.
  ```
  /plugin install pr-review-toolkit@claude-code-plugins
  ```
  Run: `/pr-review-toolkit:review-pr` (aspects: `comments`, `tests`, `errors`, `types`, `code`,
  `simplify`, `all`).

- **`code-review`** — focused automated PR review (parallel agents, confidence-scored to filter
  false positives). Overlaps `pr-review-toolkit`; install one or the other, not both.
  ```
  /plugin install code-review@claude-code-plugins
  ```
  Run: `/code-review`.

### Superpowers marketplace (separate)

Optional workflow scaffolding (brainstorming, TDD, debugging, subagents). Lower marginal value
here since the repo already runs a mature proof-driven workflow.

```
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

## Deliberately not installed

Recorded so the omission reads as a decision, not a gap:

- **Chrome DevTools MCP** — redundant with Claude Code's built-in browser preview/inspection
  tools, which already handled frontend verification.
- **GitHub MCP** — redundant with the GitHub CLI (`gh`), already installed and authenticated for
  this repo.
