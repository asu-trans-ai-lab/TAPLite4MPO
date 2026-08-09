// Independent C++ twin implementations — written from the specification
// (USER_GUIDE_VOL2 §3), NOT from TAPLite.cpp. Deliberately scalar and plain.
// This TU never includes production code.

#include "twin_vdf.hpp"
#include <cmath>
#include <algorithm>

double twin_incoming_demand(const VdfInput& in) {
    double lanes = std::max(0.01, in.lanes);
    double H = std::max(0.001, in.period_hours);
    double plf = std::max(0.0001, in.plf);
    return in.volume / lanes / H / plf;
}

double twin_voc(const VdfInput& in) {
    return twin_incoming_demand(in) / std::max(0.1, in.capacity_per_lane);
}

double twin_bpr(const VdfInput& in) {
    double x = twin_voc(in);
    return in.fftt_min * (1.0 + in.mbpr_A * x
                          + in.alpha * std::pow(x, in.beta));
}

double twin_conical(const VdfInput& in) {
    double x = twin_voc(in);
    double a = in.conic_a;
    double b = (in.conic_b > 0.0) ? in.conic_b
                                  : (2.0 * a - 1.0) / (2.0 * a - 2.0);
    double om = 1.0 - x;
    return in.fftt_min * (2.0 + std::sqrt(a * a * om * om + b * b)
                          - a * om - b);
}

double twin_qvdf(const VdfInput& in) {
    // Period-average congested speed model (spec: queue speed + congestion
    // period P = cd * DOC^n blended over the assignment period H).
    double DOC = twin_voc(in);
    double cong_ref = (DOC < 1.0)
        ? (1.0 - DOC) * in.free_speed_mph + DOC * in.cutoff_speed_mph
        : in.cutoff_speed_mph;
    double q_speed = cong_ref / (1.0 + in.alpha * std::pow(DOC, in.beta));
    double P = in.q_cd * std::pow(DOC, in.q_n);
    double H = std::max(0.001, in.period_hours);
    double period_speed = (P > H)
        ? q_speed
        : (P / H) * q_speed
          + (1.0 - P / H) * (cong_ref + in.free_speed_mph) / 2.0;
    return in.length_mile / std::max(0.1, period_speed) * 60.0;
}

double twin_bpr2(const VdfInput& in) {
    double x = twin_voc(in);
    double e = (x <= 1.0) ? in.beta : 2.0 * in.beta;
    return in.fftt_min * (1.0 + in.alpha * std::pow(x, e));
}

double twin_inrets(const VdfInput& in) {
    double x = twin_voc(in);
    if (x <= 1.0)
        return in.fftt_min * (1.1 - in.alpha * x)
               / std::max(0.05, 1.1 - x);
    return in.fftt_min * ((1.1 - in.alpha) / 0.1) * x * x;
}

double twin_akcelik(const VdfInput& in) {
    double x = twin_voc(in);
    double z = x - 1.0;
    return in.fftt_min
           + in.alpha * (z + std::sqrt(z * z + in.beta * x));
}

double twin_sandag_signal(const VdfInput& in) {
    double x = twin_voc(in);
    double bpr = in.fftt_min * (1.0 + in.alpha * std::pow(x, in.beta));
    double g = std::min(0.95, std::max(0.05, in.green_ratio));
    double C = std::max(0.0, in.cycle_length_s);
    double d_min = 0.5 * C * (1.0 - g) * (1.0 - g)
                   / std::max(0.05, 1.0 - std::min(1.0, x) * g) / 60.0;
    return bpr + d_min;
}

double twin_scag_piecewise(const VdfInput& in) {
    double x = twin_voc(in);
    double e = (x <= 1.0) ? in.scag_uncongested_beta : in.beta;
    return in.fftt_min * (1.0 + in.alpha * std::pow(x, e));
}

double twin_scag_ramp_meter(const VdfInput& in) {
    double x = twin_voc(in);
    double plph = twin_incoming_demand(in);
    double delay_hr = (plph / 120.0) * 5.0 * std::pow(1.0 + x, 8.0) / 60.0;
    return in.fftt_min + delay_hr * 60.0;
}

double twin_travel_time(int kernel_id, const VdfInput& in) {
    double t;
    switch (kernel_id) {
        case 1: t = twin_conical(in); break;
        case 2: t = twin_qvdf(in); break;
        case 3: t = twin_bpr2(in); break;
        case 4: t = twin_inrets(in); break;
        case 5: t = twin_akcelik(in); break;
        case 6: t = twin_sandag_signal(in); break;
        case 7: t = twin_scag_piecewise(in); break;
        case 8: t = twin_scag_ramp_meter(in); break;
        default: t = twin_bpr(in); break;
    }
    if (in.added_delay_per_mile != 0.0)
        t += in.added_delay_per_mile * in.length_mile;
    return (t < 0.0) ? 0.0 : t;
}
