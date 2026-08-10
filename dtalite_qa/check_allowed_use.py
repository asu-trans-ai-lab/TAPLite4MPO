"""Formal gate: allowed_use conformance against a reference assignment.

WHY THIS IS NOT A SIMPLE ZERO TEST
----------------------------------
A class having zero volume on a link does NOT mean the class is prohibited.
Airport vans must be permitted network-wide so they can reach the airport at
all; most links will still carry zero of them simply because no path routes
there. Treating every zero as a lost restriction produces thousands of false
positives and hides the handful of real ones.

The discriminator is EXPECTED volume. If a class carries share s_k of the
network's vehicles, a facility carrying V vehicles would be expected to see
about s_k * V of that class. Then:

    observed ~ 0  AND  expected LARGE   -> the class is being kept off
                                           deliberately: a real restriction
    observed ~ 0  AND  expected SMALL   -> no evidence either way; the zero
                                           is explained by absence of demand
    observed > 0                        -> the class uses the link and MUST
                                           be permitted

The test is applied at FACILITY level (all links of a corridor sharing a
facility class), not per link, because a restriction is a property of the
facility. A single zero link inside an otherwise-used facility is a routing
outcome, not a rule.

Verdicts
--------
RESTRICTION_LOST        reference keeps the class off a facility where it
                        would be expected in quantity, but allowed_use
                        permits it -> the converted network will load a
                        class the reference excludes. BLOCKER.
RESTRICTION_TOO_TIGHT   reference uses the class but allowed_use forbids it
                        -> the model can never reproduce that volume. BLOCKER.
CONSISTENT_USED         used and permitted.
CONSISTENT_EXCLUDED     unused and forbidden.
INSUFFICIENT_EVIDENCE   unused, permitted, but the evidence cannot separate a
                        restriction from absent demand -- the facility is too
                        small, the expectation too low, or there is no other
                        facility to learn the class share from. NOT a defect;
                        reported so the reviewer can see coverage.

Thresholds are declared parameters, not hidden constants, and MUST be
recorded in the run manifest alongside the verdict counts.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# a class is "not present" below this many vehicles on the whole facility
ABSENT_VEH = 1.0
# minimum EXPECTED vehicles before a zero can be called a restriction
MIN_EXPECTED_VEH = 25.0
# and the zero must be this improbable relative to expectation
MIN_EXPECTED_RATIO = 10.0
# a facility carrying less than this in total is too small to support any
# restriction verdict, however surprising the zero looks in relative terms
MIN_FACILITY_VEH = 500.0


@dataclass
class AllowedUseVerdict:
    ok: bool
    reason: str
    detail: pd.DataFrame
    counts: dict

    def require(self) -> None:
        if not self.ok:
            raise RuntimeError(f"allowed_use gate STOP: {self.reason}")


def check_allowed_use(links: pd.DataFrame, *,
                      facility_col: str = "facility_id",
                      allowed_col: str = "allowed_use",
                      class_volume_cols: dict[str, str],
                      min_expected_veh: float = MIN_EXPECTED_VEH,
                      min_expected_ratio: float = MIN_EXPECTED_RATIO,
                      absent_veh: float = ABSENT_VEH,
                      min_facility_veh: float = MIN_FACILITY_VEH
                      ) -> AllowedUseVerdict:
    """Compare `allowed_use` against a reference model's per-class volumes.

    links               one row per link; must carry `facility_col`,
                        `allowed_col`, and the reference per-class volume
                        columns named in `class_volume_cols`
    class_volume_cols   {class token -> reference volume column}

    Returns a verdict whose `detail` has one row per facility x class.
    """
    df = links.copy()
    df[allowed_col] = df[allowed_col].astype(str)
    classes = list(class_volume_cols)
    for col in class_volume_cols.values():
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # LEAVE-ONE-OUT class shares. The expectation for a facility must come
    # from how the class behaves ELSEWHERE, otherwise a facility that
    # excludes a class drives that class's own expected share toward zero
    # and the exclusion becomes invisible — the very defect being hunted.
    totals = {k: df[c].sum() for k, c in class_volume_cols.items()}

    rows = []
    for fac, g in df.groupby(facility_col, dropna=False):
        fac_total = sum(g[c].sum() for c in class_volume_cols.values())
        rest = {k: totals[k] - float(g[c].sum())
                for k, c in class_volume_cols.items()}
        rest_grand = sum(rest.values())
        share = {k: (v / rest_grand if rest_grand > 0 else 0.0)
                 for k, v in rest.items()}
        closed = (g[allowed_col] == "closed").all()
        for k in classes:
            col = class_volume_cols[k]
            observed = float(g[col].sum())
            expected = share[k] * fac_total
            permitted = bool((g[allowed_col].str.contains(k, regex=False)
                              & (g[allowed_col] != "closed")).any())
            used = observed > absent_veh
            if closed:
                verdict = ("CONSISTENT_EXCLUDED" if not used
                           else "RESTRICTION_TOO_TIGHT")
            elif used and permitted:
                verdict = "CONSISTENT_USED"
            elif used and not permitted:
                verdict = "RESTRICTION_TOO_TIGHT"
            elif not used and not permitted:
                verdict = "CONSISTENT_EXCLUDED"
            else:
                # unused but permitted — is the zero informative? It must
                # clear three bars: the facility is materially sized, the
                # expectation is material in absolute terms, and the
                # shortfall is large in relative terms.
                informative = (fac_total >= min_facility_veh
                               and expected >= min_expected_veh
                               and expected >= min_expected_ratio * max(observed, 1.0))
                verdict = ("RESTRICTION_LOST" if informative
                           else "INSUFFICIENT_EVIDENCE")
            rows.append(dict(
                facility=fac, cls=k, links=len(g),
                permitted=permitted, observed_veh=round(observed, 1),
                expected_veh=round(expected, 1),
                facility_total_veh=round(fac_total, 1),
                network_share=round(share[k], 5),
                verdict=verdict,
                action=("REMOVE from allowed_use"
                        if verdict == "RESTRICTION_LOST" else
                        "ADD to allowed_use"
                        if verdict == "RESTRICTION_TOO_TIGHT" else "")))

    detail = pd.DataFrame(rows)
    counts = detail.verdict.value_counts().to_dict()
    blockers = int(detail.verdict.isin(
        ["RESTRICTION_LOST", "RESTRICTION_TOO_TIGHT"]).sum())
    ok = blockers == 0
    reason = ("allowed_use is consistent with the reference assignment"
              if ok else
              f"{blockers} facility x class blocker(s): "
              f"{counts.get('RESTRICTION_LOST', 0)} lost, "
              f"{counts.get('RESTRICTION_TOO_TIGHT', 0)} too tight")
    return AllowedUseVerdict(ok, reason, detail, counts)


def check_toll_consistency(links: pd.DataFrame, *,
                           toll_cols: dict[str, str],
                           facility_col: str = "facility_id",
                           hov_classes=("hov2", "hov3"),
                           sov_class: str = "sov") -> AllowedUseVerdict:
    """Gate the HOT invariant: on a tolled facility that permits SOV, at
    least one HOV class MUST pay less than SOV. Otherwise the facility is a
    plain toll road and MUST be labelled as one — a managed lane with no
    price differential cannot express managed-lane behaviour."""
    df = links.copy()
    for c in toll_cols.values():
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    rows = []
    for fac, g in df.groupby(facility_col, dropna=False):
        sov_t = g[toll_cols[sov_class]]
        if (sov_t <= 0).all():
            continue                        # untolled facility
        differentials = {
            k: int((g[toll_cols[k]] < sov_t).sum())
            for k in hov_classes if k in toll_cols}
        any_diff = any(v > 0 for v in differentials.values())
        rows.append(dict(
            facility=fac, links=len(g),
            tolled_links=int((sov_t > 0).sum()),
            max_toll_sov=round(float(sov_t.max()), 4),
            **{f"links_{k}_cheaper_than_sov": v
               for k, v in differentials.items()},
            verdict="OK_HOT" if any_diff else "NO_HOV_DIFFERENTIAL",
            action="" if any_diff else
                   "set toll_hov3 = 0 (HOT), or relabel as toll_road_all"))
    detail = pd.DataFrame(rows)
    if detail.empty:
        return AllowedUseVerdict(True, "no tolled facilities", detail, {})
    bad = int((detail.verdict == "NO_HOV_DIFFERENTIAL").sum())
    return AllowedUseVerdict(
        bad == 0,
        ("every tolled facility has an HOV price differential" if bad == 0
         else f"{bad} tolled facility(ies) charge every class the same — "
              f"either set an HOV discount or relabel as toll_road_all"),
        detail, detail.verdict.value_counts().to_dict())
