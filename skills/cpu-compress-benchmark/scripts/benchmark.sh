#!/usr/bin/env bash
# benchmark.sh - run the CPU compression/decompression benchmark end to end.
#
# Usage:
#   benchmark.sh [--codecs "gzip pigz zstd xz bzip2"] [--levels "1,6,9"]
#                [--threads "1,0"] [--size-mib 128] [--category mixed]
#                [--repeats 1] [--warmup 1] [--seed 20260101]
#                [--affinity "0-3"] [--label NAME] [--run-dir DIR]
#
# Steps: generate the dataset, snapshot the environment, time every
# codec x level x thread configuration, aggregate the measurements, and render
# a structured Markdown report next to its machine-readable evidence.
#
# The defaults are tuned for a short run: one timed pass per configuration
# (--repeats 1) over a 128 MiB dataset. A single pass still yields throughput,
# ratio, CPU time, peak memory and round-trip verification. Raise --repeats
# (and usually --size-mib) when you need the run-to-run spread, which is the
# only thing a single pass cannot show.
#
# Threads: 0 means one worker per logical CPU. Codecs without a parallel mode
# are always reported with the requested count in parentheses.
# Levels: omitted or "default" uses each codec's own default level.
#
# Exit status is 0 when the run completed and every configuration verified,
# 4 when at least one configuration failed, and 2 for a usage error. The
# report and its evidence are written even on failure.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

CODECS=""
LEVELS="default"
THREADS="0"
SIZE_MIB=128
CATEGORY=mixed
REPEATS=1
WARMUP=1
SEED=20260101
AFFINITY=""
LABEL=default
RUN_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --codecs) CODECS=${2:?}; shift 2 ;;
    --levels) LEVELS=${2:?}; shift 2 ;;
    --threads) THREADS=${2:?}; shift 2 ;;
    --size-mib) SIZE_MIB=${2:?}; shift 2 ;;
    --category) CATEGORY=${2:?}; shift 2 ;;
    --repeats) REPEATS=${2:?}; shift 2 ;;
    --warmup) WARMUP=${2:?}; shift 2 ;;
    --seed) SEED=${2:?}; shift 2 ;;
    --affinity) AFFINITY=${2:?}; shift 2 ;;
    --label) LABEL=${2:?}; shift 2 ;;
    --run-dir) RUN_DIR=${2:?}; shift 2 ;;
    -h | --help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'error: unknown argument %s\n' "$1" >&2; exit 2 ;;
  esac
done

case "$REPEATS" in '' | *[!0-9]*) printf 'error: --repeats must be an integer\n' >&2; exit 2 ;; esac
[ "$REPEATS" -ge 1 ] || { printf 'error: --repeats must be at least 1\n' >&2; exit 2; }
case "$WARMUP" in '' | *[!0-9]*) printf 'error: --warmup must be an integer\n' >&2; exit 2 ;; esac
case "$SIZE_MIB" in '' | *[!0-9]*) printf 'error: --size-mib must be an integer\n' >&2; exit 2 ;; esac
[ "$SIZE_MIB" -ge 1 ] || { printf 'error: --size-mib must be at least 1\n' >&2; exit 2; }

# Default codec set: the documented order, minus anything not installed.
if [ -z "$CODECS" ]; then
  CODECS=""
  for candidate in gzip pigz zstd xz bzip2; do
    tool=$(codec_tool "$candidate")
    if command -v "$tool" >/dev/null 2>&1; then
      CODECS="${CODECS:+$CODECS }$candidate"
    else
      bench_warn "$candidate is not installed; leaving it out of the run"
    fi
  done
fi
[ -n "$CODECS" ] || { printf 'error: no usable codec found; install one of gzip, pigz, zstd, xz, bzip2\n' >&2; exit 2; }

# Validate every requested codec and level before touching the disk.
for codec in $CODECS; do
  tool=$(codec_tool "$codec")
  [ -n "$tool" ] || { printf 'error: unknown codec %s\n' "$codec" >&2; exit 2; }
  command -v "$tool" >/dev/null 2>&1 || { printf 'error: codec %s (%s) is not installed\n' "$codec" "$tool" >&2; exit 2; }
done
if [ "$LEVELS" != "default" ]; then
  for level in $(printf '%s' "$LEVELS" | tr ',' ' '); do
    case "$level" in '' | *[!0-9]*) printf 'error: level %s is not an integer\n' "$level" >&2; exit 2 ;; esac
  done
fi
for threads in $(printf '%s' "$THREADS" | tr ',' ' '); do
  case "$threads" in '' | *[!0-9]*) printf 'error: threads %s is not an integer\n' "$threads" >&2; exit 2 ;; esac
done

if [ -z "$RUN_DIR" ]; then
  RUN_DIR="./benchmark-run-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$RUN_DIR"
RUN_DIR=$(cd "$RUN_DIR" && pwd)
RUN_ID=$(basename "$RUN_DIR")
DATASET="$RUN_DIR/dataset-$CATEGORY-$SIZE_MIB""MiB.bin"
STARTED_AT=$(date -Iseconds)

mkdir -p "$RUN_DIR/raw" "$RUN_DIR/artifacts" "$RUN_DIR/tmp"
: >"$RUN_DIR/raw/measurements.jsonl"

printf 'run_dir=%s\n' "$RUN_DIR"

"$SCRIPT_DIR/gen_dataset.sh" --out "$DATASET" --size-mib "$SIZE_MIB" --category "$CATEGORY" --seed "$SEED"
"$SCRIPT_DIR/collect_env.sh" --out "$RUN_DIR/env.json" --outdir "$RUN_DIR" --codecs "$CODECS"

thread_list=$(printf '%s' "$THREADS" | tr ',' ' ')
for codec in $CODECS; do
  if [ "$LEVELS" = "default" ]; then
    level_list=$(codec_default_level "$codec")
  else
    level_list=$(printf '%s' "$LEVELS" | tr ',' ' ')
  fi
  for level in $level_list; do
    for threads in $thread_list; do
      "$SCRIPT_DIR/run_codec.sh" \
        --codec "$codec" \
        --dataset "$DATASET" \
        --outdir "$RUN_DIR" \
        --level "$level" \
        --threads "$threads" \
        --repeats "$REPEATS" \
        --warmup "$WARMUP" \
        --affinity "$AFFINITY" \
        --label "$LABEL" || bench_warn "$codec level $level threads $threads reported a failure; continuing"
    done
  done
done

FINISHED_AT=$(date -Iseconds)

python3 "$SCRIPT_DIR/summarize.py" \
  "$RUN_DIR/raw/measurements.jsonl" \
  "$RUN_DIR/summary.json" \
  "$RUN_DIR/summary.csv"

python3 - "$RUN_DIR/meta.json" \
  "$RUN_ID" "$STARTED_AT" "$FINISHED_AT" "$RUN_DIR" "$DATASET" "$SIZE_MIB" \
  "$CATEGORY" "$SEED" "$CODECS" "$LEVELS" "$THREADS" "$REPEATS" "$WARMUP" \
  "$AFFINITY" "$LABEL" "$SCRIPT_DIR" <<'PY'
import json
import sys

(path, run_id, started_at, finished_at, run_dir, dataset, size_mib, category,
 seed, codecs, levels, threads, repeats, warmup, affinity, label, script_dir) = sys.argv[1:]

affinity_flag = f' --affinity "{affinity}"' if affinity else ""
label_flag = f' --label "{label}"' if label != "default" else ""
reproduce = (
    f'{script_dir}/benchmark.sh --run-dir "{run_dir}" --codecs "{codecs}" '
    f'--levels "{levels}" --threads "{threads}" --size-mib {size_mib} '
    f'--category {category} --repeats {repeats} --warmup {warmup} --seed {seed}'
    f'{affinity_flag}{label_flag}'
)

meta = {
    "run_id": run_id,
    "started_at": started_at,
    "finished_at": finished_at,
    "run_dir": run_dir,
    "dataset": dataset,
    "dataset_mib": int(size_mib),
    "category": category,
    "seed": int(seed),
    "codecs": codecs.split(),
    "levels": levels,
    "threads": threads,
    "repeats": int(repeats),
    "warmup": int(warmup),
    "affinity": affinity,
    "label": label,
    "reproduce": [
        reproduce,
        f'{script_dir}/summarize.py "{run_dir}/raw/measurements.jsonl" "{run_dir}/summary.json" "{run_dir}/summary.csv"',
        f'{script_dir}/render_report.py --env "{run_dir}/env.json" --summary "{run_dir}/summary.json" --meta "{run_dir}/meta.json" --out "{run_dir}/report.md"',
    ],
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(meta, handle, ensure_ascii=False, sort_keys=True, indent=2)
    handle.write("\n")
PY

python3 "$SCRIPT_DIR/render_report.py" \
  --env "$RUN_DIR/env.json" \
  --summary "$RUN_DIR/summary.json" \
  --meta "$RUN_DIR/meta.json" \
  --out "$RUN_DIR/report.md"

rmdir "$RUN_DIR/tmp" 2>/dev/null || true

failures=$(python3 -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print(sum(group.get("failures", 0) for group in data["groups"]))
' "$RUN_DIR/summary.json")

printf '\nrun_dir=%s\nreport=%s\nsummary=%s\nraw=%s\nfailures=%s\n' \
  "$RUN_DIR" "$RUN_DIR/report.md" "$RUN_DIR/summary.json" "$RUN_DIR/raw/measurements.jsonl" "$failures"

[ "$failures" -eq 0 ] || exit 4
