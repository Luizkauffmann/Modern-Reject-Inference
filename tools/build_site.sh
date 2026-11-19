#!/usr/bin/env bash
# Refreshes docs/demo, the folder served by GitHub Pages, from the sources.
# The browser demo runs these exact files in Pyodide. Run this after changing reject_inference/
# or after rebuilding the data (python data/generate_data.py && python -m reject_inference.pipeline).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=docs/demo
rm -rf "$OUT/app" && mkdir -p "$OUT/app/ui" "$OUT/data"
cp reject_inference/explorer.py "$OUT/app/explorer.py"
cp reject_inference/ui/index.html reject_inference/ui/app.css reject_inference/ui/app.js "$OUT/app/ui/"
${PYTHON:-python3} tools/slim_data.py data "$OUT/data"
echo "demo refreshed in $OUT:"; ls -la "$OUT/app" "$OUT/data"
