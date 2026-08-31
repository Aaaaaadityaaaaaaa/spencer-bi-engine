# Development Tooling

Optional assistant tooling used while developing this repository. **None of this is required to
build or run Spencer** — see [`README.md`](README.md) and the backend/frontend READMEs for that.
This file documents the MCP servers declared in [`.mcp.json`](.mcp.json) (Claude Code) and
`~/.workbuddy-ai/mcp.json` (WorkBuddy), plus the editor plugins used during development, so the
setup is reproducible and the choices are on the record.

_Last verified: 2026-08-31 (Node v22.22.2, npm 10.9.7). MCP section updated; see below._

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
pinned to `@latest`; at time of writing they resolve to Context7 `4.0.4` and Playwright MCP
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

## WorkBuddy MCP config (`~/.workbuddy-ai/mcp.json`)

The section above is **Claude Code's** project scope. WorkBuddy reads a *different* file —
`%USERPROFILE%\.workbuddy-ai\mcp.json` — so the same servers are declared there for that host.
Both files are kept deliberately: separate clients, separate scopes, and neither reads the
other's config. Three servers are declared:

| Server | Launch form | Notes |
|---|---|---|
| `context7` | `cmd /c npx -y @upstash/context7-mcp@latest` | Same as `.mcp.json`. |
| `playwright` | `cmd /c npx -y @playwright/mcp@latest` | Same as `.mcp.json`. Chromium 1234 is already in `~/AppData/Local/ms-playwright`, so no `playwright install` needed. |
| `skills-server` | `node <pkg>/build/index.js` | See below — deliberately **not** the `.cmd` shim. |

### Why `skills-server` is launched via `node`, not its `.cmd` shim

`@skills-server/mcp` (v3.0.1) installs a `skills-server.cmd` shim, and its own README suggests
`"command": "skills-server"`. **Both of those forms fail on this machine.** Node cannot spawn a
`.cmd` directly without `shell: true` — it raises `Error: spawn EINVAL` — and MCP clients do not
pass a shell. Verified empirically: the `.cmd` path fails; `node build/index.js` completes the
full `initialize` → `tools/list` → `tools/call` handshake.

So the config calls the managed `node.exe` against the package entry point, using absolute paths
(no PATH reliance). The package is installed into the **managed workspace**, not `-g`:

```
C:\Users\adity\.workbuddy-ai\binaries\node\workspace\node_modules\@skills-server\mcp
```

`SKILLS_DIR` points at `~/.workbuddy-ai/skills` — the *same* directory the native Skills system
uses — instead of the server's `~/.skills` default, so the two systems mirror each other rather
than compete. Every `SKILL.md` written there is auto-discovered and hot-reloads without a restart
(verified: 1 skill discovered, exposed as a `spencer-verify` tool, `get_skill` returned 2,980
chars). `LAZY_MCP_ENABLED` is `false` — the bridge needs a separate Python install and would add
two navigation tools for no gain here.

**Caveat:** the binary self-reports `Enhanced Skills MCP Server v0.2.0` while the npm package is
`3.0.1`. Upstream version-string mismatch, cosmetic only.

**Caveat:** the `node.exe` path is version-pinned to `22.22.2-1`. If that managed runtime is ever
removed, replace it with `C:\Program Files\nodejs\node.exe`.

### Activation (WorkBuddy)

MCP servers are **not** live until trusted: open connector management, find the new servers under
the custom-connectors entry at the top right, and click **Trust** on each. A restart may be
needed before they appear.

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
