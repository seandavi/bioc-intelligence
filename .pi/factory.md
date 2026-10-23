# The factory: spec → implement → review → revise → PR

Issues run through a fixed loop of [pi-subagents](https://github.com/nicobailon/pi-subagents)
stages: Opus where judgment matters, Sonnet where volume does, Haiku for bookkeeping. A human
merges. The script is [`workflows/factory.js`](workflows/factory.js). The engine is a copy of
[seandavi/pi-factory](https://github.com/seandavi/pi-factory) at `4d310bf`; its
[docs/factory.md](https://github.com/seandavi/pi-factory/blob/main/docs/factory.md) describes the
loop in full (stages, revise rounds, fix-judging, follow-up issues, `needs:human`, `startAt`).
Replace this copy with the installed engine and a `.pi/factory.json` once pi-factory#2/#3 land.

## What is specific to this repo

The project block at the top of `factory.js` sets:

- **Spec:** `bioc-intelligence-spec.md` + `CLAUDE.md`. Specs are written to
  `docs/specs/<issue>-<slug>.md`.
- **Checks:** `uv run pytest`, `uv run ruff check src tests`, plus `npm run build` and
  `npm run lint` in `frontend/` for frontend changes. Check results are `tests` and `lint`; a
  failure makes the PR a draft.
- **Guardrails:** stages never run the refresh, `sync-marts.sh` or `publish-marts.sh`, and never
  edit `data/` or `frontend/public/data/`. The main checkout runs production (see `AGENTS.md`).
  A change that needs a data run says so in the PR; a human runs it after merge.
- **Skills:** none yet.

**Review lenses**, chosen per issue from its labels:

| Lens | When | Looks at |
|---|---|---|
| `code` | always | spec ↔ code agreement, offline fixture tests, framework-free modules with `run()`, `schema.sql` + migration, `DEFINITIONS` for every mart column, views-file regeneration, source-agnostic enrichment SQL |
| `data` | label `data-quality`, or any change to marts, metrics or enrichment | correct aggregation per metric, provenance columns, snapshot/era discipline, work identity, NULL not fake zeros, definitions that say what a number does not mean |
| `frontend` | label `frontend` | DuckDB-WASM over published marts, a11y, jargon tooltips, pending states, Vega-Lite encodings |

Label `seam` (arg `seam: true`) for shared foundations later issues build on, such as a new
dimension other marts join.

## Running it

Make the worktree first (the workflow sandbox has no shell). Use the `-wt<issue>` sibling
convention:

```sh
git -C ~/Documents/git/bioc-intelligence fetch origin
git -C ~/Documents/git/bioc-intelligence worktree add -b issue-91-region-groupings \
  ~/Documents/git/bioc-intelligence-wt91 origin/main
```

```js
subagent({
  workflow: "./.pi/workflows/factory.js",
  cwd: "~/Documents/git/bioc-intelligence",
  async: true,
  args: {
    repo: "seandavi/bioc-intelligence", issue: 91, slug: "region-groupings",
    worktree: "/home/davsean/Documents/git/bioc-intelligence-wt91",
    branch: "issue-91-region-groupings", lenses: ["code", "data"], seam: true
    // parent: <tracking issue>, startAt: "implement" | "review"
  }
})
```

Your queue is `gh issue list -l needs:human` plus `gh pr list -l needs:human`. Merge from the main
session; remove `needs:human` once you've acted. Never `/reload` pi while a run is active.
