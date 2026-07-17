#!/usr/bin/env bash
# Canonical build for the consolidated DTALite/TAPLite C++ kernel.
# Self-contained: builds kernel/src/TAPLite.cpp -> bin/DTALite.exe via CMake.
#
# Output: a stripped Release standalone executable (App-Control-clean, ~1.5 MB).
# For gdb source debugging, turn OFF Windows Smart App Control, then build with
#   -DCMAKE_BUILD_TYPE=RelWithDebInfo  (larger binary, App Control may block it).
set -e
export PATH="/c/Users/xzhou/AppData/Local/Microsoft/WinGet/Packages/BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe/mingw64/bin:$PATH"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/kernel"
BUILD="$HERE/cmake_build_rel"
mkdir -p "$HERE/bin"
echo "[build] configure (Release, stripped, exe target)"
cmake -S "$SRC" -B "$BUILD" -G Ninja \
    -DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-g++.exe \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_FLAGS="-fopenmp -O2 -DNDEBUG" \
    -DCMAKE_EXE_LINKER_FLAGS="-s" >/dev/null
echo "[build] build DTALite_exe"
cmake --build "$BUILD" --target DTALite_exe
cp "$BUILD/DTALite_exe.exe" "$HERE/bin/DTALite.exe"
echo "[build] kernel -> $HERE/bin/DTALite.exe ($(stat -c%s "$HERE/bin/DTALite.exe") bytes)"
