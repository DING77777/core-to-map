"""Numeric scalar extents across each hole's accepted source records.

Author: Ding Qing
Date: 2026-10-15
"""

import math

from metrics import canonical_metric


def summarize(catalog):
    registry = catalog["metric_registry"]
    result = {
        hole["hole_id"]: {
            metric: {"from_m": None, "to_m": None, "numeric_count": 0}
            for metric in registry
        }
        for hole in catalog["holes"]
    }
    for row in catalog["records"]:
        ranges = result.get(row["hole_id"])
        if ranges is None:
            continue
        aliases = row.get("field_aliases", {})
        tokens = {
            canonical_metric(aliases.get(field, field)): token
            for field, token in row.get("raw_row", {}).items()
        }
        tokens[canonical_metric(row["metric_id"])] = row["raw_token"]
        for metric, token in tokens.items():
            if metric not in registry:
                continue
            try:
                value = float(str(token).strip())
            except (ValueError, TypeError, OverflowError):
                continue
            if not math.isfinite(value) or value < registry[metric]["minimum_valid_value"]:
                continue
            extent = ranges[metric]
            extent["from_m"] = row["from_m"] if extent["from_m"] is None else min(extent["from_m"], row["from_m"])
            extent["to_m"] = row["to_m"] if extent["to_m"] is None else max(extent["to_m"], row["to_m"])
            extent["numeric_count"] += 1
    return result
