"""Build the small regional basemap from complete public Natural Earth ZIPs.

Python standard library only. Run:
  python build_basemap.py --sources PATH_TO_ZIPS --output basemap.json
No network access, borehole data, or application code is used by this builder.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import zipfile

BBOX = (112.0, -44.0, 154.0, -10.0)
SOURCE_FILES = (
    ("ne_10m_admin_0_countries.zip", "land"),
    ("ne_10m_lakes.zip", "lakes"),
    ("ne_10m_lakes_australia.zip", "lakes"),
    ("ne_10m_roads.zip", "roads"),
    ("ne_10m_populated_places_simple.zip", "places"),
)
EXPECTED_SHA256 = {
    "ne_10m_admin_0_countries.zip": "ce1ac7036499a0edd641fbc093cd209a98f96a49d2eca8480aaacad35138a7f6",
    "ne_10m_lakes.zip": "0803a06f9c3cb4671d89b68c48b142aad9366ba40f665245e12a913fbc61722a",
    "ne_10m_lakes_australia.zip": "44c604c90ae459947b41f082973d58a7f0a1da61e9928ee89464ba7a8b00e00e",
    "ne_10m_roads.zip": "880b235383a1e1ccf33f4ea6f82b6755a2ffbce07e3974e412b43e88fe954ae9",
    "ne_10m_populated_places_simple.zip": "2963ee08f7743f13f37d5243acd77a2f7a510e26a36c7e04b920f1b381f2b251",
}


def overlap(box):
    return box[2] >= BBOX[0] and box[0] <= BBOX[2] and box[3] >= BBOX[1] and box[1] <= BBOX[3]


def bounds(points):
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def signed_area(ring):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:])) / 2


def contains(ring, point):
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:]):
        if (a[1] > y) != (b[1] > y):
            cross = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < cross:
                inside = not inside
    return inside


def polygon_geometry(parts):
    # Shapefile outer rings are clockwise; GeoJSON convention reverses them.
    # Associate each interior ring with its smallest enclosing exterior ring.
    outer = [[ring] for ring in parts if signed_area(ring) < 0 and overlap(bounds(ring))]
    holes = [ring for ring in parts if signed_area(ring) > 0 and overlap(bounds(ring))]
    for hole in holes:
        candidates = [poly for poly in outer if contains(poly[0], hole[0])]
        if not candidates:
            raise ValueError("Polygon interior ring has no enclosing exterior")
        min(candidates, key=lambda poly: abs(signed_area(poly[0]))).append(hole)
    if not outer:
        return None
    coordinates = [[list(reversed(ring)) for ring in polygon] for polygon in outer]
    if len(coordinates) == 1:
        return {"type": "Polygon", "coordinates": coordinates[0]}
    return {"type": "MultiPolygon", "coordinates": coordinates}


def dbf_rows(data):
    count = struct.unpack_from("<I", data, 4)[0]
    header_length, record_length = struct.unpack_from("<HH", data, 8)
    fields = []
    for pos in range(32, header_length - 1, 32):
        block = data[pos:pos + 32]
        if block[0] == 13:
            break
        name = block[:11].split(b"\0")[0].decode("ascii").lower()
        fields.append((name, chr(block[11]), block[16]))
    rows = []
    for number in range(count):
        start = header_length + number * record_length
        record = data[start:start + record_length]
        if len(record) != record_length:
            raise ValueError("Truncated DBF record")
        if record[:1] == b"*":
            rows.append(None)
            continue
        row, cursor = {}, 1
        for name, field_type, length in fields:
            token = record[cursor:cursor + length].decode("utf-8").strip(" \t\r\n\0")
            cursor += length
            if field_type in ("N", "F"):
                try:
                    value = float(token)
                    value = int(value) if value.is_integer() else value
                except ValueError:
                    value = None
            else:
                value = token or None
            row[name] = value
        rows.append(row)
    return rows


def shape_geometries(data):
    if struct.unpack_from(">I", data, 0)[0] != 9994:
        raise ValueError("Invalid shapefile header")
    declared_bytes = struct.unpack_from(">I", data, 24)[0] * 2
    if declared_bytes != len(data):
        raise ValueError("Shapefile length mismatch")
    position = 100
    while position < len(data):
        _, words = struct.unpack_from(">II", data, position)
        record = data[position + 8:position + 8 + words * 2]
        position += 8 + words * 2
        kind = struct.unpack_from("<I", record)[0]
        if kind == 0:
            yield None
        elif kind == 1:
            x, y = struct.unpack_from("<dd", record, 4)
            yield {"type": "Point", "coordinates": [x, y]} if BBOX[0] <= x <= BBOX[2] and BBOX[1] <= y <= BBOX[3] else None
        elif kind in (3, 5):
            record_bbox = struct.unpack_from("<4d", record, 4)
            if not overlap(record_bbox):
                yield None
                continue
            part_count, point_count = struct.unpack_from("<II", record, 36)
            indices = list(struct.unpack_from("<" + "I" * part_count, record, 44)) + [point_count]
            offset = 44 + part_count * 4
            points = [list(struct.unpack_from("<dd", record, offset + i * 16)) for i in range(point_count)]
            parts = [points[a:b] for a, b in zip(indices, indices[1:])]
            if kind == 3:
                parts = [part for part in parts if len(part) >= 2 and overlap(bounds(part))]
                yield {"type": "MultiLineString", "coordinates": parts} if parts else None
            else:
                if any(len(ring) < 4 or ring[0] != ring[-1] for ring in parts):
                    raise ValueError("Invalid polygon ring")
                yield polygon_geometry(parts)
        else:
            raise ValueError("Unexpected source shape type: " + str(kind))


def build(source_directory):
    features, sources, summary = [], [], []
    for filename, layer in SOURCE_FILES:
        data = (source_directory / filename).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != EXPECTED_SHA256[filename]:
            raise ValueError("Unreviewed source archive: " + filename)
        with zipfile.ZipFile(source_directory / filename) as archive:
            if archive.testzip() is not None:
                raise ValueError("Failed ZIP CRC validation")
            names = archive.namelist()
            def member(suffix):
                matches = [name for name in names if name.endswith(suffix)]
                if len(matches) != 1:
                    raise ValueError("Expected one member ending " + suffix)
                return archive.read(matches[0])
            projection = member(".prj").decode("ascii")
            if 'DATUM["D_WGS_1984"' not in projection or 'UNIT["Degree"' not in projection:
                raise ValueError("Unexpected source CRS")
            if member(".cpg").decode("ascii").strip().upper() != "UTF-8":
                raise ValueError("Unexpected source text encoding")
            version = member(".VERSION.txt").decode("utf-8").strip()
            records = dbf_rows(member(".dbf"))
            geometries = list(shape_geometries(member(".shp")))
        if len(records) != len(geometries):
            raise ValueError("Shapefile and attribute record counts differ")
        selected = 0
        for index, (attributes, geometry) in enumerate(zip(records, geometries), 1):
            if attributes is None or geometry is None:
                continue
            properties = {
                "layer": layer,
                "name": attributes.get("name_en") or attributes.get("name") or "",
                "scalerank": attributes.get("scalerank"),
                "source": filename.removesuffix(".zip"),
                "source_record": index,
            }
            for key in ("featurecla", "min_zoom", "labelrank", "type", "adm0name", "adm1name", "sov_a3"):
                if attributes.get(key) is not None:
                    properties[key] = attributes[key]
            features.append({"type": "Feature", "properties": properties, "geometry": geometry})
            selected += 1
        category = "physical" if layer == "lakes" else "cultural"
        sources.append({"filename": filename, "version": version, "sha256": digest,
                        "source_url": f"https://naturalearth.s3.amazonaws.com/10m_{category}/{filename}"})
        summary.append({"file": filename, "source_records": len(records), "selected_features": selected})
    counts = dict(Counter(feature["properties"]["layer"] for feature in features))
    if any(counts.get(layer, 0) == 0 for layer in ("land", "lakes", "roads", "places")):
        raise ValueError("One or more expected regional layers are empty")
    metadata = {
        "name": "Natural Earth",
        "scale": "1:10,000,000",
        "nominal_scale": 10000000,
        "crs": "EPSG:4326",
        "crs_name": "WGS84 geographic longitude/latitude",
        "source_url": "https://www.naturalearthdata.com/",
        "license": "Public domain",
        "license_url": "https://www.naturalearthdata.com/about/terms-of-use/",
        "attribution": "Made with Natural Earth",
        "layers": list(counts),
        "feature_counts": counts,
        "bounds": list(BBOX),
        "processing": "Complete source archives processed locally. Fixed Australia bbox [112,-44,154,-10]; points selected inside bbox, line parts and polygon exterior rings selected by bbox intersection, with interior rings retained. Coordinates are not simplified or clipped; render within the stated viewport bounds.",
        "scale_note": "Generalised regional cartography, not a ten-metre dataset. Not suitable for site navigation, precise distances or hundred-metre terrain detail.",
        "position_note": "Any GDA2020 borehole overlay belongs to the application, not this public basemap. Approximate regional areas rounded to 0.1 degrees are contextual only; no precision datum conversion is implied.",
        "sources": sources,
        "source_selection_counts": summary,
    }
    return {"type": "FeatureCollection", "metadata": metadata, "features": features}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, default=Path("basemap.json"))
    args = parser.parse_args()
    document = build(args.sources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    args.output.write_bytes(payload)
    print(json.dumps({"output": args.output.name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                      "features": document["metadata"]["feature_counts"], "source_counts": document["metadata"]["source_selection_counts"]}, indent=2))


if __name__ == "__main__":
    main()
