from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import numpy as np

from ..resources.congestion_t_node_pair_lookup.load_node_pair_boundaries import (
    BOUNDARY_FIELDS,
    load_period,
    lookup,
    period_path,
)


def apply_congestion_boundaries(
    network,
    period: str,
    lookup_directory: Optional[Union[str, Path]] = None,
):
    """Add period-specific observed T0/T2/T3 values to converted links."""
    period_name = str(period).lower()
    links = list(network.link_dict.values())

    # Keep one stable link.csv schema across periods and parallel chunks.
    # A blank value tells the kernel to use its existing analytical fallback.
    for link in links:
        for field in BOUNDARY_FIELDS:
            link.other_attrs[field] = ""

    lookup_path = period_path(period_name, lookup_directory)
    if not lookup_path.is_file():
        stats = {
            "period": period_name,
            "available": False,
            "lookup_path": str(lookup_path),
            "links": len(links),
            "matched": 0,
            "unmatched": len(links),
        }
        network.congestion_boundary_stats = stats
        print(
            f"Congestion boundary lookup {period_name.upper()}: no lookup table; "
            f"{', '.join(BOUNDARY_FIELDS)} left blank for {len(links):,} links."
        )
        return stats

    table = load_period(period_name, lookup_directory)
    from_node_ids = np.fromiter(
        (link.from_node.node_id for link in links),
        dtype=np.uint64,
        count=len(links),
    )
    to_node_ids = np.fromiter(
        (link.to_node.node_id for link in links),
        dtype=np.uint64,
        count=len(links),
    )
    values, found = lookup(table, from_node_ids, to_node_ids)

    for link_index in np.flatnonzero(found):
        link = links[int(link_index)]
        for field_index, field in enumerate(BOUNDARY_FIELDS):
            value = values[link_index, field_index]
            link.other_attrs[field] = float(value) if np.isfinite(value) else ""

    matched = int(np.count_nonzero(found))
    stats = {
        "period": period_name,
        "available": True,
        "lookup_path": str(lookup_path),
        "links": len(links),
        "matched": matched,
        "unmatched": len(links) - matched,
    }
    network.congestion_boundary_stats = stats
    print(
        f"Congestion boundary lookup {period_name.upper()}: matched "
        f"{matched:,} of {len(links):,} converted links; "
        f"{len(links) - matched:,} left blank."
    )
    return stats
