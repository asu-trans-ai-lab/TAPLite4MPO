#!/usr/bin/env bash
# Build the C-ABI shared library that pytaplite loads via ctypes — the Path4GMNS / DTALite
# package pattern. The kernel exports DTA_AssignmentAPI()/DTA_SimulationAPI() (extern "C",
# declared in kernel/src/TAPLite.h). No pybind11 needed; ctypes is in the Python stdlib.
#
#   bash kernel/python/build_shared.sh        # -> pytaplite/DTALite.dll | libDTALite.so | .dylib
#
# (Equivalently: cmake's `add_library(DTALite SHARED ...)` target in kernel/CMakeLists.txt.)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../src/TAPLite.cpp"
OUT_DIR="$HERE/../../pytaplite"
CXX="${CXX:-g++}"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    OUT="$OUT_DIR/DTALite.dll"
    # static-link the MinGW runtime so the DLL has no external runtime-DLL dependencies
    EXTRA="-static -static-libgcc -static-libstdc++" ;;
  Darwin)
    OUT="$OUT_DIR/libDTALite.dylib"; EXTRA="-fPIC" ;;
  *)
    OUT="$OUT_DIR/libDTALite.so";    EXTRA="-fPIC" ;;
esac

echo "building $OUT"
"$CXX" -O2 -shared -std=c++17 -DNDEBUG -fopenmp $EXTRA "$SRC" -o "$OUT"
echo "built $OUT  — pytaplite will load it via ctypes automatically"
