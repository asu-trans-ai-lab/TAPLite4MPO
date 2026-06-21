# Build the in-process Python binding (pytaplite._native) for the TAPLite kernel.
#
#   pip install pybind11
#   cmake -S kernel/python -B kernel/python/build -DCMAKE_BUILD_TYPE=Release
#   cmake --build kernel/python/build --config Release
#   # then copy the built _native.* next to pytaplite/__init__.py
#
# IMPORTANT (Windows): build the extension with the SAME toolchain family as your Python
# (CPython from python.org is MSVC-built — use the "x64 Native Tools" / Visual Studio
# generator). MinGW-built extensions against MSVC CPython can have ABI mismatches.
cmake_minimum_required(VERSION 3.15)
project(taplite_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(pybind11 CONFIG REQUIRED)        # pip install pybind11 (provides the CMake config)

# Compile the kernel WITHOUT BUILD_EXE so its main() is excluded; only AssignmentAPI() is used.
pybind11_add_module(_native
    binding.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../src/TAPLite.cpp)

find_package(OpenMP)
if(OpenMP_CXX_FOUND)
    target_link_libraries(_native PRIVATE OpenMP::OpenMP_CXX)
endif()

# Place the module where pytaplite can import it.
set_target_properties(_native PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../../pytaplite"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../../pytaplite")
