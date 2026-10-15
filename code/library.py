"""Discover local GSWA summaries and build a checked, reproducible catalog.

Author: Ding Qing
Date: 2026-10-15
"""

from collections import defaultdict
import copy
import csv
import json
from pathlib import Path

import coords
import core_photos
import engine
from datasets import SOURCES, GROUPS, DEMO_HOLES
from summaries import load_summary


ROOT = Path(__file__).resolve().parent
SETTINGS = {
    "SWIR_algorithm": "TSA+", "TIR_algorithm": "jCLST",
    "Bin_min_threshold": "0.05", "Scalar_min_depth": "0.001",
    "N.A.": "Not detected or below threshold",
    "System": "Automated spectral unmixing result",
    "Invalid": "Unclassified e.g. aspectral, noisy, low albedo, high errors",
}


def download_manifest():
    path = ROOT / "download_manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"summaries": []}


def load_library(data_root):
    root = Path(data_root).resolve()
    inbox = root / "inbox"
    issues, candidates = [], defaultdict(list)
    pins = {item["hole_id"]: item for item in download_manifest()["summaries"]}
    paths = [(root / relative, hole, digest, False) for hole, (relative, digest) in SOURCES.items()]
    paths += [(path, None, None, True) for path in sorted(inbox.glob("*.csv"))] if inbox.is_dir() else []
    for path, declared_hole, expected, from_inbox in paths:
        if not path.is_file() and not from_inbox:
            continue
        hole = declared_hole
        try:
            if not path.resolve().is_relative_to(root) or path.is_symlink():
                raise ValueError("Source must be a regular file inside the data directory")
            bundle = load_summary(path, declared_hole)
            source = bundle["source"]
            hole = source["hole_id"]
            pin = pins.get(hole)
            expected = expected or (pin["sha256"] if pin else None)
            if expected and source["sha256"] != expected:
                raise ValueError("File differs from the recorded source version; keep it separate for review")
            metadata = source["metadata"]
            for key, value in SETTINGS.items():
                if " ".join(metadata.get(key, "").split()) != value:
                    raise ValueError(f"Unsupported source processing setting: {key}")
            if not metadata.get("****D", "").startswith("Background normalised depth of dominant spectral feature"):
                raise ValueError("Unsupported absorption-depth definition")
            source.update(relative_path=path.relative_to(root).as_posix(),
                          fingerprint_verified=expected is not None, from_inbox=from_inbox,
                          compatibility_settings=SETTINGS,
                          source_verification="Recorded download checksum" if expected else "Local file; origin not independently verified")
            if pin:
                source["source_url"] = pin["url"]
            else:
                source["suggested_source_url"] = source.pop("source_url")
                source["source_url"] = None
            normal = engine.normalize_records(bundle["records"])
            if normal["rejected_records"] or not normal["records"]:
                raise ValueError("Invalid, overlapping or empty depth records; file excluded as a whole")
            if source["field_aliases"]:
                issues.append({"hole_id": hole, "source_filename": path.name, "reason": "field_alias",
                               "detail": "Explicit column alias applied; original row names are preserved.",
                               "aliases": source["field_aliases"]})
            candidates[hole].append(bundle)
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            issues.append({"hole_id": hole, "source_filename": path.name, "reason": "source_rejected",
                           "detail": str(error) if not isinstance(error, OSError) else type(error).__name__})
    records, sources = [], []
    for hole, bundles in sorted(candidates.items()):
        digests = {item["source"]["sha256"] for item in bundles}
        if len(digests) > 1:
            issues.append({"hole_id": hole, "reason": "conflicting_versions", "source_filename": None,
                           "detail": "Several different files identify this hole. No version was selected."})
            continue
        bundle = bundles[0]
        if len(bundles) > 1:
            issues.append({"hole_id": hole, "reason": "duplicate_ignored", "source_filename": None,
                           "detail": f"{len(bundles) - 1} identical copies ignored."})
        records.extend(bundle["records"])
        sources.append(bundle["source"])
    if not sources:
        raise ValueError("No supported summaries found. Place original GSWA Summary CSVs directly in data/inbox. "
                         + "; ".join(item["detail"] for item in issues[:5]))
    holes = [item["hole_id"] for item in sources]
    catalog = engine.catalog_from_records(records, sources, coords.load_coordinates(root, holes), hole_ids=holes)
    catalog["audit"]["issues"].extend(issues)
    catalog["audit"]["source_issues"] = issues
    available = set().union(*(set(source["fields"]) for source in sources))
    catalog["metric_registry"] = {key: value for key, value in catalog["metric_registry"].items() if key in available}
    catalog["manifest"]["metric_ids"] = sorted(catalog["metric_registry"])
    catalog["versions"]["data_manifest_hash"] = engine._hash(catalog["manifest"])
    catalog["versions"]["metric_registry_hash"] = engine._hash(catalog["metric_registry"])
    catalog["groups"] = [dict(group, hole_ids=[hole for hole in group["hole_ids"] if hole in holes]) for group in GROUPS]
    catalog["groups"] = [group for group in catalog["groups"] if group["hole_ids"]]
    added = sorted(set(holes) - set(SOURCES))
    if added:
        extent = max(row["to_m"] for row in catalog["records"] if row["hole_id"] in added)
        catalog["groups"].append({"id": "library", "label": "Added to library", "hole_ids": added,
                                  "depth_from_m": 0, "depth_to_m": extent})
        for hole in catalog["holes"]:
            if hole["hole_id"] in added:
                hole["group_id"] = "library"
    catalog["default_query"] = copy.deepcopy(engine.DEFAULT_QUERY)
    if not set(DEMO_HOLES).issubset(holes):
        catalog["default_query"].update(hole_ids=holes[:3], depth_from_m=0,
                                        depth_to_m=max(row["to_m"] for row in catalog["records"]))
    catalog["library"] = {"inbox": "inbox", "accepted_count": len(holes),
                          "inbox_accepted_count": sum(source["from_inbox"] for source in sources),
                          "issues": issues, "refresh_policy": "Place CSVs in data/inbox, then Refresh library or restart.",
                          "data_root": str(root), "inbox_path": str(inbox)}
    photos, photo_files, photo_issues = core_photos.index_photos(root, holes)
    catalog["core_images"] = photos
    catalog["core_image_files"] = photo_files
    catalog["core_image_issues"] = photo_issues
    catalog["versions"]["data_manifest_hash"] = engine._hash(catalog["manifest"])
    return catalog
