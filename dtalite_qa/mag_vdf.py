"""MAG New-2015 VDF table (free-flow speed + BPR alpha/beta by Area Type x
Facility Type, keyed by vdf_code = AT*100 + FT). Digitized from the official MAG
2015 VDF reference (updated 2016.07).

Used by `adapt --mag-vdf-2015` to overwrite a MAG network's vdf_alpha / vdf_beta /
free_speed with the calibrated 2015 values (the shipped networks were found to
carry stale alpha/beta -- ~96% mismatch). Centroid-connector codes (xx5) have no
alpha/beta and are left untouched.
"""

# vdf_code -> (free_flow_speed_mph, alpha, beta);  None alpha/beta = connector
NEW_2015 = {
    100: (70, 0.74, 4.60), 101: (70, 0.99, 3.50), 102: (47, 5, 2.00), 103: (25, 1.8, 1.90),
    104: (37, 3.9, 1.50), 105: (15, None, None), 106: (35, 1.8, 1.90), 107: (39, 1.8, 1.90),
    108: (30, 1.8, 1.90), 109: (50, 0.87, 5.00), 110: (47, 1.8, 1.90), 111: (15, 1.8, 1.90),
    200: (70, 1.88, 3.10), 201: (70, 0.99, 3.50), 202: (49, 5, 2.00), 203: (28, 1.8, 1.90),
    204: (39, 8, 2.00), 205: (20, None, None), 206: (40, 1.8, 1.90), 207: (40, 1.8, 1.90),
    208: (30, 1.8, 1.90), 209: (53, 0.75, 4.00), 210: (49, 1.8, 1.90), 211: (20, 1.8, 1.90),
    300: (75, 1.88, 3.10), 301: (71, 0.99, 3.50), 302: (55, 5, 2.00), 303: (37, 2.6, 2.00),
    304: (41, 3.2, 2.50), 305: (25, None, None), 306: (41, 2.6, 2.00), 307: (44, 2.6, 2.00),
    308: (30, 2.6, 2.00), 309: (57, 0.71, 3.47), 310: (55, 2.6, 2.00), 311: (25, 2.6, 2.00),
    400: (75, 1.88, 3.10), 401: (71, 4, 6), 402: (55, 20, 2.50), 403: (39, 3.6, 2.50),
    404: (42, 3.2, 2.50), 405: (25, None, None), 406: (41, 3.6, 2.50), 407: (44, 3.6, 2.50),
    408: (30, 3.6, 2.50), 409: (59, 0.71, 3.47), 410: (55, 3.6, 2.50), 411: (25, 3.6, 2.50),
    500: (75, 1.88, 3.10), 501: (72, 400, 6), 502: (57, 20, 2.50), 503: (40, 3.6, 2.50),
    504: (43, 3.6, 2.50), 505: (30, None, None), 506: (42, 3.6, 2.50), 507: (46, 3.6, 2.50),
    508: (30, 3.6, 2.50), 509: (61, 0.71, 3.47), 510: (57, 3.6, 2.50), 511: (30, 3.6, 2.50),
}


def apply_to_rows(rows, set_free_speed=True):
    """In place: set vdf_alpha/vdf_beta (and free_speed/vdf_free_speed_mph) from
    NEW_2015 by each row's vdf_code. Returns (n_applied, n_mismatch_replaced)."""
    n = 0
    for r in rows:
        code = (r.get("vdf_code") or "").split(".")[0]
        if not code.isdigit():
            continue
        tv = NEW_2015.get(int(code))
        if not tv or tv[1] is None:
            continue
        ffs, a, b = tv
        r["vdf_alpha"] = a
        r["vdf_beta"] = b
        if set_free_speed and ffs:
            r["vdf_free_speed_mph"] = ffs
            r["free_speed"] = ffs
        n += 1
    return n
