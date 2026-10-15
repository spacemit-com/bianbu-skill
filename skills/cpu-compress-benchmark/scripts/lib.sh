# shellcheck shell=bash
# lib.sh - shared helpers for the CPU compression benchmark skill.
# Source this file; do not execute it directly.

BENCH_NPROC=$(nproc 2>/dev/null || echo 1)

bench_die() { printf 'error: %s\n' "$*" >&2; exit 1; }
bench_warn() { printf 'warning: %s\n' "$*" >&2; }

# Milliseconds since the epoch. GNU coreutils date.
bench_now_ms() {
  # Portable milliseconds since the epoch. `date +%s%3N` is not
  # truncation-capable everywhere: coreutils on this riscv64 Bianbu image
  # ignores the %3 field width and emits "<epoch-seconds><full-nanoseconds>"
  # (e.g. 1790741312204099837), which makes every wall_ms ~1e6 too large and
  # zeroes out every MiB/s column. Prefer %s%N and divide explicitly.
  local n
  n=$(date +%s%N 2>/dev/null)
  case "$n" in
    '' | *[!0-9]*)
      python3 -c 'import time; print(int(time.time() * 1000))' 2>/dev/null || date +%s000
      ;;
    *) echo $((n / 1000000)) ;;
  esac
}

# Canonical codec name -> executable checked with command -v.
codec_tool() {
  case "$1" in
    gzip) echo gzip ;;
    pigz) echo pigz ;;
    zstd) echo zstd ;;
    xz) echo xz ;;
    bzip2) echo bzip2 ;;
    *) echo "" ;;
  esac
}

# File extension for the produced archive.
codec_ext() {
  case "$1" in
    gzip | pigz) echo gz ;;
    zstd) echo zst ;;
    xz) echo xz ;;
    bzip2) echo bz2 ;;
    *) echo bin ;;
  esac
}

# Whether the codec has a real multi-threaded mode in its own CLI.
codec_is_threaded() {
  case "$1" in
    pigz | zstd | xz) return 0 ;;
    *) return 1 ;;
  esac
}

# Compression level used when the caller does not pin one.
codec_default_level() {
  case "$1" in
    gzip | pigz) echo 6 ;;
    zstd) echo 3 ;;
    xz) echo 6 ;;
    bzip2) echo 9 ;;
    *) echo 6 ;;
  esac
}

# Documented level range, used for reporting only.
codec_level_range() {
  case "$1" in
    gzip | pigz) echo "1-9" ;;
    zstd) echo "1-19" ;;
    xz) echo "0-9" ;;
    bzip2) echo "1-9" ;;
    *) echo "?" ;;
  esac
}

# Threads actually handed to the tool: 0 means "all cores" and becomes 1 for
# single-threaded codecs, which have no parallel mode at all.
codec_threads_applied() {
  local codec=$1 threads=$2
  if ! codec_is_threaded "$codec"; then
    echo 1
    return
  fi
  if [ "$threads" = "0" ]; then
    echo "$BENCH_NPROC"
  else
    echo "$threads"
  fi
}

# One-line note describing the threading model of the codec.
codec_thread_note() {
  local codec=$1
  if codec_is_threaded "$codec"; then
    case "$codec" in
      pigz) echo "multi-threaded gzip implementation (zlib blocks in parallel)" ;;
      zstd) echo "multi-threaded via --threads on independent frames/blocks" ;;
      xz) echo "multi-threaded via -T with larger block size, which changes the output bytes" ;;
    esac
  else
    echo "single-threaded by design; it has no parallel mode"
  fi
}

# Build the compression command in the global CMD array.
# The caller redirects stdout to the archive path.
build_compress_cmd() {
  local codec=$1 level=$2 threads=$3 in=$4
  case "$codec" in
    gzip) CMD=(gzip "-$level" -c -n "$in") ;;
    pigz) CMD=(pigz "-$level" -p "$threads" -c -n "$in") ;;
    zstd) CMD=(zstd -q "-$level" "--threads=$threads" -c "$in") ;;
    xz) CMD=(xz "-$level" -T "$threads" -c "$in") ;;
    bzip2) CMD=(bzip2 "-$level" -c "$in") ;;
    *) return 1 ;;
  esac
}

# Build the decompression command in the global CMD array.
# The caller redirects stdout to /dev/null for timing, or to a file to verify.
build_decompress_cmd() {
  local codec=$1 threads=$2 artifact=$3
  case "$codec" in
    gzip) CMD=(gzip -dc "$artifact") ;;
    pigz) CMD=(pigz -dc -p "$threads" "$artifact") ;;
    zstd) CMD=(zstd -q -dc "--threads=$threads" "$artifact") ;;
    xz) CMD=(xz -dc -T "$threads" "$artifact") ;;
    bzip2) CMD=(bzip2 -dc "$artifact") ;;
    *) return 1 ;;
  esac
}

# First line of the tool's version output, trimmed.
codec_version() {
  local tool=$1
  case "$tool" in
    pigz) pigz --version 2>&1 | head -n 1 | tr -s ' ' ;;
    zstd) zstd --version 2>&1 | head -n 1 ;;
    *) "$tool" --version 2>&1 | head -n 1 ;;
  esac
}

# sha256 of a file, or "unavailable".
file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "unavailable"
  fi
}
