"""Canonical GMNS schema and kernel default values for the DTALite/TAPLite kernel.

The default values here mirror what the C++ kernel uses internally
(link_record constructor + ReadLinks + createSettingsFile/createModeTypeFile),
so the filler produces an explicit, normalized network that runs identically but
leaves nothing implicit.
"""

# link.csv -------------------------------------------------------------------
# Hard-required (no sensible default; validation errors if missing/invalid).
LINK_REQUIRED = ["from_node_id", "to_node_id", "lanes", "capacity", "free_speed"]

# Optional columns the kernel reads, with the default it falls back to.
# (cutoff_speed default is derived as 0.75*free_speed and handled specially.)
LINK_DEFAULTS = {
    "link_type": 1,
    "vdf_type": 0,        # 0 BPR · 1 conic · 2 QVDF · 3 BPR2 · 4 INRETS · 5 Akcelik · 6 SANDAG-signal
    "vdf_alpha": 0.15,
    "vdf_A": 0,           # ARC modified-BPR linear term: fftt*(1 + A*(v/c) + alpha*(v/c)^beta); 0 = standard BPR
    "vdf_beta": 4,
    "green_ratio": 0.45,  # SANDAG vdf_type=6 signal green ratio g/C (Webster intersection delay)
    "vdf_plf": 1,
    "vdf_cp": 0.28125,
    "vdf_cd": 1.0,
    "vdf_n": 1.0,
    "vdf_s": 4,
    "non_uturn_flag": 0,
    "ref_volume": 0,
    "vdf_toll": 0,
    "allowed_use": "",    # empty == all modes allowed
}
# QVDF parameters required to be meaningful when vdf_type == 2.
LINK_QVDF_COLS = ["vdf_cp", "vdf_cd", "vdf_n", "vdf_s"]

# node.csv -------------------------------------------------------------------
NODE_REQUIRED = ["node_id", "zone_id", "x_coord", "y_coord"]
NODE_DEFAULTS = {"zone_id": 0}

# settings.csv (single row) --------------------------------------------------
SETTINGS_COLUMNS = [
    "number_of_iterations", "number_of_processors",
    "demand_period_starting_hours", "demand_period_ending_hours",
    "first_through_node_id", "base_demand_mode", "route_output",
    "vehicle_output", "log_file", "odme_mode", "odme_vmt", "demand_format",
    "added_delay_per_mile", "convergence_gap_pct", "convergence_consecutive",
]
SETTINGS_DEFAULTS = {
    "number_of_iterations": 20, "number_of_processors": 8,
    "demand_period_starting_hours": 7, "demand_period_ending_hours": 8,
    "first_through_node_id": -1, "base_demand_mode": 0, "route_output": 1,
    "vehicle_output": 0, "log_file": 0, "odme_mode": 0, "odme_vmt": 0,
    "demand_format": 0,   # 0 = CSV (default), 1 = binary (.bin via demand-bin)
    "added_delay_per_mile": 0,  # MAG VDF: T_c + this*L(mi); MAG uses 1.4 (0 = pure BPR)
    "convergence_gap_pct": 0,   # stop FW when gap% < this (0 = run all iterations)
    "convergence_consecutive": 1,  # require gap% below target for this many consecutive iters (ARC: 3)
    "relative_gap_standard": 0,  # 0 = gap normalized by AoN total (legacy); 1 = by current total (AequilibraE std)
    "assignment_method": 0,  # 0 = Frank-Wolfe (default); 1 = conjugate FW (CFW); 2 = bi-conjugate FW (BFW)
}

# mode_type.csv --------------------------------------------------------------
MODE_DEFAULTS = {
    "vot": 10, "pce": 1, "occ": 1, "dedicated_shortest_path": 1,
    "operating_cost": 0,  # ARC generalized cost: $/mile distance term (0 = off)
    "demand_file": "demand.csv", "name": "",
}

# demand.csv -----------------------------------------------------------------
DEMAND_REQUIRED = ["o_zone_id", "d_zone_id", "volume"]

# movement.csv ---------------------------------------------------------------
MOVEMENT_COLUMNS = ["mvmt_id", "node_id", "ib_link_id", "ob_link_id", "penalty"]
MOVEMENT_BAN_PENALTY = 10  # penalty >= this => forbidden movement


def is_all_allowed(allowed_use):
    """True if the allowed_use token means 'all modes' (empty or 'all')."""
    s = (allowed_use or "").strip().lower()
    return s == "" or s == "all"


def is_closed(allowed_use):
    return (allowed_use or "").strip().lower() == "closed"


def mode_allowed(allowed_use, mode_token):
    """Replicate the kernel's substring match: a link permits a mode if
    allowed_use is empty/'all', or the mode token appears as a substring."""
    if is_all_allowed(allowed_use):
        return True
    if is_closed(allowed_use):
        return False
    return mode_token in allowed_use
