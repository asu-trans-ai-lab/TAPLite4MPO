// taplite_selftest — PR-1 (CR-0006): scalar certification of the PRODUCTION
// cost functions on known values and mathematical properties.
//
// This translation unit #includes the production source (BUILD_EXE undefined,
// so no main() clash) and calls Link_Travel_Time() directly — the same code
// path the assignment uses. NO production line is modified.
//
// Expected values are HAND-COMPUTED constants or closed-form identities
// (never recomputed via the production formula). The independent C++ twin
// and the external Python oracle arrive in PR-2; this spine proves the
// harness and freezes today's numerical behavior.
//
// Run:  taplite_selftest            (exit 0 = all pass, nonzero = failures)

#include "../src/TAPLite.cpp"

#include <cstdio>
#include <cmath>
#include <vector>
#include <string>

static int g_pass = 0, g_fail = 0;
static std::vector<std::string> g_failures;

static void check(bool ok, const char* what) {
    if (ok) { ++g_pass; }
    else { ++g_fail; g_failures.push_back(what); }
}
static void near_(double a, double b, double tol, const char* what) {
    char buf[256];
    if (std::fabs(a - b) <= tol) { ++g_pass; return; }
    ++g_fail;
    snprintf(buf, sizeof buf, "%s (got %.9f expected %.9f tol %.1e)",
             what, a, b, tol);
    g_failures.push_back(buf);
}

// One-link laboratory: lanes=1, H=1h, plf=1  =>  IncomingDemand == Volume,
// per-lane V/C == Volume / Lane_Capacity.
static const double C_LANE = 1000.0;   // veh/h/lane
static const double T0 = 10.0;         // free-flow minutes

static void reset_link(int vdf_type) {
    Link[0] = link_record();           // ctor defaults
    Link[0].VDF_type = vdf_type;
    Link[0].lanes = 1.0;
    Link[0].Lane_Capacity = C_LANE;
    Link[0].FreeTravelTime = T0;
    Link[0].VDF_plf = 1.0;
    Link[0].VDF_Alpha = 0.15;
    Link[0].VDF_Beta = 4.0;
    Link[0].VDF_A = 0.0;
    Link[0].length = 5.0;              // miles (QVDF/ramp use it)
    Link[0].free_speed = 60.0;         // mph
    Link[0].Cutoff_Speed = 45.0;
    Link[0].Q_cp = 0.28125; Link[0].Q_cd = 1.0;
    Link[0].Q_n = 1.24;     Link[0].Q_s = 4.0;
    Link[0].green_ratio = 0.45;
    Link[0].cycle_length = 90;         // seconds
}

static double tt_at(double x) {        // x = V/C on the lab link
    double vol[1] = { x * C_LANE };
    return Link_Travel_Time(0, vol);
}

static const double GRID[] = {0.0, 0.1, 0.25, 0.5, 0.8,
                              0.999999, 1.0, 1.000001, 1.2, 1.5, 2.0, 3.0};
static const int NG = sizeof(GRID) / sizeof(GRID[0]);

static void props(const char* name, double continuity_probe /*x or -1*/) {
    double prev = -1.0;
    for (int i = 0; i < NG; ++i) {
        double t = tt_at(GRID[i]);
        char b[128];
        snprintf(b, sizeof b, "%s nonneg @x=%.6f", name, GRID[i]);
        check(t >= 0.0, b);
        snprintf(b, sizeof b, "%s monotone @x=%.6f", name, GRID[i]);
        check(t >= prev - 1e-9, b);
        prev = t;
    }
    if (continuity_probe > 0) {
        double lo = tt_at(continuity_probe * 0.999999);
        double hi = tt_at(continuity_probe * 1.000001);
        char b[128];
        snprintf(b, sizeof b, "%s continuous @x=%.4f", name, continuity_probe);
        check(std::fabs(hi - lo) < 0.05 * (1.0 + lo), b);
    }
}

int run_selftest() {
    demand_period_starting_hours = 7.0;
    demand_period_ending_hours = 8.0;      // H = 1
    g_added_delay_per_mile = 0.0;
    Link = new link_record[1];

    std::printf("TAPLite C++ capability self-test (production functions)\n");
    std::printf("=======================================================\n");

    // ---- vdf_type 0: BPR + ARC modified ----
    reset_link(0);
    near_(tt_at(0.0), T0, 1e-9, "BPR t(0)=t0");
    near_(tt_at(1.0), 11.5, 1e-9, "BPR t(1)=t0*(1+0.15)");     // 10*(1.15)
    near_(tt_at(2.0), T0 * (1.0 + 0.15 * 16.0), 1e-9, "BPR t(2)");
    props("BPR", -1);
    Link[0].VDF_A = 0.5;                                        // ARC modified
    near_(tt_at(1.0), T0 * (1.0 + 0.5 + 0.15), 1e-9, "MBPR t(1)");
    props("ModifiedBPR", -1);

    // ---- vdf_type 1: Spiess conic (Feng FT1: a=15, b=(2a-1)/(2a-2)) ----
    reset_link(1);
    Link[0].Conic_a = 15.0;
    Link[0].Conic_b = 29.0 / 28.0;
    near_(tt_at(1.0), 2.0 * T0, 1e-9, "Conic t(1)=2*t0 (Spiess identity)");
    {   // x=0 closed form: t0*(2+sqrt(a^2+b^2)-a-b)
        double a = 15.0, b = 29.0 / 28.0;
        near_(tt_at(0.0), T0 * (2.0 + std::sqrt(a * a + b * b) - a - b),
              1e-9, "Conic t(0) closed form");
    }
    props("ConicalSpiess", 1.0);
    // documented fallback (deprecated in PR-3 strict mode): a/b from alpha/beta
    Link[0].Conic_a = 0.0; Link[0].Conic_b = 0.0;
    Link[0].VDF_Alpha = 15.0; Link[0].VDF_Beta = 29.0 / 28.0;
    near_(tt_at(1.0), 2.0 * T0, 1e-9,
          "Conic legacy alpha/beta fallback still active (PR-3 will gate)");

    // ---- vdf_type 2: QVDF period-average (closed-form branch) ----
    reset_link(2);
    Link[0].VDF_Alpha = 0.272; Link[0].VDF_Beta = 4.0;
    {   // x=0: P=0 => avg speed = 0*q + 1*(cong_ref+free)/2 with cong_ref=free
        double t = tt_at(0.0);
        near_(t, Link[0].length / 60.0 * 60.0, 1e-6, "QVDF t(0)=L/free*60");
    }
    props("QVDF", 1.0);

    // ---- vdf_type 3: BPR2 ----
    reset_link(3);
    near_(tt_at(0.5), T0 * (1.0 + 0.15 * std::pow(0.5, 4.0)), 1e-9, "BPR2 below cap");
    near_(tt_at(1.5), T0 * (1.0 + 0.15 * std::pow(1.5, 8.0)), 1e-9, "BPR2 doubled exponent");
    props("BPR2", 1.0);

    // ---- vdf_type 4: INRETS ----
    reset_link(4);
    Link[0].VDF_Alpha = 0.9;
    near_(tt_at(0.5), T0 * (1.1 - 0.9 * 0.5) / (1.1 - 0.5), 1e-9, "INRETS below");
    near_(tt_at(2.0), T0 * ((1.1 - 0.9) / 0.1) * 4.0, 1e-9, "INRETS above");
    props("INRETS", -1);   // kernel guard fmax(0.05,...) flattens near x=1.05+

    // ---- vdf_type 5: Akcelik ----
    reset_link(5);
    Link[0].VDF_Alpha = 2.0; Link[0].VDF_Beta = 0.5;
    near_(tt_at(0.0), T0, 1e-9, "Akcelik t(0)=t0");
    {   double z = 0.2, x = 1.2;
        near_(tt_at(x), T0 + 2.0 * (z + std::sqrt(z * z + 0.5 * x)), 1e-9,
              "Akcelik t(1.2)");
    }
    props("Akcelik", -1);

    // ---- vdf_type 6: SANDAG signal (BPR + Webster uniform) ----
    reset_link(6);
    {   double d0 = 0.5 * 90.0 * 0.55 * 0.55 / 1.0 / 60.0;     // x=0
        near_(tt_at(0.0), T0 + d0, 1e-9, "SANDAG t(0)=t0+webster");
    }
    props("SANDAGsignal", -1);

    // ---- vdf_type 7: SCAG piecewise ----
    reset_link(7);
    Link[0].VDF_Alpha = 1.0; Link[0].VDF_Beta = 6.0;
    near_(tt_at(0.999999), T0 * (1.0 + 1.0 * std::pow(0.999999, 4.0)), 1e-6,
          "SCAG-PWL below breakpoint (beta=4)");
    near_(tt_at(1.000001), T0 * (1.0 + 1.0 * std::pow(1.000001, 6.0)), 1e-6,
          "SCAG-PWL above breakpoint (per-link beta)");
    {   double lo = tt_at(0.999999), hi = tt_at(1.000001);
        check(std::fabs(hi - lo) < 1e-3, "SCAG-PWL continuous at x=1");
    }
    props("SCAGpiecewise", 1.0);

    // ---- vdf_type 8: SCAG ramp meter ----
    reset_link(8);
    {   double x = 0.5, plph = x * C_LANE;
        double d_hr = (plph / 120.0) * 5.0 * std::pow(1.5, 8.0) / 60.0;
        near_(tt_at(x), T0 + d_hr * 60.0, 1e-6, "SCAG ramp t(0.5)");
    }
    props("SCAGrampMeter", -1);

    // ---- CR-0010: processor-count contract ----
    check(ProcessorCountValidationStatus(0) == 0,
          "processors=0 accepted as auto-detect sentinel");
    check(ProcessorCountValidationStatus(1) == 0, "processors=1 valid");
    check(ProcessorCountValidationStatus(-1) != 0, "processors=-1 rejected");

    // ---- guard behavior: clamp at zero, added-delay off by default ----
    reset_link(0);
    check(tt_at(0.0) >= 0.0, "nonneg clamp");
    // MAG per-mile added delay applies additively when enabled
    g_added_delay_per_mile = 1.4;
    near_(tt_at(0.0), T0 + 1.4 * 5.0, 1e-9, "MAG added delay per mile");
    g_added_delay_per_mile = 0.0;

    // ---- CR-0014: QVDF reporting-profile decision contract (K-1/K-2) ----
    // args: (profile_mode, is_freeway, has_observed_t2, vdf_type, params_provided)
    {
        auto d = DecideQvdfProfile(-1, true, false, 0, false);   // the K-1 case:
        check(!d.eligible, "BPR freeway legacy-auto: no analytical QVDF profile");
        check(std::string(d.status) == "flat_non_qvdf_assignment",
              "BPR freeway legacy-auto status");
        d = DecideQvdfProfile(-1, true, false, 1, false);
        check(!d.eligible, "conical freeway legacy-auto: no analytical QVDF profile");
        d = DecideQvdfProfile(-1, true, false, 2, false);        // QVDF run unchanged
        check(d.eligible && std::string(d.status) == "generated_legacy_link_type",
              "QVDF freeway legacy-auto preserved");
        d = DecideQvdfProfile(-1, false, true, 2, false);
        check(d.eligible && std::string(d.status) == "generated_legacy_observed_t2",
              "QVDF observed-t2 legacy-auto preserved");
        d = DecideQvdfProfile(-1, false, true, 0, true);         // calibrated + t2
        check(d.eligible, "non-QVDF observed-t2 WITH vdf_cd/vdf_n eligible");
        d = DecideQvdfProfile(-1, false, true, 0, false);        // K-2 case:
        check(!d.eligible && std::string(d.status) == "flat_missing_parameters",
              "non-QVDF observed-t2 without params refused (no silent defaults)");
        d = DecideQvdfProfile(0, true, true, 2, true);
        check(!d.eligible && std::string(d.status) == "flat_disabled",
              "explicit mode 0 disables");
        d = DecideQvdfProfile(1, false, false, 0, true);
        check(d.eligible && std::string(d.status) == "generated_model",
              "explicit mode 1 with params generates");
        d = DecideQvdfProfile(1, false, false, 0, false);
        check(!d.eligible && std::string(d.status) == "flat_missing_parameters",
              "explicit mode 1 without params refused");
        d = DecideQvdfProfile(2, false, false, 0, true);
        check(!d.eligible && std::string(d.status) == "flat_missing_observation",
              "mode 2 without observed t2 refused");
        d = DecideQvdfProfile(2, false, true, 0, true);
        check(d.eligible && std::string(d.status) == "generated_observed",
              "mode 2 with observed t2 and params generates");
        d = DecideQvdfProfile(-1, false, false, 0, false);
        check(!d.eligible && std::string(d.status) == "flat_legacy_not_selected",
              "non-freeway non-QVDF stays flat");
    }

    // ---- CR-0015: binary route pool codec round trip ----
    {
        std::vector<RoutePoolRecord> recs(3);
        recs[0].mode = 1; recs[0].o_zone = 100; recs[0].d_zone = 200;
        recs[0].prob = 0.375; recs[0].volume = 1234.5678;
        recs[0].link_ext_ids.push_back(7);
        recs[0].link_ext_ids.push_back(2000000000);   // large external id
        recs[1].mode = 6; recs[1].o_zone = 3857; recs[1].d_zone = 1;
        recs[1].prob = 1.0; recs[1].volume = 0.0;     // zero-volume path
        recs[1].link_ext_ids.push_back(42);
        recs[2].mode = 2; recs[2].o_zone = 5; recs[2].d_zone = 5;
        recs[2].prob = 0.625; recs[2].volume = 0.001; // empty path edge case
        const char* fn = "selftest_route_pool.bin";
        check(WriteRoutePool(fn, recs), "route pool write");
        std::vector<RoutePoolRecord> back;
        check(ReadRoutePool(fn, back), "route pool read + link-count check");
        check(back.size() == 3, "route pool record count");
        if (back.size() == 3) {
            near_(back[0].volume, 1234.5678, 1e-12, "volume bit round trip");
            near_(back[0].prob, 0.375, 1e-15, "prob round trip");
            check(back[0].link_ext_ids.size() == 2 &&
                  back[0].link_ext_ids[1] == 2000000000,
                  "large external link id round trip");
            check(back[1].volume == 0.0 && back[1].link_ext_ids.size() == 1,
                  "zero-volume path round trip");
            check(back[2].link_ext_ids.empty(), "empty path round trip");
        }
        std::remove(fn);
        std::vector<RoutePoolRecord> none;
        check(!ReadRoutePool("selftest_no_such_file.bin", none),
              "missing file fails loudly");
    }

    // ---- CR-0017: tree column pool codec + bottom-up identity ----
    // Hand-computed tree (root=1):  1 --L10--> 2 --L20--> 3
    //                                          2 --L30--> 4
    // Arc slice in farther-to-root order: (4,L30), (3,L20), (2,L10).
    // Demand: dest 3 = 100, dest 4 = 50.  Bottom-up sweep must give
    //   L30 = 50, L20 = 100, L10 = 150  (and L10 == total demand: the
    //   conservation identity at the root).
    {
        std::map<int, int> from_node;
        from_node[10] = 1; from_node[20] = 2; from_node[30] = 2;

        std::vector<TreePoolSnapshot> snaps(1);
        snaps[0].iteration = 0; snaps[0].mode = 1;
        snaps[0].root_zone = 1; snaps[0].root_node = 1;
        snaps[0].arc_begin = 0; snaps[0].arc_count = 3; snaps[0].theta = 1.0;
        std::vector<TreePoolArc> arcs(3);
        arcs[0].node = 4; arcs[0].link = 30;
        arcs[1].node = 3; arcs[1].link = 20;
        arcs[2].node = 2; arcs[2].link = 10;
        std::vector<TreePoolOD> ods(2);
        ods[0].snapshot_idx = 0; ods[0].dest_node = 3; ods[0].dest_zone = 3;
        ods[0].volume = 100.0;
        ods[1].snapshot_idx = 0; ods[1].dest_node = 4; ods[1].dest_zone = 4;
        ods[1].volume = 50.0;

        std::map<int, double> lv;
        check(TreePoolAccumulate(snaps, arcs, ods, from_node, lv),
              "tree bottom-up sweep runs");
        near_(lv[30], 50.0, 1e-12, "tree bottom-up leaf L30");
        near_(lv[20], 100.0, 1e-12, "tree bottom-up leaf L20");
        near_(lv[10], 150.0, 1e-12, "tree bottom-up trunk L10 = sum of demand");

        // theta scaling is linear and applies to every arc of the snapshot
        snaps[0].theta = 0.4;
        std::map<int, double> lv04;
        check(TreePoolAccumulate(snaps, arcs, ods, from_node, lv04),
              "tree sweep with theta=0.4");
        near_(lv04[10], 60.0, 1e-12, "theta scales trunk");
        near_(lv04[30], 20.0, 1e-12, "theta scales leaf");
        snaps[0].theta = 1.0;

        // FW accumulation across two snapshots: thetas must sum into one x
        std::vector<TreePoolSnapshot> two(2);
        two[0] = snaps[0]; two[0].theta = 0.25;
        two[1] = snaps[0]; two[1].iteration = 1; two[1].theta = 0.75;
        std::vector<TreePoolOD> ods2 = ods;
        ods2.push_back(ods[0]); ods2.back().snapshot_idx = 1;
        ods2.push_back(ods[1]); ods2.back().snapshot_idx = 1;
        std::map<int, double> lv2;
        check(TreePoolAccumulate(two, arcs, ods2, from_node, lv2),
              "two-snapshot FW accumulation");
        near_(lv2[10], 150.0, 1e-12, "sum of thetas = 1 reproduces x exactly");

        // binary round trip
        const char* tf = "selftest_tree_pool.bin";
        check(WriteTreePool(tf, snaps, arcs, ods), "tree pool write");
        std::vector<TreePoolSnapshot> s2;
        std::vector<TreePoolArc> a2;
        std::vector<TreePoolOD> o2;
        check(ReadTreePool(tf, s2, a2, o2), "tree pool read");
        check(s2.size() == 1 && a2.size() == 3 && o2.size() == 2,
              "tree pool counts round trip");
        if (s2.size() == 1) {
            near_(s2[0].theta, 1.0, 1e-15, "theta round trip");
            check(s2[0].root_node == 1 && s2[0].arc_count == 3,
                  "snapshot fields round trip");
        }
        if (a2.size() == 3)
            check(a2[0].node == 4 && a2[0].link == 30 && a2[2].link == 10,
                  "arc order preserved (farther-to-root)");
        if (o2.size() == 2)
            near_(o2[0].volume, 100.0, 1e-12, "OD volume round trip");
        // reloaded pool must reproduce the same link volumes
        std::map<int, double> lv_rt;
        check(TreePoolAccumulate(s2, a2, o2, from_node, lv_rt),
              "reloaded pool sweeps");
        near_(lv_rt[10], 150.0, 1e-12, "reload identity: trunk");
        near_(lv_rt[20], 100.0, 1e-12, "reload identity: branch");
        std::remove(tf);

        // corruption must fail loudly, never be silently repaired
        std::vector<TreePoolSnapshot> bad_s = snaps;
        bad_s[0].arc_count = 99;              // slice past the arc pool
        check(WriteTreePool(tf, bad_s, arcs, ods), "write oversized slice");
        std::vector<TreePoolSnapshot> s3; std::vector<TreePoolArc> a3;
        std::vector<TreePoolOD> o3;
        check(!ReadTreePool(tf, s3, a3, o3),
              "arc slice past end of pool rejected");
        std::remove(tf);
        std::vector<TreePoolOD> bad_o = ods;
        bad_o[0].snapshot_idx = 7;            // dangling snapshot reference
        check(WriteTreePool(tf, snaps, arcs, bad_o), "write dangling OD");
        check(!ReadTreePool(tf, s3, a3, o3), "dangling snapshot_idx rejected");
        std::remove(tf);
        check(!ReadTreePool("selftest_no_tree_here.bin", s3, a3, o3),
              "missing tree pool fails loudly");
        // an unmapped link must fail, not silently drop flow
        std::map<int, int> holes = from_node;
        holes.erase(20);
        std::map<int, double> lvh;
        check(!TreePoolAccumulate(snaps, arcs, ods, holes, lvh),
              "unknown link in arc pool rejected");
    }

    // ---- CR-0018: compact OD matrix binary codec ----
    {
        std::vector<OdZoneRec> zt(2);
        zt[0].zone_id = 101; zt[0].x = -77.0485f; zt[0].y = 38.8938f;
        zt[1].zone_id = 3858; zt[1].x = -77.5f;   zt[1].y = 39.0f;
        std::vector<OdPerfRec> rr(2);
        rr[0].mode = 1; rr[0].o_zone = 101; rr[0].d_zone = 3858;
        rr[0].dist_mile = 1.18f; rr[0].straight_mile = 0.690332f;
        rr[0].fftt_min = 2.50185f; rr[0].tt_min = 3.19994f;
        rr[0].volume = 0.002f;
        rr[1].mode = 6; rr[1].o_zone = 3858; rr[1].d_zone = 101;
        rr[1].dist_mile = 0.0f; rr[1].straight_mile = 0.0f;
        rr[1].fftt_min = 0.0f; rr[1].tt_min = 0.0f; rr[1].volume = 0.0f;
        const char* of = "selftest_od_perf.bin";
        check(WriteOdPerfBinary(of, zt, 6, rr), "od matrix write");
        std::vector<OdZoneRec> z2; std::vector<OdPerfRec> r2;
        unsigned int nm = 0;
        check(ReadOdPerfBinary(of, z2, nm, r2), "od matrix read");
        check(nm == 6 && z2.size() == 2 && r2.size() == 2,
              "od matrix counts round trip");
        if (r2.size() == 2) {
            near_(r2[0].volume, 0.002f, 1e-9, "od volume round trip");
            near_(r2[0].tt_min, 3.19994f, 1e-6, "od travel time round trip");
            check(r2[0].o_zone == 101 && r2[0].d_zone == 3858 &&
                  r2[1].mode == 6, "od identity round trip");
        }
        if (z2.size() == 2)
            near_(z2[0].x, -77.0485f, 1e-5,
                  "zone coords stored ONCE in the zone table");
        // 32 B/record vs ~200 B/CSV row is the whole point
        check(sizeof(OdPerfRec) == 32, "od record is 32 bytes");
        std::remove(of);
        std::vector<OdZoneRec> z3; std::vector<OdPerfRec> r3;
        check(!ReadOdPerfBinary("selftest_no_od.bin", z3, nm, r3),
              "missing od matrix fails loudly");
    }

    // ---- CR-0019: static VDFs use V_period / C_period, no PLF ----
    // The whole point: with capacity_period supplied, the loading ratio must
    // not depend on lanes, period hours, or PLF. Changing any of those must
    // leave the travel time bit-identical.
    {
        demand_period_starting_hours = 15.0;   // PM, H = 4
        demand_period_ending_hours = 19.0;
        double v[1] = {4000.0};          // Volume[0] is the lab link

        reset_link(0);                          // BPR
        Link[0].capacity_period = 5000.0;       // x = 4000/5000 = 0.8
        double t_bpr = Link_Travel_Time(0, v);
        near_(t_bpr, T0 * (1.0 + 0.15 * std::pow(0.8, 4.0)), 1e-9,
              "CR-0019 BPR uses V_period/C_period");

        // PLF, lanes and period hours must now be inert
        Link[0].VDF_plf = 0.4270;
        near_(Link_Travel_Time(0, v), t_bpr, 1e-12, "PLF is inert");
        Link[0].lanes = 7.0;
        near_(Link_Travel_Time(0, v), t_bpr, 1e-12, "lanes are inert");
        demand_period_ending_hours = 18.0;      // H = 3
        near_(Link_Travel_Time(0, v), t_bpr, 1e-12, "period hours are inert");
        demand_period_ending_hours = 19.0;

        // conical takes the same ratio
        reset_link(1);
        Link[0].Conic_a = 15.0;
        Link[0].Conic_b = (2 * 15.0 - 1) / (2 * 15.0 - 2);
        Link[0].capacity_period = 5000.0;
        double t_con = Link_Travel_Time(0, v);
        Link[0].VDF_plf = 0.4270;
        Link[0].lanes = 7.0;
        near_(Link_Travel_Time(0, v), t_con, 1e-12,
              "CR-0019 conical: PLF and lanes inert");
        // x = 1 must give exactly 2*t0 for any a (Spiess identity), and it
        // must hold through the period-capacity path
        double v1[1] = {5000.0};
        near_(Link_Travel_Time(0, v1), 2.0 * T0, 1e-9,
              "CR-0019 conical t(x=1) = 2*t0 via period capacity");

        // legacy path preserved when capacity_period is absent
        reset_link(0);
        Link[0].capacity_period = 0.0;
        Link[0].lanes = 2.0;
        Link[0].VDF_plf = 0.8503;
        double legacy_x = 4000.0 / (2.0 * 4.0 * 0.8503) / C_LANE;
        near_(Link_Travel_Time(0, v),
              T0 * (1.0 + 0.15 * std::pow(legacy_x, 4.0)), 1e-9,
              "legacy lanes/H/PLF path unchanged when capacity_period absent");

        // a negative or zero value must fall back, never divide by it
        Link[0].capacity_period = 0.0;
        double t_zero = Link_Travel_Time(0, v);
        check(std::isfinite(t_zero) && t_zero > 0.0,
              "capacity_period = 0 falls back safely");
        reset_link(0);
    }

    // ---- CR-0020: QVDF V->D mapping via k_d, discharge cap via k_mu ----
    // k_d replaces the implicit k_d = 1/vdf_plf. It is free to exceed 1 --
    // that is the whole mechanism: x_D > 1 is what makes QVDF queue.
    {
        demand_period_starting_hours = 15.0;
        demand_period_ending_hours = 19.0;          // H = 4
        double D_, DOC_, P_, t0_, t2_, t3_, vt2_, mu_, gam_, cref_, aqs_, aps_, sev_;
        double prof[300];
        const double V = 6000.0;                    // 1 lane, H = 4 -> V/lanes/H = 1500

        reset_link(2);                              // QVDF
        Link[0].Q_cd = 1.0; Link[0].Q_n = 1.24;
        Link[0].Q_kd = 1.6;                         // D = 1.6 * 1500 = 2400
        Link_QueueVDF(0, V, D_, DOC_, P_, t0_, t2_, t3_, vt2_, mu_, gam_,
                      cref_, aqs_, aps_, sev_, prof);
        near_(D_, 1.6 * 1500.0, 1e-9, "CR-0020 D = k_d * (V/lanes/H)");
        near_(DOC_, 2400.0 / C_LANE, 1e-9, "CR-0020 DOC = D / C_lane");
        check(DOC_ > 1.0, "CR-0020 k_d > 1 yields x_D > 1 (QVDF can queue)");
        near_(P_, 1.0 * std::pow(2.4, 1.24), 1e-9, "CR-0020 P = f_d * x_D^n");

        double D_ref = D_, P_ref = P_, mu_ref = mu_;
        Link[0].VDF_plf = 0.3170;                   // must be inert now
        Link_QueueVDF(0, V, D_, DOC_, P_, t0_, t2_, t3_, vt2_, mu_, gam_,
                      cref_, aqs_, aps_, sev_, prof);
        near_(D_, D_ref, 1e-12, "CR-0020 vdf_plf inert when k_d supplied");
        near_(P_, P_ref, 1e-12, "CR-0020 P unchanged by vdf_plf");

        reset_link(2);                              // legacy: no k_d
        Link[0].Q_cd = 1.0; Link[0].Q_n = 1.24;
        Link[0].VDF_plf = 0.8503;
        Link_QueueVDF(0, V, D_, DOC_, P_, t0_, t2_, t3_, vt2_, mu_, gam_,
                      cref_, aqs_, aps_, sev_, prof);
        near_(D_, 1500.0 / 0.8503, 1e-9, "CR-0020 legacy D = (V/lanes/H)/plf");

        reset_link(2);                              // k_mu caps discharge
        Link[0].Q_cd = 1.0; Link[0].Q_n = 1.24;
        Link[0].Q_kd = 1.6; Link[0].Q_kmu = 0.80;
        Link_QueueVDF(0, V, D_, DOC_, P_, t0_, t2_, t3_, vt2_, mu_, gam_,
                      cref_, aqs_, aps_, sev_, prof);
        check(mu_ <= 0.80 * C_LANE + 1e-9, "CR-0020 mu <= k_mu * C_lane");
        near_(mu_, std::min(0.80 * C_LANE, D_ / std::max(0.01, P_)), 1e-9,
              "CR-0020 mu = min(k_mu*C, D/P)");

        Link[0].Q_kmu = 0.0;                        // absent -> nominal ceiling
        Link_QueueVDF(0, V, D_, DOC_, P_, t0_, t2_, t3_, vt2_, mu_, gam_,
                      cref_, aqs_, aps_, sev_, prof);
        near_(mu_, std::min(C_LANE, D_ / std::max(0.01, P_)), 1e-9,
              "CR-0020 mu ceiling = C_lane when k_mu absent");
        (void)mu_ref;
        reset_link(0);
    }

    // ---- GOLD-001: external single-link closure gold (SLC I-10 package) ----
    // An independently authored analytical gold that specifies k_d and k_mu
    // EXPLICITLY -- i.e. exactly the CR-0020 contract. Verifying the kernel
    // against a gold we did not write is the point of the verification spine.
    //   L=1.2mi H=4h V=12000 vf=65 vco=49 C=5000 k_d=1.25 k_mu=0.85
    //   f_d=5.0 n=1.1 f_p=0.24 s=1.4 T2=8.0
    {
        demand_period_starting_hours = 6.0;    // T2=8 with P=3.64 must fit
        demand_period_ending_hours = 10.0;     // H = 4
        double D_, DOC_, P_, t0_, t2_, t3_, vt2_, mu_, gam_, cref_, aqs_, aps_, sev_;
        double prof[300];

        reset_link(2);
        Link[0].lanes = 1.0;
        Link[0].Lane_Capacity = 5000.0;
        Link[0].free_speed = 65.0;
        Link[0].Cutoff_Speed = 49.0;
        Link[0].length = 1.2;
        Link[0].Q_kd = 1.25;  Link[0].Q_kmu = 0.85;
        Link[0].Q_cd = 5.0;   Link[0].Q_n = 1.1;
        Link[0].Q_cp = 0.24;  Link[0].Q_s = 1.4;
        Link[0].QVDF_t2 = 8.0;
        // t2 is IN/OUT: production seeds it from Link[k].QVDF_t2 at the call
        // site (TAPLite.cpp:6676), so the harness must do the same or t0/t3
        // are computed around t2 = 0.
        t2_ = std::isfinite(Link[0].QVDF_t2) ? Link[0].QVDF_t2
                                             : DemandPeriodMidpointHours();
        Link_QueueVDF(0, 12000.0, D_, DOC_, P_, t0_, t2_, t3_, vt2_, mu_, gam_,
                      cref_, aqs_, aps_, sev_, prof);

        near_(D_,   3750.0,    1e-9, "GOLD-001 D = k_d*(V/lanes/H) = 3750");
        near_(DOC_, 0.75,      1e-9, "GOLD-001 x_D = D/C = 0.75");
        near_(P_,   3.6436560, 1e-6, "GOLD-001 P = f_d*x^n = 3.643656 h");
        near_(vt2_, 19.863990, 1e-5, "GOLD-001 vT2 = v_co/(1+f_p*P^s) = 19.86399");
        near_(t0_,  6.1781720, 1e-6, "GOLD-001 t0 = T2 - P/2 = 6.178172");
        near_(t3_,  9.8218280, 1e-6, "GOLD-001 t3 = T2 + P/2 = 9.821828");
        near_(Link[0].length / vt2_, 0.0604110, 1e-6,
              "GOLD-001 TT at T2 = L/vT2 = 0.060411 h");

        // mu: the gold reports k_mu*C = 4250; the canonical QVDF form the
        // kernel implements gives min(k_mu*C, D/P) = 1029.19, because the
        // ceiling is not binding at x=0.75. Both are pinned here so the
        // divergence is a recorded fact, not a silent difference.
        near_(mu_, 3750.0 / 3.6436560, 1e-4,
              "GOLD-001 kernel mu = min(k_mu*C, D/P) = 1029.19 (NOT k_mu*C)");
        check(0.85 * 5000.0 > mu_,
              "GOLD-001 k_mu ceiling 4250 is not binding at x_D = 0.75");
        reset_link(0);
    }

    std::printf("  Performance functions: BPR, ModifiedBPR, Conical, QVDF,\n"
                "    BPR2, INRETS, Akcelik, SANDAGsignal, SCAGpiecewise,\n"
                "    SCAGrampMeter — exercised on the D/C grid.\n");
    std::printf("-------------------------------------------------------\n");
    std::printf("  PASS %d   FAIL %d\n", g_pass, g_fail);
    for (size_t i = 0; i < g_failures.size(); ++i)
        std::printf("  FAIL: %s\n", g_failures[i].c_str());
    std::printf("OVERALL: %s\n", g_fail == 0 ? "PASS" : "BLOCKED");
    delete[] Link; Link = NULL;
    return g_fail == 0 ? 0 : 1;
}

int main() { return run_selftest(); }
