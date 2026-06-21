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

if (CMAKE_SYSTEM_NAME STREQUAL "Darwin")
    if (CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang")
        set(CMAKE_CXX_FLAGS "-Xpreprocessor -fopenmp -fpic")
    else()
        set(CMAKE_CXX_FLAGS "-fopenmp -fpic")
    endif()
elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    set(CMAKE_CXX_FLAGS "-fopenmp -fpic")
endif()

find_package(OpenMP REQUIRED)
target_link_libraries(DTALite PRIVATE OpenMP::OpenMP_CXX)

if(BUILD_DTALITE_EXE)
    add_executable(DTALite_exe src/TAPLite.cpp)
    target_compile_definitions(DTALite_exe PRIVATE BUILD_EXE)
    target_link_libraries(DTALite_exe PRIVATE OpenMP::OpenMP_CXX)
    if(MINGW)
        # static runtime so the exe is self-contained; large stack for the
        # CSV parser's buffers on big networks.
        target_link_options(DTALite_exe PRIVATE
            -static -static-libgcc -static-libstdc++ -Wl,--stack,268435456)
    endif()
endif()