"""Link local tray photographs to the depths recorded in their TSG package.

Author: Ding Qing
Date: 2026-10-15
"""

import hashlib
import math
from pathlib import Path
import re


SAMPLE = re.compile(r"\bT=(\d+) L=(\d+) P=\d+ D=([^\s]+) X=[^\s]+ H=([^\s]+)")
HOLE_NAME = re.compile(r"[A-Za-z0-9_-]+\Z")


def safe_file(path, root):
    return path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def scan_ranges(path, hole):
    """Return observed sample extents per tray row, without filling depth gaps."""
    trays = {}
    with path.open(encoding="latin-1") as stream:
        for line in stream:
            match = SAMPLE.search(line)
            if not match:
                continue
            tray, row, depth, source_hole = match.groups()
            tray, row, depth = int(tray), int(row), float(depth)
            if source_hole != hole or tray < 1 or row < 1 or not math.isfinite(depth) or depth < 0:
                raise ValueError("Invalid TSG sample identity or depth")
            record = trays.setdefault(tray, {}).setdefault(row, {"row": row, "from_m": depth, "to_m": depth, "scan_count": 0})
            record["from_m"] = min(record["from_m"], depth)
            record["to_m"] = max(record["to_m"], depth)
            record["scan_count"] += 1
    return trays


def jpeg_tray(path):
    """Read the TSG tray identifier and row count from the JPEG COM segment."""
    with path.open("rb") as stream:
        if stream.read(2) != b"\xff\xd8":
            raise ValueError("Not a JPEG")
        for _ in range(256):
            marker = stream.read(2)
            if len(marker) != 2 or marker[0] != 255 or marker in (b"\xff\xda", b"\xff\xd9"):
                break
            length_bytes = stream.read(2)
            if len(length_bytes) != 2:
                break
            length = int.from_bytes(length_bytes, "big") - 2
            if length < 0:
                break
            content = stream.read(length)
            if len(content) != length:
                break
            if marker == b"\xff\xfe" and content.startswith(b"IOL34_JID1,"):
                fields = content.rstrip(b"\x00").decode("ascii").split(",")
                tray, rows = int(fields[1]), int(fields[2])
                if tray < 1 or not 1 <= rows <= 100:
                    raise ValueError("Invalid JPEG tray metadata")
                return tray, rows
    raise ValueError("No supported JPEG tray metadata")


def index_photos(data_root, holes):
    root = Path(data_root).resolve()
    photos, files, issues = [], {}, []
    for hole in sorted(holes):
        if not HOLE_NAME.fullmatch(hole):
            continue
        folder = root / "nvcl_wa" / hole / "extracted"
        headers = [path for path in folder.glob(f"*/{hole}_tsg.tsg") if safe_file(path, root)]
        if not headers:
            continue
        if len(headers) != 1:
            issues.append({"hole_id": hole, "detail": "Multiple core packages; photo version not selected."})
            continue
        header = headers[0]
        try:
            ranges = scan_ranges(header, hole)
            header_hash = digest(header)
        except (OSError, ValueError) as error:
            issues.append({"hole_id": hole, "detail": f"Cannot index tray depths: {type(error).__name__}."})
            continue
        for tray, rows in sorted(ranges.items()):
            photo = header.parent / f"{hole}_{tray:04d}.jpg"
            if not safe_file(photo, root):
                continue
            try:
                photo_tray, row_count = jpeg_tray(photo)
                if photo_tray != tray or max(rows) > row_count:
                    raise ValueError("JPEG and TSG tray metadata disagree")
                photo_hash = digest(photo)
                spans = sorted(rows.values(), key=lambda item: item["row"])
                photos.append({
                    "photo_id": photo_hash, "hole_id": hole, "tray_number": tray,
                    "url": f"/core-images/{photo_hash}.jpg", "filename": photo.name,
                    "depth_from_m": min(row["from_m"] for row in spans),
                    "depth_to_m": max(row["to_m"] for row in spans), "rows": spans,
                    "scan_count": sum(row["scan_count"] for row in spans),
                    "jpeg_rows": row_count, "sha256": photo_hash,
                    "depth_source": "TSG sample headers: hole H, tray T, row L and along-hole depth D",
                    "depth_filename": header.name, "depth_sha256": header_hash,
                    "source": "Local WA NVCL core package",
                })
                files[photo_hash] = photo.relative_to(root).as_posix()
            except (OSError, ValueError, IndexError, UnicodeError):
                issues.append({"hole_id": hole, "filename": photo.name,
                               "detail": "Photo excluded: JPEG and TSG tray metadata could not be matched."})
    return photos, files, issues


def read_photo(data_root, catalog, photo_id):
    relative = catalog.get("core_image_files", {}).get(photo_id)
    if relative is None:
        return None
    root = Path(data_root).resolve()
    path = root / relative
    try:
        if not safe_file(path, root):
            return None
        data = path.read_bytes()
        return data if hashlib.sha256(data).hexdigest() == photo_id else None
    except OSError:
        return None
