#!/usr/bin/env bash
# collect_env.sh - record the machine and toolchain context for a benchmark run.
#
# Usage:
#   collect_env.sh --out <env.json> --outdir <run-dir> [--codecs "gzip pigz ..."]
#
# Writes env.json for the report renderer and <run-dir>/env-snapshot.txt for a
# human-readable trace. The snapshot is deliberately verbose: a throughput
# number without the CPU, kernel, governor and tool versions is not a result.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

OUT=""
OUTDIR=""
CODECS="gzip pigz zstd xz bzip2"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT=${2:?--out needs a path}; shift 2 ;;
    --outdir) OUTDIR=${2:?--outdir needs a path}; shift 2 ;;
    --codecs) CODECS=${2:?--codecs needs a list}; shift 2 ;;
    -h | --help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf 'error: unknown argument %s\n' "$1" >&2; exit 2 ;;
  esac
done

[ -n "$OUT" ] || { printf 'error: --out is required\n' >&2; exit 2; }
[ -n "$OUTDIR" ] || { printf 'error: --outdir is required\n' >&2; exit 2; }
mkdir -p "$(dirname "$OUT")" "$OUTDIR"

cpu_model=$(awk -F': ' '/^model name/ {print $2; exit}' /proc/cpuinfo 2>/dev/null || true)
[ -n "$cpu_model" ] || cpu_model=$(lscpu 2>/dev/null | awk -F': *' '/Model name/ {print $2; exit}' || true)
cpu_model=${cpu_model:-unknown}

arch=$(uname -m)
logical=$(nproc 2>/dev/null || echo 1)
physical=$(lscpu 2>/dev/null | awk -F': *' '/^Core\(s\) per socket/ {print $2; exit}' || true)
[ -n "$physical" ] || physical=""
sockets=$(lscpu 2>/dev/null | awk -F': *' '/^Socket\(s\)/ {print $2; exit}' || true)
if [ -n "$physical" ] && [ -n "$sockets" ]; then
  physical=$((physical * sockets))
else
  physical=""
fi

threads_per_core=$(lscpu 2>/dev/null | awk -F': *' '/^Thread\(s\) per core/ {print $2; exit}' || true)
max_mhz=$(lscpu 2>/dev/null | awk -F': *' '/^CPU max MHz/ {print $2; exit}' || true)
[ -n "$max_mhz" ] || max_mhz=$(awk -F': ' '/^cpu MHz/ {print $2; exit}' /proc/cpuinfo 2>/dev/null || true)
max_mhz=$(printf '%s' "${max_mhz:-}" | awk '{printf "%.0f", $1}' 2>/dev/null || true)
[ -n "$max_mhz" ] || max_mhz=0

l3=$(lscpu 2>/dev/null | awk -F': *' '/^L3 cache/ {print $2; exit}' || true)
governor=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo "unknown")
mem_total_kib=$(awk '/^MemTotal/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)
mem_total_mib=$((mem_total_kib / 1024))
kernel=$(uname -sr)
os=$(. /etc/os-release 2>/dev/null && printf '%s %s' "$NAME" "$VERSION_ID" || echo unknown)
[ -n "$os" ] || os=unknown

# Turbo is not readable everywhere; report what cpufreq exposes without guessing.
no_turbo="unknown"
for candidate in /sys/devices/system/cpu/intel_pstate/no_turbo /sys/devices/system/cpu/cpufreq/boost; do
  if [ -r "$candidate" ]; then
    value=$(cat "$candidate")
    case "$candidate" in
      */no_turbo) [ "$value" = "0" ] && no_turbo="enabled" || no_turbo="disabled" ;;
      */boost) [ "$value" = "1" ] && no_turbo="enabled" || no_turbo="disabled" ;;
    esac
    break
  fi
done

# Record whether the filesystem under the run directory is a RAM-backed one:
# tmpfs removes disk writes from the measurement, which the report must state.
run_fs_type=$(stat -f -c '%T' "$OUTDIR" 2>/dev/null || echo unknown)
run_fs_mount=$(df -P "$OUTDIR" 2>/dev/null | awk 'NR==2 {print $6}' || echo unknown)

tools_json="{}"
tools_txt=""
for codec in $CODECS; do
  tool=$(codec_tool "$codec")
  if [ -n "$tool" ] && command -v "$tool" >/dev/null 2>&1; then
    path=$(command -v "$tool")
    version=$(codec_version "$tool")
    level=$(codec_default_level "$codec")
    range=$(codec_level_range "$codec")
    applied_note=$(codec_thread_note "$codec")
    entry=$(printf '{"path":%s,"version":%s,"available":true,"default_level":"%s","level_range":"%s","thread_note":%s}' \
      "$(printf '%s' "$path" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
      "$(printf '%s' "$version" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
      "$level" "$range" \
      "$(printf '%s' "$applied_note" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")
    tools_json=$(python3 -c '
import json, sys
base = json.loads(sys.argv[1])
base[sys.argv[2]] = json.loads(sys.argv[3])
print(json.dumps(base, ensure_ascii=False, sort_keys=True))
' "$tools_json" "$codec" "$entry")
    tools_txt="${tools_txt}$(printf '%-8s %-28s %s (default level %s, range %s)\n' "$codec" "$path" "$version" "$level" "$range")"$'\n'
  else
    entry='{"available":false}'
    tools_json=$(python3 -c '
import json, sys
base = json.loads(sys.argv[1])
base[sys.argv[2]] = json.loads(sys.argv[3])
print(json.dumps(base, ensure_ascii=False, sort_keys=True))
' "$tools_json" "$codec" "$entry")
    tools_txt="${tools_txt}$(printf '%-8s %s\n' "$codec" "not installed (skipped)")"$'\n'
  fi
done

python3 - "$OUT" <<PY
import json, sys

env = {
    "cpu_model": $(printf '%s' "$cpu_model" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
    "architecture": "$arch",
    "logical_cpus": int("$logical"),
    "physical_cores": ${physical:-0},
    "threads_per_core": ${threads_per_core:-0},
    "max_mhz": int(float("$max_mhz")),
    "l3_cache": $(printf '%s' "$l3" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
    "scaling_governor": "$governor",
    "turbo": "$no_turbo",
    "mem_total_mib": int("$mem_total_mib"),
    "kernel": $(printf '%s' "$kernel" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
    "os": $(printf '%s' "$os" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
    "filesystem_type": "$run_fs_type",
    "filesystem_mount": $(printf '%s' "$run_fs_mount" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),
    "tools": json.loads('''$tools_json'''),
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(json.dumps(env, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
PY

{
  printf 'cpu_model=%s\n' "$cpu_model"
  printf 'architecture=%s\n' "$arch"
  printf 'logical_cpus=%s physical_cores=%s threads_per_core=%s\n' "$logical" "${physical:-unknown}" "${threads_per_core:-unknown}"
  printf 'max_mhz=%s l3_cache=%s\n' "$max_mhz" "${l3:-unknown}"
  printf 'scaling_governor=%s turbo=%s\n' "$governor" "$no_turbo"
  printf 'memory_total_mib=%s\n' "$mem_total_mib"
  printf 'kernel=%s\nos=%s\n' "$kernel" "$os"
  printf 'run_filesystem=%s mount=%s\n' "$run_fs_type" "$run_fs_mount"
  printf -- '--- tools ---\n%s' "$tools_txt"
} >"$OUTDIR/env-snapshot.txt"

printf 'env=%s snapshot=%s\n' "$OUT" "$OUTDIR/env-snapshot.txt"
