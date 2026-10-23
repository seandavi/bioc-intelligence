# AGENTS.md

Read [CLAUDE.md](CLAUDE.md) first: commands, layout, architecture, settled decisions and domain
gotchas. `bioc-intelligence-spec.md` is the design source of truth. Rules for any agent working
here:

- **The main checkout (`~/Documents/git/bioc-intelligence` on onclappc02) runs production.** The
  monthly systemd refresh runs from it. Work in a worktree (`../bioc-intelligence-wt<issue>`),
  keep the main checkout on `main`, and never switch its branch.
- Never run the refresh, `sync-marts.sh` or `systemd/publish-marts.sh` from a branch, and never
  hand-edit `data/` or `frontend/public/data/`. If a change needs a data run or a views-file
  regeneration, say so in the PR.
- Tests are offline and fixture-based (`tests/fixtures/`). `uv run pytest` and
  `uv run ruff check src tests` must pass.
- One PR per issue. Merge on green from the main session. Never `git stash` (worktrees share
  `refs/stash`); never force-push `main`.
- Commits written by an agent carry `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Issues run through the factory: see [.pi/factory.md](.pi/factory.md).
