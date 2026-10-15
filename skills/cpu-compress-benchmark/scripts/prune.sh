#!/usr/bin/env bash
# prune.sh - shrink a finished run directory without losing its evidence.
#
# Usage:
#   prune.sh --run-dir DIR [--keep-dataset]
#
# Deletes the large regenerable files (the dataset and the compressed artifacts)
# and writes artifacts-manifest.sha256 with their hashes first, so the report
# still names a verifiable artifact for every configuration. The measured
# numbers, the report and the raw rows are never touched.
#
# The dataset is reproducible from its seed, and every artifact is reproducible
# from the dataset plus the recorded codec, level and thread count, so nothing
# irreplaceable is removed. Pass --keep-dataset to keep the input file.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

RUN_DIR=""
KEEP_DATASET=0

while [ $# -gt 0 ]; do
  case "$1" in
    --run-dir) RUN_DIR=${2:?--run-dir needs a path}; shift 2 ;;
    --keep-dataset) KEEP_DATASET=1; shift ;;
    -h | --help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'error: unknown argument %s\n' "$1" >&2; exit 2 ;;
  esac
done

[ -n "$RUN_DIR" ] || { printf 'error: --run-dir is required\n' >&2; exit 2; }
[ -d "$RUN_DIR" ] || { printf 'error: run directory %s does not exist\n' "$RUN_DIR" >&2; exit 2; }
RUN_DIR=$(cd "$RUN_DIR" && pwd)

manifest="$RUN_DIR/artifacts-manifest.sha256"
# An already-pruned run has nothing left to hash; rewriting an empty manifest
# would erase the hashes recorded by the first prune, so bail out instead.
if [ -f "$manifest" ] && [ -s "$manifest" ] && ! compgen -G "$RUN_DIR/dataset-*.bin" >/dev/null \
  && ! compgen -G "$RUN_DIR/artifacts/*" >/dev/null; then
  printf 'already pruned: %s\nmanifest=%s\n' "$RUN_DIR" "$manifest"
  exit 0
fi

before=$(du -sk "$RUN_DIR" | awk '{print $1}')

: >"$manifest"
# Record hashes before deleting, so the report keeps a verifiable reference.
for target in "$RUN_DIR"/dataset-*.bin "$RUN_DIR"/artifacts/*; do
  [ -f "$target" ] || continue
  relative=${target#"$RUN_DIR"/}
  printf '%s  %s\n' "$(file_sha256 "$target")" "$relative" >>"$manifest"
done

[ "$KEEP_DATASET" -eq 1 ] || rm -f "$RUN_DIR"/dataset-*.bin
if [ -d "$RUN_DIR/artifacts" ]; then
  find "$RUN_DIR/artifacts" -maxdepth 1 -type f ! -name '.gitkeep' -delete
fi

# Mark the run as pruned so the report can say why the files are gone.
if [ -f "$RUN_DIR/meta.json" ]; then
  python3 - "$RUN_DIR/meta.json" "$(basename "$manifest")" <<'PY'
import json
import sys

path, manifest_name = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    meta = json.load(handle)
meta["artifacts_pruned"] = True
meta["artifact_manifest"] = manifest_name
with open(path, "w", encoding="utf-8") as handle:
    json.dump(meta, handle, ensure_ascii=False, sort_keys=True, indent=2)
    handle.write("\n")
PY
fi

if [ -f "$RUN_DIR/report.md" ] && [ -f "$RUN_DIR/meta.json" ]; then
  python3 "$SCRIPT_DIR/render_report.py" \
    --env "$RUN_DIR/env.json" \
    --summary "$RUN_DIR/summary.json" \
    --meta "$RUN_DIR/meta.json" \
    --out "$RUN_DIR/report.md" >/dev/null
fi

after=$(du -sk "$RUN_DIR" | awk '{print $1}')
printf 'pruned=%s\nmanifest=%s\nfreed_kib=%s\nremaining_kib=%s\n' \
  "$RUN_DIR" "$manifest" "$((before - after))" "$after"
