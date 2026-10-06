#!/usr/bin/env bash
# Copy the pipeline's Parquet marts into the web app's static assets, write the
# views-only DuckDB file + datapackage.json over their public URLs, and stamp a
# manifest. Run from anywhere; paths are resolved relative to this script.
set -euo pipefail

# Bioconductor release whose biocViews hierarchy (tree.json) the site shows.
# Bump when a new release ships.
RELEASE="${RELEASE:-3.23}"
# Where the published marts live; the views file bakes these URLs in.
PUBLIC_BASE="${PUBLIC_BASE:-https://seandavi.github.io/bioc-intelligence/data}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
src="$here/../../data/marts"
dst="$here/../public/data"
mkdir -p "$dst"

shopt -s nullglob
marts=("$src"/*.parquet)
if [ ${#marts[@]} -eq 0 ]; then
  echo "no marts found in $src — run 'biocintel build-marts' first" >&2
  exit 1
fi

cp "${marts[@]}" "$dst/"
curl -fsS "https://bioconductor.org/packages/json/$RELEASE/tree.json" -o "$dst/tree.json"
snapshot="$(date -u +%Y-%m-%d)"
# The project venv's entry point, not `uv run`: systemd's PATH has no uv, and a sync
# would drop the -e installed lake client.
"$here/../../.venv/bin/biocintel" build-marts --marts-dir "$src" \
  --views-db "$dst/bioc-intelligence.duckdb" --public-base "$PUBLIC_BASE" --snapshot "$snapshot"
names=""
for m in "${marts[@]}"; do
  names+="\"$(basename "$m")\", "
done
names="${names%, }"
printf '{\n  "snapshot": "%s",\n  "marts": [%s],\n  "views_db": "bioc-intelligence.duckdb"\n}\n' \
  "$snapshot" "$names" > "$dst/manifest.json"
echo "synced ${#marts[@]} marts to $dst (snapshot $snapshot)"
