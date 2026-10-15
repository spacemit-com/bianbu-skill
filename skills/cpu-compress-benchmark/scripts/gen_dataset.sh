#!/usr/bin/env bash
# gen_dataset.sh - build the benchmark input file from a reproducible recipe.
#
# Categories are shaped to expose different compressor weaknesses:
#   text    English prose, highly compressible, dictionary friendly
#   source  C-like source code, mixed structure and identifiers
#   json    structured records, very repetitive at the record level
#   log     timestamped log lines, repetitive with a variable tail
#   binary  pseudo-random bytes, effectively incompressible (a floor check)
#   mixed   concatenation of all of the above
#
# Usage:
#   gen_dataset.sh --out PATH --size-mib N [--category NAME] [--seed S]
#
# The generator is deterministic for a fixed seed: the same seed always
# produces the same bytes, so repeated benchmark runs compare equal inputs.
# It never downloads anything and never reads outside the output path.

set -euo pipefail

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

OUT=""
SIZE_MIB=64
CATEGORY="mixed"
SEED=20260101

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT=${2:?--out needs a path}; shift 2 ;;
    --size-mib) SIZE_MIB=${2:?--size-mib needs a number}; shift 2 ;;
    --category) CATEGORY=${2:?--category needs a name}; shift 2 ;;
    --seed) SEED=${2:?--seed needs a number}; shift 2 ;;
    -h | --help) usage 0 ;;
    *) printf 'error: unknown argument %s\n' "$1" >&2; usage 2 ;;
  esac
done

[ -n "$OUT" ] || { printf 'error: --out is required\n' >&2; exit 2; }
case "$SIZE_MIB" in
  '' | *[!0-9]*) printf 'error: --size-mib must be a positive integer\n' >&2; exit 2 ;;
esac
[ "$SIZE_MIB" -gt 0 ] || { printf 'error: --size-mib must be greater than zero\n' >&2; exit 2; }
[ "$SIZE_MIB" -le 4096 ] || { printf 'error: --size-mib above 4096 is not supported by this skill\n' >&2; exit 2; }

case "$CATEGORY" in
  text | source | json | log | binary | mixed) ;;
  *) printf 'error: unknown --category %s (text|source|json|log|binary|mixed)\n' "$CATEGORY" >&2; exit 2 ;;
esac

mkdir -p "$(dirname "$OUT")"

python3 - "$OUT" "$SIZE_MIB" "$CATEGORY" "$SEED" <<'PY'
import json
import random
import sys

path, size_mib, category, seed = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
target = size_mib * 1024 * 1024
rng = random.Random(seed)

WORDS = (
    "system kernel buffer stream packet latency throughput scheduler memory page cache "
    "thread lock queue signal socket protocol header payload checksum segment index range "
    "table record column schema query update delete commit rollback snapshot replica cluster "
    "node region bucket object storage volume mount device driver interrupt vector register "
    "measure baseline profile report sample average variance percentile histogram threshold"
).split()

SUBSYSTEMS = ["http", "auth", "storage", "scheduler", "rpc", "cache", "billing", "search", "ingest", "worker"]
LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]


def text_chunk() -> bytes:
    out = []
    length = 0
    while length < 4096:
        words = rng.choices(WORDS, k=rng.randint(6, 16))
        sentence = " ".join(words).capitalize() + rng.choice([".", ".", ".", "!", "?", ";"])
        out.append(sentence)
        length += len(sentence)
    return (" ".join(out) + "\n").encode()


def source_chunk() -> bytes:
    out = []
    for _ in range(rng.randint(8, 20)):
        name = rng.choice(WORDS) + str(rng.randint(0, 99))
        other = rng.choice(WORDS)
        body = rng.choice(
            [
                "    unsigned long %s = 0;" % name,
                "    if (%s > %s_limit) {" % (name, other),
                "    /* %s must stay %d-byte aligned for %s */" % (name, rng.choice([4, 8, 16, 64]), other),
                "    }",
                "    return (%s) ? %s_get(%s) : -1;" % (name, other, name),
                "    struct %s_entry *entry = %s_lookup(&%s_table, %s);" % (other, other, name, name),
            ]
        )
        out.append(body)
    return ("\n".join(out) + "\n").encode()


def json_chunk() -> bytes:
    lines = []
    for _ in range(rng.randint(6, 14)):
        record = {
            "ts": rng.randint(1700000000, 1800000000),
            "level": rng.choice(LEVELS),
            "service": rng.choice(SUBSYSTEMS),
            "latency_us": rng.randint(40, 90000),
            "bytes_in": rng.randint(64, 1 << 20),
            "bytes_out": rng.randint(64, 1 << 20),
            "shard": rng.randint(0, 63),
            "trace": "%032x" % rng.getrandbits(128),
            "ok": rng.random() > 0.05,
        }
        lines.append(json.dumps(record, separators=(",", ":")))
    return ("\n".join(lines) + "\n").encode()


def log_chunk() -> bytes:
    lines = []
    for _ in range(rng.randint(10, 24)):
        lines.append(
            "2026-01-%02dT%02d:%02d:%02d.%03dZ %-5s %-10s %s=%d %s"
            % (
                rng.randint(1, 28),
                rng.randint(0, 23),
                rng.randint(0, 59),
                rng.randint(0, 59),
                rng.randint(0, 999),
                rng.choice(LEVELS),
                rng.choice(SUBSYSTEMS),
                rng.choice(WORDS),
                rng.randint(0, 1 << 20),
                rng.choice(WORDS),
            )
        )
    return ("\n".join(lines) + "\n").encode()


def binary_chunk() -> bytes:
    return rng.randbytes(4096)


GENERATORS = {
    "text": text_chunk,
    "source": source_chunk,
    "json": json_chunk,
    "log": log_chunk,
    "binary": binary_chunk,
}
MIXED_CYCLE = ["text", "source", "json", "log", "text", "binary"]

written = 0
step = 0
with open(path, "wb") as handle:
    while written < target:
        if category == "mixed":
            kind = MIXED_CYCLE[step % len(MIXED_CYCLE)]
        else:
            kind = category
        chunk = GENERATORS[kind]()
        remaining = target - written
        if remaining < len(chunk):
            chunk = chunk[:remaining]
        handle.write(chunk)
        written += len(chunk)
        step += 1
PY

printf 'dataset=%s category=%s size_mib=%s seed=%s\n' "$OUT" "$CATEGORY" "$SIZE_MIB" "$SEED"
