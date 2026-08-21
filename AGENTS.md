# AGENTS.md

You are the implementation agent for this repository.

Before making changes:
1. Read this file.
2. Read `.ai/PROJECT.md`
3. Read `.ai/REQUIREMENTS.md`
4. Read `.ai/ARCHITECTURE.md`
5. Read `.ai/DATABASE.md` and `.ai/API.md`
6. Read `.ai/CODING_STANDARDS.md` — pay particular attention to the Confirmed Anti-Patterns section; each was a real bug caught in this project, not a hypothetical
7. Read `.ai/CURRENT_STATE.md`
8. Read the active task in `tasks/active/`
9. Inspect the relevant existing source code

Local assistant tooling (optional; Claude Code MCP servers + editor plugins) is documented in `TOOLING.md`. It is developer setup only — not required to build or run the project, and not part of the task workflow above.

Do not make architectural changes without explicitly reporting them as:
```
ARCHITECTURAL_CHANGE_REQUEST
```
including: current decision, problem, proposed change, reason, benefits, risks, affected components.

Implement ONLY the current task. Do not modify unrelated files. Prefer modifying existing abstractions over creating duplicate ones. Do not introduce dependencies unless justified.

After implementation:
1. Run relevant tests — and paste their actual output, not a description of expected behavior (see CODING_STANDARDS.md AP-5)
2. Run broader tests when practical
3. Fix failures
4. Inspect your own diff
5. Verify every item in the task's Acceptance Criteria individually
6. Update `.ai/IMPLEMENTATION_REPORT.md`

The implementation report must contain:
- Task ID
- Summary
- Files changed / files created
- Important implementation decisions
- Tests executed + actual results (real output)
- Known limitations
- Remaining concerns

Self-review checklist before reporting completion:
```
[ ] Requirements implemented
[ ] Acceptance criteria satisfied — verified individually, not assumed
[ ] Relevant tests pass — actual output attached
[ ] No unrelated files changed
[ ] No debug code remains
[ ] No secrets committed
[ ] Error handling exists
[ ] Existing functionality preserved
[ ] Documentation updated
[ ] Final diff inspected
```
This is a first QA layer, not a replacement for independent review. Claims made here are verified against actual output — do not expect a report to be taken at face value.

If an important ambiguity arises that touches architecture, database schema, API contracts, security, or product behavior — do not silently invent a requirement. Report:
```
BLOCKED_ON_DECISION
```
and describe the ambiguity. For minor implementation details, use engineering judgment.
