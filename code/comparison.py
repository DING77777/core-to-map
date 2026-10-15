"""Find scalars supported by the selected holes and depth window.

Author: Ding Qing
Date: 2026-10-15
"""

import math

from metrics import canonical_metric


def availability(catalog, scope):
    from engine import _integer

    required = {"hole_ids", "depth_from_m", "depth_to_m"}
    if not isinstance(scope, dict) or set(scope) != required:
        raise ValueError("Availability requires hole_ids, depth_from_m and depth_to_m")
    requested = scope["hole_ids"]
    if not isinstance(requested, list) or not all(isinstance(hole, str) and hole for hole in requested):
        raise ValueError("hole_ids must be a list of hole names")
    chosen = set(requested)
    known = {hole["hole_id"] for hole in catalog["holes"]}
    if chosen - known:
        raise ValueError("Unknown hole_ids: " + ", ".join(sorted(chosen - known)))
    start = _integer(scope["depth_from_m"], "depth_from_m")
    end = _integer(scope["depth_to_m"], "depth_to_m")
    if start < 0 or end <= start:
        raise ValueError("Depth window must satisfy 0 <= from < to")

    registry = catalog["metric_registry"]
    counts = {metric: 0 for metric in registry}
    holes = {metric: set() for metric in registry}
    for row in catalog["records"]:
        if row["hole_id"] not in chosen or row["from_m"] < start or row["to_m"] > end:
            continue
        aliases = row.get("field_aliases", {})
        tokens = {canonical_metric(aliases.get(field, field)): token
                  for field, token in row.get("raw_row", {}).items()}
        tokens[row["metric_id"]] = row["raw_token"]
        for metric, token in tokens.items():
            if metric not in registry:
                continue
            try:
                value = float(str(token).strip())
            except (ValueError, TypeError, OverflowError):
                continue
            if math.isfinite(value) and value >= registry[metric]["minimum_valid_value"]:
                counts[metric] += 1
                holes[metric].add(row["hole_id"])

    metrics = []
    for metric in registry:
        count = counts[metric]
        if not chosen:
            reason = "Select at least one hole"
        elif not count:
            reason = "No numeric values in the selected holes and depth range"
        else:
            reason = f"{count} numeric records across {len(holes[metric])} of {len(chosen)} holes"
        metrics.append({"metric_id": metric, "numeric_count": count,
                        "holes_with_values": len(holes[metric]), "hole_count": len(chosen),
                        "enabled": count > 0, "reason": reason})
    return {"metrics": metrics}
