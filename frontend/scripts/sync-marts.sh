#!/usr/bin/env bash
# Copy the pipeline's Parquet marts into the web app's static assets and stamp a
# manifest. Run from anywhere; paths are resolved relative to this script.
set -euo pipefail

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
snapshot="$(date -u +%Y-%m-%d)"
names=""
for m in "${marts[@]}"; do
  names+="\"$(basename "$m")\", "
done
names="${names%, }"
printf '{\n  "snapshot": "%s",\n  "marts": [%s]\n}\n' "$snapshot" "$names" > "$dst/manifest.json"
echo "synced ${#marts[@]} marts to $dst (snapshot $snapshot)"
