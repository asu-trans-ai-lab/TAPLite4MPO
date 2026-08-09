cmake_minimum_required(VERSION 3.10.0)

project(DTALite VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 11)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

# Shared library target (Python ctypes / DTALite package consumes this).
add_library(DTALite SHARED src/TAPLite.cpp)

# Standalone executable target for consistent, debuggable runs.
# Built when -DBUILD_DTALITE_EXE=ON (default ON). Defines BUILD_EXE so the
# main() entry point in TAPLite.cpp is compiled in. The executable runs the
# kernel directly in the working directory and is gdb-debuggable; it also
# avoids the Windows Application Control block on loading unsigned DLLs.
option(BUILD_DTALITE_EXE "Build the standalone TAPLite executable" ON)

# OpenMP is strongly recommended (parallel shortest paths) but OPTIONAL: on
# Apple clang without libomp (`brew install libomp`) the kernel builds serial --
# TAPLite.cpp carries inline fallbacks for the two OpenMP APIs it calls.
find_package(OpenMP)
if(OpenMP_CXX_FOUND)
    target_link_libraries(DTALite PRIVATE OpenMP::OpenMP_CXX)
else()
    message(WARNING "OpenMP not found -- building a SERIAL kernel (correct but slower). "
                    "macOS: brew install libomp, then re-run cmake.")
endif()
set_target_properties(DTALite PROPERTIES POSITION_INDEPENDENT_CODE ON)

# ---- PR-1 (CR-0006): C++ self-test spine -----------------------------------
# taplite_selftest #includes the production TU (no BUILD_EXE -> no main clash)
# and certifies the production cost functions on hand-computed known values
# and mathematical properties. Zero production-code change.
enable_testing()
option(BUILD_TAPLITE_SELFTEST "Build the taplite_selftest certification exe" ON)
if(BUILD_TAPLITE_SELFTEST)
    add_executable(taplite_selftest tests_cpp/selftest_main.cpp)
    if(OpenMP_CXX_FOUND)
        target_link_libraries(taplite_selftest PRIVATE OpenMP::OpenMP_CXX)
    endif()
    if(MINGW)
        target_link_options(taplite_selftest PRIVATE
            -static -static-libgcc -static-libstdc++)
    endif()
    add_test(NAME scalar_certification COMMAND taplite_selftest)
endif()

if(BUILD_DTALITE_EXE)
    add_executable(DTALite_exe src/TAPLite.cpp)
    target_compile_definitions(DTALite_exe PRIVATE BUILD_EXE)
    if(OpenMP_CXX_FOUND)
        target_link_libraries(DTALite_exe PRIVATE OpenMP::OpenMP_CXX)
    endif()
    if(MINGW)
        # static runtime so the exe is self-contained; large stack for the
        # CSV parser's buffers on big networks.
        target_link_options(DTALite_exe PRIVATE
            -static -static-libgcc -static-libstdc++ -Wl,--stack,268435456)
    endif()
endif()