// pybind11 in-process binding for the TAPLite kernel.
//
// Compiles TAPLite.cpp WITHOUT BUILD_EXE (so its main() is excluded) and exposes the kernel's
// AssignmentAPI() as pytaplite._native.run_in_dir(path). The kernel reads/writes CSVs in the
// current working directory, so we chdir into `path` first.
//
// Build: see CMakeLists.txt in this folder (needs pybind11). The resulting _native module is
// imported automatically by pytaplite when present; otherwise pytaplite uses a subprocess.

#include <pybind11/pybind11.h>
#include <string>
#ifdef _WIN32
#include <direct.h>
#define portable_chdir _chdir
#else
#include <unistd.h>
#define portable_chdir chdir
#endif

int AssignmentAPI();    // defined in TAPLite.cpp (compiled here without BUILD_EXE)

namespace py = pybind11;

static int run_in_dir(const std::string& path) {
    if (!path.empty())
        portable_chdir(path.c_str());
    int rc;
    {
        py::gil_scoped_release release;   // the assignment is a long C++ run; free the GIL
        rc = AssignmentAPI();
    }
    return rc;
}

PYBIND11_MODULE(_native, m) {
    m.doc() = "In-process TAPLite assignment kernel (calls AssignmentAPI()).";
    m.def("run_in_dir", &run_in_dir, py::arg("path") = "",
          "Run a static assignment, reading CSV inputs from `path` (or the current working\n"
          "directory) and writing link_performance.csv there. Returns the kernel exit code.\n"
          "NOTE: the kernel keeps global state, so run ONE assignment per process — for many\n"
          "runs use subprocess / multiprocessing (pytaplite.assign does this for you).");
}
