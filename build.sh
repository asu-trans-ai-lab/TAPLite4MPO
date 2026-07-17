#!/usr/bin/env bash
# Canonical cross-platform build for the DTALite/TAPLite C++ kernel.
#   Windows (Git Bash/MSYS): -> bin/TAPLite.exe   (MinGW, static, stripped;
#                               bin/DTALite.exe kept as a legacy-name copy)
#   macOS:                   -> bin/TAPLite       (clang; OpenMP via `brew install libomp`,
#                                                  builds SERIAL if libomp is absent)
#   Linux:                   -> bin/TAPLite       (g++/clang, OpenMP)
# Requires: cmake >= 3.10 and a C++ compiler. Ninja is used if available.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/kernel"
BUILD="$HERE/cmake_build_rel"
mkdir -p "$HERE/bin"

GEN=()
command -v ninja >/dev/null 2>&1 && GEN=(-G Ninja)

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    # Windows via MinGW: static, stripped Release exe (App-Control-clean).
    WINLIBS="/c/Users/xzhou/AppData/Local/Microsoft/WinGet/Packages/BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe/mingw64/bin"
    [ -d "$WINLIBS" ] && export PATH="$WINLIBS:$PATH"
    CXX_NAME="g++"
    command -v x86_64-w64-mingw32-g++.exe >/dev/null 2>&1 && CXX_NAME="x86_64-w64-mingw32-g++.exe"
    echo "[build] Windows/MinGW ($CXX_NAME) -> bin/TAPLite.exe"
    cmake -S "$SRC" -B "$BUILD" "${GEN[@]}" \
        -DCMAKE_CXX_COMPILER="$CXX_NAME" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CXX_FLAGS="-fopenmp -O2 -DNDEBUG" \
        -DCMAKE_EXE_LINKER_FLAGS="-s" >/dev/null
    cmake --build "$BUILD" --target DTALite_exe
    cp "$BUILD/DTALite_exe.exe" "$HERE/bin/TAPLite.exe"
    cp "$BUILD/DTALite_exe.exe" "$HERE/bin/DTALite.exe"   # legacy-name compat copy
    OUT="$HERE/bin/TAPLite.exe"
    ;;
  Darwin)
    echo "[build] macOS (clang) -> bin/TAPLite"
    EXTRA=()
    # NOTE: `brew --prefix libomp` succeeds even when libomp is NOT installed,
    # so verify the dylib actually exists before wiring it into the build.
    if command -v brew >/dev/null 2>&1 && [ -f "$(brew --prefix libomp 2>/dev/null)/lib/libomp.dylib" ]; then
      OMP="$(brew --prefix libomp)"
      echo "[build] libomp found at $OMP (parallel kernel)"
      EXTRA=(-DOpenMP_CXX_FLAGS="-Xpreprocessor -fopenmp -I$OMP/include"
             -DOpenMP_CXX_LIB_NAMES=omp
             -DOpenMP_omp_LIBRARY="$OMP/lib/libomp.dylib")
    else
      echo "[build] libomp NOT found -- building a SERIAL kernel (correct but slower)."
      echo "[build] for the parallel kernel:  brew install libomp  and rebuild."
    fi
    cmake -S "$SRC" -B "$BUILD" "${GEN[@]}" -DCMAKE_BUILD_TYPE=Release "${EXTRA[@]}"
    cmake --build "$BUILD" --target DTALite_exe -j
    cp "$BUILD/DTALite_exe" "$HERE/bin/TAPLite"
    cp "$BUILD/DTALite_exe" "$HERE/bin/DTALite"   # legacy-name compat copy
    OUT="$HERE/bin/TAPLite"
    ;;
  *)
    echo "[build] Linux -> bin/TAPLite"
    cmake -S "$SRC" -B "$BUILD" "${GEN[@]}" -DCMAKE_BUILD_TYPE=Release
    cmake --build "$BUILD" --target DTALite_exe -j
    cp "$BUILD/DTALite_exe" "$HERE/bin/TAPLite"
    cp "$BUILD/DTALite_exe" "$HERE/bin/DTALite"   # legacy-name compat copy
    OUT="$HERE/bin/TAPLite"
    ;;
esac

echo "[build] kernel -> $OUT"
