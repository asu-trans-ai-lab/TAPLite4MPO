// Independent C++ twin — PR-2 (CR-0007).
//
// Reference implementations of every TAPLite performance function, written
// FROM THE SPECIFICATION (USER_GUIDE_VOL2 §3 + spec/performance_functions),
// deliberately boring, scalar and slow. This header/TU must NEVER include or
// call production code (TAPLite.cpp / Link_Travel_Time). The only shared
// vocabulary is the neutral VdfInput struct below.
//
// Acceptance (twin_differential): production ≈ twin on the full grid.

#ifndef TAPLITE_TWIN_VDF_HPP
#define TAPLITE_TWIN_VDF_HPP

struct VdfInput {
    // demand side (per link)
    double volume = 0.0;            // vehicles over the period
    double lanes = 1.0;
    double period_hours = 1.0;
    double plf = 1.0;               // peak load factor (phi/L)
    // supply side
    double capacity_per_lane = 1000.0;  // veh/h/lane
    double fftt_min = 10.0;         // free-flow travel time, minutes
    double length_mile = 5.0;
    double free_speed_mph = 60.0;
    double cutoff_speed_mph = 45.0;
    // parameters (meaning depends on function — the twin takes them
    // explicitly; no column aliasing exists here by construction)
    double alpha = 0.15;            // BPR-family alpha
    double beta = 4.0;              // BPR-family beta
    double mbpr_A = 0.0;            // ARC modified-BPR linear term
    double conic_a = 0.0;
    double conic_b = 0.0;           // 0 => derive (2a-1)/(2a-2)
    double q_cp = 0.28125, q_cd = 1.0, q_n = 1.24, q_s = 4.0;
    double green_ratio = 0.45;
    double cycle_length_s = 90.0;
    double scag_uncongested_beta = 4.0;
    double added_delay_per_mile = 0.0;  // MAG additive term
};

// Per-lane hourly demand rate and per-lane V/C (the shared preamble).
double twin_incoming_demand(const VdfInput& in);
double twin_voc(const VdfInput& in);

// The nine forms (minutes returned; >= 0):
double twin_bpr(const VdfInput& in);            // kernel_id 0 (incl. modified)
double twin_conical(const VdfInput& in);        // kernel_id 1
double twin_qvdf(const VdfInput& in);           // kernel_id 2 (period-average)
double twin_bpr2(const VdfInput& in);           // kernel_id 3
double twin_inrets(const VdfInput& in);         // kernel_id 4
double twin_akcelik(const VdfInput& in);        // kernel_id 5
double twin_sandag_signal(const VdfInput& in);  // kernel_id 6
double twin_scag_piecewise(const VdfInput& in); // kernel_id 7
double twin_scag_ramp_meter(const VdfInput& in);// kernel_id 8

// dispatch by kernel id (applies the MAG additive term + zero clamp,
// mirroring the specified post-processing)
double twin_travel_time(int kernel_id, const VdfInput& in);

#endif
