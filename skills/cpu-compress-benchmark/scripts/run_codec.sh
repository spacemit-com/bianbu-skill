#!/usr/bin/env bash
# run_codec.sh - time one codec against one dataset and emit raw JSONL rows.
#
# Usage:
#   run_codec.sh --codec zstd --dataset D --outdir RUN \
#                [--level N] [--threads N|0] [--repeats N] [--warmup N]
#                [--affinity 0-3] [--label NAME]
#
# threads 0 means "one thread per logical CPU". Codecs without a parallel mode
# always run single-threaded and say so in the row.
#
# repeats defaults to 1 so a quick run stays quick; each extra repeat exists to
# measure the run-to-run spread, not to make a single number more accurate.
#
# Measurements per repeat
#   compress    wall_ms, tool_seconds, rss_max_kib, in_bytes, out_bytes
#   decompress  wall_ms, tool_seconds, rss_max_kib, out_bytes (streamed to /dev/null)
#
# The wall clock comes from bench_now_ms (epoch milliseconds, derived from
# date +%s%N) around the process, which includes fork/exec overhead;
# tool_seconds comes from /usr/bin/time and excludes it.
# Both are recorded so the report can show the reconciliation instead of
# hiding it. max RSS is the peak resident set of the tool process, in KiB.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"
EMIT="$SCRIPT_DIR/emit_row.py"

CODEC=""
DATASET=""
OUTDIR=""
LEVEL=""
THREADS=0
REPEATS=1
WARMUP=1
AFFINITY=""
LABEL=""

while [ $# -gt 0 ]; do
  case "$1" in
    --codec) CODEC=${2:?}; shift 2 ;;
    --dataset) DATASET=${2:?}; shift 2 ;;
    --outdir) OUTDIR=${2:?}; shift 2 ;;
    --level) LEVEL=${2:?}; shift 2 ;;
    --threads) THREADS=${2:?}; shift 2 ;;
    --repeats) REPEATS=${2:?}; shift 2 ;;
    --warmup) WARMUP=${2:?}; shift 2 ;;
    --affinity)
      # Optional: an empty value means "do not pin".
      AFFINITY=${2:-}
      if [ $# -ge 2 ]; then shift 2; else shift 1; fi
      ;;
    --label) LABEL=${2:?}; shift 2 ;;
    -h | --help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'error: unknown argument %s\n' "$1" >&2; exit 2 ;;
  esac
done

[ -n "$CODEC" ] || { printf 'error: --codec is required\n' >&2; exit 2; }
[ -n "$DATASET" ] || { printf 'error: --dataset is required\n' >&2; exit 2; }
[ -n "$OUTDIR" ] || { printf 'error: --outdir is required\n' >&2; exit 2; }
[ -f "$DATASET" ] || { printf 'error: dataset %s does not exist\n' "$DATASET" >&2; exit 2; }

tool=$(codec_tool "$CODEC")
[ -n "$tool" ] || { printf 'error: unknown codec %s\n' "$CODEC" >&2; exit 2; }
command -v "$tool" >/dev/null 2>&1 || { printf 'error: %s is not installed; skipping is the caller\x27s job\n' "$tool" >&2; exit 3; }

[ -n "$LEVEL" ] || LEVEL=$(codec_default_level "$CODEC")
threads_applied=$(codec_threads_applied "$CODEC" "$THREADS")
ext=$(codec_ext "$CODEC")

mkdir -p "$OUTDIR/artifacts" "$OUTDIR/raw" "$OUTDIR/tmp"
ROWS="$OUTDIR/raw/measurements.jsonl"
# The artifact name carries the requested thread count, so two configurations
# of a codec that cannot run in parallel still get distinct, inspectable files.
artifact="$OUTDIR/artifacts/${CODEC}-L${LEVEL}-T${THREADS}.${ext}"
timefile=$(mktemp "$OUTDIR/tmp/time.XXXXXX")
verifyfile=$(mktemp "$OUTDIR/tmp/verify.XXXXXX")

time_bin=""
if command -v /usr/bin/time >/dev/null 2>&1; then
  time_bin=/usr/bin/time
else
  bench_warn "/usr/bin/time not found; max RSS will be recorded as -1"
fi

in_bytes=$(stat -c '%s' "$DATASET")
data_mib=$(python3 -c "print(f'{$in_bytes/1048576:.4f}')")
dataset_sha=$(file_sha256 "$DATASET")

# Timing state filled in by timed_run.
WALL_MS=0
TOOL_S="0"
RSS_MAX_KIB=-1
EXIT_CODE=0

timed_run() {
  # timed_run <stdout-target> <cmd...>
  local out=$1
  shift
  local start end
  : >"$timefile"
  start=$(bench_now_ms)
  if [ -n "$AFFINITY" ]; then
    if [ -n "$time_bin" ]; then
      if taskset -c "$AFFINITY" "$time_bin" -f '%e %M' -o "$timefile" "$@" >"$out"; then
        EXIT_CODE=0
      else
        EXIT_CODE=$?
      fi
    else
      if taskset -c "$AFFINITY" "$@" >"$out"; then EXIT_CODE=0; else EXIT_CODE=$?; fi
    fi
  else
    if [ -n "$time_bin" ]; then
      if "$time_bin" -f '%e %M' -o "$timefile" "$@" >"$out"; then
        EXIT_CODE=0
      else
        EXIT_CODE=$?
      fi
    else
      if "$@" >"$out"; then EXIT_CODE=0; else EXIT_CODE=$?; fi
    fi
  fi
  end=$(bench_now_ms)
  WALL_MS=$((end - start))
  if [ -s "$timefile" ]; then
    TOOL_S=$(awk 'NR==1 {print $1}' "$timefile")
    RSS_MAX_KIB=$(awk 'NR==1 {print $2}' "$timefile")
    [ -n "$TOOL_S" ] || TOOL_S="0"
    [ -n "$RSS_MAX_KIB" ] || RSS_MAX_KIB=-1
  else
    TOOL_S="0"
    RSS_MAX_KIB=-1
  fi
}

row() {
  python3 "$EMIT" jsonl "$ROWS" "$@" >/dev/null
}

[ -n "$LABEL" ] || LABEL=default
common=(
  "kind:=measurement"
  "codec:=$CODEC"
  "tool:=$tool"
  "level#=$LEVEL"
  "threads#=$THREADS"
  "threads_applied#=$threads_applied"
  "thread_note:=$(codec_thread_note "$CODEC")"
  "dataset:=$DATASET"
  "dataset_sha256:=$dataset_sha"
  "in_bytes#=$in_bytes"
  "data_mib#=$data_mib"
  "affinity:=$AFFINITY"
  "label:=$LABEL"
)

# Warm the page cache so the first measured run is not a disk read.
for _ in $(seq 1 "$WARMUP"); do
  cat "$DATASET" >/dev/null
done

printf 'codec=%s level=%s threads=%s (applied %s) repeats=%s dataset=%s\n' \
  "$CODEC" "$LEVEL" "$THREADS" "$threads_applied" "$REPEATS" "$DATASET"

compress_hashes=()
failures=0

for repeat in $(seq 1 "$REPEATS"); do
  build_compress_cmd "$CODEC" "$LEVEL" "$threads_applied" "$DATASET" || {
    printf 'error: cannot build compress command for %s\n' "$CODEC" >&2
    exit 2
  }
  timed_run "$artifact" "${CMD[@]}"
  if [ "$EXIT_CODE" -ne 0 ]; then
    row "${common[@]}" "repeat#=$repeat" "phase:=compress" "status:=failed" "exit_code#=$EXIT_CODE" "wall_ms#=$WALL_MS"
    printf 'error: %s compress failed with exit %s\n' "$CODEC" "$EXIT_CODE" >&2
    failures=$((failures + 1))
    continue
  fi
  out_bytes=$(stat -c '%s' "$artifact")
  hash=$(file_sha256 "$artifact")
  compress_hashes+=("$hash")
  row "${common[@]}" "repeat#=$repeat" "phase:=compress" "status:=ok" "wall_ms#=$WALL_MS" \
    "tool_seconds=$TOOL_S" "rss_max_kib#=$RSS_MAX_KIB" "out_bytes#=$out_bytes" "artifact_sha256:=$hash"

  build_decompress_cmd "$CODEC" "$threads_applied" "$artifact" || {
    printf 'error: cannot build decompress command for %s\n' "$CODEC" >&2
    exit 2
  }
  timed_run /dev/null "${CMD[@]}"
  if [ "$EXIT_CODE" -ne 0 ]; then
    row "${common[@]}" "repeat#=$repeat" "phase:=decompress" "status:=failed" "exit_code#=$EXIT_CODE" \
      "wall_ms#=$WALL_MS" "tool_seconds=$TOOL_S" "rss_max_kib#=$RSS_MAX_KIB" "out_bytes#=$out_bytes"
    printf 'error: %s decompress failed with exit %s\n' "$CODEC" "$EXIT_CODE" >&2
    failures=$((failures + 1))
    continue
  fi
  row "${common[@]}" "repeat#=$repeat" "phase:=decompress" "status:=ok" "exit_code#=$EXIT_CODE" \
    "wall_ms#=$WALL_MS" "tool_seconds=$TOOL_S" "rss_max_kib#=$RSS_MAX_KIB" "out_bytes#=$out_bytes"
done

# Determinism: identical inputs at a fixed level/thread count should produce
# identical archives. xz -T legitimately changes output bytes with thread count.
# A single repeat cannot prove determinism, so it is reported as not applicable.
deterministic="n/a"
if [ "${#compress_hashes[@]}" -gt 1 ]; then
  deterministic="true"
  for hash in "${compress_hashes[@]}"; do
    [ "$hash" = "${compress_hashes[0]}" ] || deterministic="false"
  done
fi

# Correctness: decompress the final artifact and compare against the input.
verified="false"
output_sha=""
if [ -f "$artifact" ]; then
  if build_decompress_cmd "$CODEC" "$threads_applied" "$artifact"; then
    if "${CMD[@]}" >"$verifyfile" 2>/dev/null; then
      if cmp -s "$DATASET" "$verifyfile"; then
        verified="true"
      fi
      output_sha=$(file_sha256 "$verifyfile")
    fi
  fi
fi
rm -f "$timefile" "$verifyfile"

python3 "$EMIT" jsonl "$ROWS" "${common[@]}" "kind:=verification" "status:=ok" \
  "verified:=$verified" "deterministic:=$deterministic" "failures#=$failures" \
  "artifact:=$artifact" "artifact_sha256:=${compress_hashes[0]:-}" "output_sha256:=$output_sha" >/dev/null

printf 'codec=%s artifact=%s verified=%s deterministic=%s failures=%s\n' \
  "$CODEC" "$artifact" "$verified" "$deterministic" "$failures"

[ "$failures" -eq 0 ] || exit 4
