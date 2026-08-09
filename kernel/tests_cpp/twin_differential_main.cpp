// twin_differential — PR-2 (CR-0007): production vs independent twin over
// the compiled analytical case grid, plus a machine-readable dump for the
// external Python oracle (three-way acceptance).
//
// TU 1 (this file): #includes the production source (no BUILD_EXE).
// TU 2 (twin_vdf.cpp): the independent twin — never includes production.
// They meet only at link time through twin_vdf.hpp's neutral structs.

#include "../src/TAPLite.cpp"
#include "../twin/twin_vdf.hpp"
#include "vdf_cases.inc"

#include <cstdio>
#include <cmath>
#include <string>
#include <vector>

static int g_pass = 0, g_fail = 0;
static std::vector<std::string> g_bad;

static double production_tt(const VdfCase& c, double x) {
    Link[0] = link_record();
    Link[0].VDF_type = c.kernel_id;
    Link[0].lanes = 1.0;
    Link[0].Lane_Capacity = 1000.0;
    Link[0].FreeTravelTime = 10.0;
    Link[0].VDF_plf = 1.0;
    Link[0].length = 5.0;
    Link[0].free_speed = 60.0;
    Link[0].Cutoff_Speed = 45.0;
    Link[0].VDF_Alpha = c.alpha;   Link[0].VDF_Beta = c.beta;
    Link[0].VDF_A = c.mbpr_A;
    Link[0].Conic_a = c.conic_a;   Link[0].Conic_b = c.conic_b;
    // Replicate the LOAD-TIME normalization ReadLinks applies (TAPLite.cpp
    // 6354-6355): derive Spiess b when absent. Without this step the runtime
    // fallback silently uses VDF_Beta as conic b — finding TW-1 (a conic
    // link evaluated with b=beta=4 clamps to ZERO travel time at x=0.8).
    // Strict mode (PR-3) will make that state unrepresentable.
    if (Link[0].VDF_type == 1 && Link[0].Conic_b <= 0.0
        && Link[0].Conic_a > 1.0)
        Link[0].Conic_b = (2.0 * Link[0].Conic_a - 1.0)
                          / (2.0 * Link[0].Conic_a - 2.0);
    Link[0].Q_cp = c.q_cp; Link[0].Q_cd = c.q_cd;
    Link[0].Q_n = c.q_n;   Link[0].Q_s = c.q_s;
    Link[0].green_ratio = c.green_ratio;
    Link[0].cycle_length = (int)c.cycle_length_s;
    g_added_delay_per_mile = c.added_delay_per_mile;
    double vol[1] = { x * 1000.0 };
    double t = Link_Travel_Time(0, vol);
    g_added_delay_per_mile = 0.0;
    return t;
}

static VdfInput twin_input(const VdfCase& c, double x) {
    VdfInput in;
    in.volume = x * 1000.0;
    in.lanes = 1.0; in.period_hours = 1.0; in.plf = 1.0;
    in.capacity_per_lane = 1000.0; in.fftt_min = 10.0;
    in.length_mile = 5.0; in.free_speed_mph = 60.0;
    in.cutoff_speed_mph = 45.0;
    in.alpha = c.alpha; in.beta = c.beta; in.mbpr_A = c.mbpr_A;
    in.conic_a = c.conic_a; in.conic_b = c.conic_b;
    in.q_cp = c.q_cp; in.q_cd = c.q_cd; in.q_n = c.q_n; in.q_s = c.q_s;
    in.green_ratio = c.green_ratio; in.cycle_length_s = c.cycle_length_s;
    in.added_delay_per_mile = c.added_delay_per_mile;
    return in;
}

int main(int argc, char** argv) {
    demand_period_starting_hours = 7.0;
    demand_period_ending_hours = 8.0;
    Link = new link_record[1];

    FILE* dump = NULL;
    if (argc > 1) dump = fopen(argv[1], "w");
    if (dump) fprintf(dump, "case_id,kernel_id,x,production_tt,twin_tt\n");

    for (int ci = 0; ci < N_CASES; ++ci) {
        const VdfCase& c = CASES[ci];
        for (int gi = 0; gi < CASE_NG; ++gi) {
            double x = CASE_GRID[gi];
            double tp = production_tt(c, x);
            double tw = twin_travel_time(c.kernel_id, twin_input(c, x));
            double tol = CASE_REL_TOL * (1.0 + std::fabs(tp));
            if (std::fabs(tp - tw) <= tol) ++g_pass;
            else {
                ++g_fail;
                char b[192];
                snprintf(b, sizeof b,
                         "%s @x=%.6f production=%.12f twin=%.12f",
                         c.id, x, tp, tw);
                g_bad.push_back(b);
            }
            if (dump)
                fprintf(dump, "%s,%d,%.9f,%.15g,%.15g\n",
                        c.id, c.kernel_id, x, tp, tw);
        }
    }
    if (dump) fclose(dump);

    std::printf("twin differential: %d cases x %d grid points\n",
                N_CASES, CASE_NG);
    std::printf("  PASS %d   FAIL %d\n", g_pass, g_fail);
    for (size_t i = 0; i < g_bad.size() && i < 20; ++i)
        std::printf("  DIVERGENCE: %s\n", g_bad[i].c_str());
    std::printf("OVERALL: %s\n", g_fail == 0 ? "PASS" : "BLOCKED");
    delete[] Link; Link = NULL;
    return g_fail == 0 ? 0 : 1;
}
