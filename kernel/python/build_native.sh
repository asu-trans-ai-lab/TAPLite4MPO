#!/usr/bin/env bash
# Build pytaplite._native directly with the compiler (no CMake). See CMakeLists.txt for the
# recommended cross-platform path. On Windows, prefer building with the toolchain matching
# your Python (MSVC for python.org CPython); MinGW may hit ABI mismatches.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PYINC="$(python -c 'import sysconfig; print(sysconfig.get_path("include"))')"
PBINC="$(python -c 'import pybind11; print(pybind11.get_include())')"
EXT="$(python -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX") or ".pyd")')"
OUT="$HERE/../../pytaplite/_native$EXT"

CXX="${CXX:-g++}"
echo "compiling _native -> $OUT"
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || -n "$WINDIR" ]]; then
  PYLIB="$(python -c 'import sysconfig,os; print(os.path.join(sysconfig.get_config_var("installed_base"),"libs"))')"
  PYVER="$(python -c 'import sysconfig; print("python"+sysconfig.get_config_var("py_version_nodot"))')"
  # statically link the MinGW runtime (libgcc/libstdc++/libgomp/winpthread) so the .pyd has
  # no external DLL dependencies — avoids "DLL load failed" on import.
  "$CXX" -O2 -shared -std=c++17 -DNDEBUG -fopenmp \
     -static -static-libgcc -static-libstdc++ \
     -I"$PYINC" -I"$PBINC" \
     "$HERE/binding.cpp" "$HERE/../src/TAPLite.cpp" \
     -L"$PYLIB" -l"$PYVER" -o "$OUT"
else
  "$CXX" -O3 -shared -std=c++17 -fPIC -DNDEBUG -fopenmp \
     -I"$PYINC" -I"$PBINC" \
     "$HERE/binding.cpp" "$HERE/../src/TAPLite.cpp" -o "$OUT"
fi
echo "built $OUT"
