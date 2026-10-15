#!/usr/bin/env bash
set -euo pipefail

project=${1:-.}
base=${2:-HEAD}

if [[ ! -d "$project" ]]; then
  echo "错误：项目目录不存在：$project" >&2
  exit 2
fi
if ! git -C "$project" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "错误：不是 Git 工作区：$project" >&2
  exit 2
fi
if ! git -C "$project" rev-parse --verify "$base^{commit}" >/dev/null 2>&1; then
  echo "错误：无法解析基线 revision：$base" >&2
  exit 2
fi

tracked_added=0
tracked_deleted=0
tracked_binary=0
while IFS=$'\t' read -r added deleted _path; do
  [[ -n "${added:-}" ]] || continue
  if [[ "$added" == "-" || "$deleted" == "-" ]]; then
    tracked_binary=$((tracked_binary + 1))
  else
    tracked_added=$((tracked_added + added))
    tracked_deleted=$((tracked_deleted + deleted))
  fi
done < <(git -C "$project" diff --numstat "$base" --)

untracked_total=0
deliverable_files=0
deliverable_lines=0
generated_files=0
other_files=0
declare -a deliverables=()
declare -a generated=()
declare -a other=()

is_generated() {
  case "$1" in
    .riscv-porter/*|_port/*|riscv-port-report.md|build/*|build-*/*|out/*|cmake-build-*/*|*.o|*.a|*.so|*.so.*|*.dylib|*.dll|*.exe|*.class|*.pyc)
      return 0 ;;
    *) return 1 ;;
  esac
}

is_text_deliverable() {
  case "$1" in
    Makefile|GNUmakefile|CMakeLists.txt|meson.build|*.c|*.cc|*.cpp|*.cxx|*.h|*.hh|*.hpp|*.S|*.s|*.rs|*.go|*.py|*.sh|*.cmake|*.mk|*.toml|*.yaml|*.yml|*.json|*.md|*.txt)
      return 0 ;;
    *) return 1 ;;
  esac
}

while IFS= read -r -d '' file; do
  untracked_total=$((untracked_total + 1))
  if is_generated "$file"; then
    generated_files=$((generated_files + 1))
    generated+=("$file")
  elif is_text_deliverable "$file"; then
    deliverable_files=$((deliverable_files + 1))
    lines=$(wc -l < "$project/$file")
    deliverable_lines=$((deliverable_lines + lines))
    deliverables+=("$file")
  else
    other_files=$((other_files + 1))
    other+=("$file")
  fi
done < <(git -C "$project" ls-files --others --exclude-standard -z)

echo "audit.base=$base"
echo "audit.tracked.added_lines=$tracked_added"
echo "audit.tracked.deleted_lines=$tracked_deleted"
echo "audit.tracked.binary_files=$tracked_binary"
echo "audit.untracked.total_files=$untracked_total"
echo "audit.untracked.deliverable_files=$deliverable_files"
echo "audit.untracked.deliverable_lines=$deliverable_lines"
echo "audit.untracked.generated_files=$generated_files"
echo "audit.untracked.other_files=$other_files"

for file in "${deliverables[@]}"; do
  echo "audit.file.deliverable=$file"
done
for file in "${generated[@]}"; do
  echo "audit.file.generated=$file"
done
for file in "${other[@]}"; do
  echo "audit.file.other=$file"
done
