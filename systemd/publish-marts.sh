#!/usr/bin/env bash
# Commit the refreshed Parquet marts and push. The push to
# frontend/public/data/ is what triggers deploy-pages.yml, so without this the
# pipeline runs and nothing the public sees ever changes.
#
# This replaces the "Commit updated marts" step from enrich.yml, but it runs
# somewhere that step never did: a working checkout a human also uses. A CI
# runner starts from a pristine clone and can assume anything it finds is its
# own; here that assumption is false, so the guards below refuse to act rather
# than risk touching in-progress work. A refusal exits non-zero, which trips
# the unit's OnFailure= and pages -- deliberately, because a silently skipped
# publish looks exactly like a successful run with no data changes.
set -euo pipefail

cd /home/davsean/Documents/git/bioc-intelligence

branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$branch" != "main" ]; then
  echo "refusing to publish: on branch '$branch', not main" >&2
  exit 1
fi

# Anything dirty outside the marts directory is someone's uncommitted work.
# `git add` would not stage it, but `git pull --rebase` below would fail or
# stash-dance around it, so stop before touching the tree at all.
stray=$(git status --porcelain -- . ':!frontend/public/data' | head -5)
if [ -n "$stray" ]; then
  echo "refusing to publish: uncommitted changes outside frontend/public/data:" >&2
  echo "$stray" >&2
  exit 1
fi

git add frontend/public/data/
if git diff --cached --quiet; then
  echo "No data changes."
  exit 0
fi

git -c user.name="biocintel-refresh" \
    -c user.email="seandavi@gmail.com" \
    commit -m "data: monthly mart refresh $(date -u +%Y-%m-%d)"
git pull --rebase
git push
echo "published $(git rev-parse --short HEAD)"
