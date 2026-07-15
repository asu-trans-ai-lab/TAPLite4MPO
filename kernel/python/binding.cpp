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
#ifdef _OPENMP
#include <omp.h>
#endif
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

static py::dict openmp_status(int requested_threads) {
    if (requested_threads < 0)
        throw py::value_error("requested_threads must be >= 0");

    bool compiled = false;
    int openmp_version = 0;
    int max_threads = 1;
    int num_procs = 1;
    bool dynamic = false;
    int probe_team_size = 1;

#ifdef _OPENMP
    compiled = true;
    openmp_version = _OPENMP;
    max_threads = omp_get_max_threads();
    num_procs = omp_get_num_procs();
    const int original_dynamic = omp_get_dynamic();
    dynamic = original_dynamic != 0;

    if (requested_threads > 0) {
        omp_set_dynamic(0);
        omp_set_num_threads(requested_threads);
    }

#pragma omp parallel
    {
#pragma omp single
        probe_team_size = omp_get_num_threads();
    }

    if (requested_threads > 0) {
        omp_set_num_threads(max_threads);
        omp_set_dynamic(original_dynamic);
    }
#endif

    py::dict status;
    status["compiled"] = compiled;
    status["openmp_version"] = openmp_version;
    status["max_threads"] = max_threads;
    status["num_procs"] = num_procs;
    status["dynamic"] = dynamic;
    status["requested_threads"] = requested_threads;
    status["probe_team_size"] = probe_team_size;
    return status;
}

PYBIND11_MODULE(_native, m) {
    m.doc() = "In-process TAPLite assignment kernel (calls AssignmentAPI()).";
    m.def("run_in_dir", &run_in_dir, py::arg("path") = "",
          "Run a static assignment, reading CSV inputs from `path` (or the current working\n"
          "directory) and writing link_performance.csv there. Returns the kernel exit code.\n"
          "NOTE: the kernel keeps global state, so run ONE assignment per process — for many\n"
          "runs use subprocess / multiprocessing (pytaplite.assign does this for you).");
    m.def("openmp_status", &openmp_status, py::arg("requested_threads") = 0,
          "Return native OpenMP build and runtime diagnostics without running an assignment.");
}
