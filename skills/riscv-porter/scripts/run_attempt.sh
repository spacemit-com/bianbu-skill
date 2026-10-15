#!/bin/sh
set -u

project=.
label=attempt
build_cmd=
test_cmd=
build_timeout=
test_timeout=
log_dir=.riscv-porter/logs

while [ "$#" -gt 0 ]; do
  case "$1" in
    --project) project=$2; shift 2 ;;
    --label) label=$2; shift 2 ;;
    --build) build_cmd=$2; shift 2 ;;
    --test) test_cmd=$2; shift 2 ;;
    --build-timeout) build_timeout=$2; shift 2 ;;
    --test-timeout) test_timeout=$2; shift 2 ;;
    --log-dir) log_dir=$2; shift 2 ;;
    *) echo "错误：未知参数：$1" >&2; exit 2 ;;
  esac
done

if [ -z "$build_cmd" ]; then
  echo "错误：必须提供 --build" >&2
  exit 2
fi
if [ ! -d "$project" ]; then
  echo "错误：项目目录不存在：$project" >&2
  exit 2
fi
case "$label" in
  *[!A-Za-z0-9._-]*|'') echo "错误：--label 只能包含字母、数字、点、下划线和连字符" >&2; exit 2 ;;
esac
for timeout_value in "$build_timeout" "$test_timeout"; do
  case "$timeout_value" in
    '') ;;
    *[!0-9]*|0) echo "错误：timeout 必须是正整数秒" >&2; exit 2 ;;
  esac
done
if { [ -n "$build_timeout" ] || [ -n "$test_timeout" ]; } && ! command -v timeout >/dev/null 2>&1; then
  echo "错误：当前系统缺少 timeout，无法执行有界阶段" >&2
  exit 2
fi

mkdir -p "$project/$log_dir"
build_log="$project/$log_dir/build-$label.log"
test_log="$project/$log_dir/test-$label.log"

echo "attempt=$label phase=build command=$build_cmd"
start=$(date +%s)
if [ -n "$build_timeout" ]; then
  echo "attempt=$label phase=build timeout_seconds=$build_timeout"
  (cd "$project" && timeout --signal=TERM --kill-after=5 "$build_timeout" sh -c "$build_cmd") >"$build_log" 2>&1
else
  (cd "$project" && sh -c "$build_cmd") >"$build_log" 2>&1
fi
build_rc=$?
elapsed=$(($(date +%s) - start))
echo "attempt=$label phase=build exit=$build_rc elapsed_seconds=$elapsed log=$build_log"
if [ "$build_rc" -ne 0 ]; then
  tail -40 "$build_log" >&2 || true
  echo "action_required=inspect-classify-patch" >&2
  exit "$build_rc"
fi

if [ -z "$test_cmd" ]; then
  exit 0
fi

echo "attempt=$label phase=test command=$test_cmd"
start=$(date +%s)
if [ -n "$test_timeout" ]; then
  echo "attempt=$label phase=test timeout_seconds=$test_timeout"
  (cd "$project" && timeout --signal=TERM --kill-after=5 "$test_timeout" sh -c "$test_cmd") >"$test_log" 2>&1
else
  (cd "$project" && sh -c "$test_cmd") >"$test_log" 2>&1
fi
test_rc=$?
elapsed=$(($(date +%s) - start))
echo "attempt=$label phase=test exit=$test_rc elapsed_seconds=$elapsed log=$test_log"
if [ "$test_rc" -ne 0 ]; then
  tail -40 "$test_log" >&2 || true
  echo "action_required=inspect-classify-patch" >&2
fi
exit "$test_rc"
