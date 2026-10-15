#!/bin/sh
set -eu

project=${1:-.}
if [ ! -d "$project" ]; then
  echo "error: project directory not found: $project" >&2
  exit 2
fi

echo "system.arch=$(uname -m)"
echo "system.kernel=$(uname -sr)"
if [ -r /etc/os-release ]; then
  os_name=$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release | head -1 | tr -d '"')
  echo "system.os=$os_name"
fi

for tool in cc c++ gcc g++ clang cmake make ninja meson cargo rustc go python3 file readelf; do
  if command -v "$tool" >/dev/null 2>&1; then
    path=$(command -v "$tool")
    version=$($tool --version 2>/dev/null | head -1 || true)
    echo "tool.$tool=$path | $version"
  else
    echo "tool.$tool=missing"
  fi
done

echo "compiler.macros.begin"
if command -v cc >/dev/null 2>&1; then
  cc -dM -E - </dev/null 2>/dev/null | grep -E '^#define (__riscv|__BYTE_ORDER__|__SIZEOF_POINTER__|__LP64__)' || true
fi
echo "compiler.macros.end"

echo "project.arch_refs.begin"
find "$project" -type f \( -name '*.c' -o -name '*.cc' -o -name '*.cpp' -o -name '*.h' -o -name '*.hpp' -o -name '*.S' -o -name '*.s' -o -name 'CMakeLists.txt' -o -name 'Makefile' \) \
  -not -path '*/.git/*' -not -path '*/build/*' -not -path '*/node_modules/*' \
  -exec grep -nHE '(__m(128|256|512)|immintrin|x86intrin|xmmintrin|arm_neon|__aarch64__|__arm__|__x86_64__|__riscv|march=|mcpu=|msse|mavx)' {} + 2>/dev/null | head -200 || true
echo "project.arch_refs.end"

