"""Serve verified mineral-change results and calculate missing holes in the background.

Author: Ding Qing
Date: 2026-10-15
"""

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import uuid

from analysis_overlay import COMPOSITION_COLUMNS


ROOT = Path(__file__).resolve().parent
DEFAULT_ANALYSIS = ROOT / "analysis" if (ROOT / "analysis").is_dir() else ROOT.parent / "analysis"
DEFAULT_CACHE = ROOT / "work" / "change-viewer"
HOLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_HOLES = 6
MAX_RESULT_BYTES = 20 * 1024 * 1024
ASSETS = {"index.html": "text/html; charset=utf-8", "viewer.css": "text/css; charset=utf-8",
          "viewer.js": "text/javascript; charset=utf-8", "viewer-data.js": "text/javascript; charset=utf-8"}
SETTINGS = {f"{beta}-{minimum}" for beta in (1, 2, 4, 8) for minimum in (2, 3, 5)}


class BusyError(ValueError):
    pass


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_result(path, hole_id):
    """Parse the generated assignment as JSON, without evaluating JavaScript."""
    path = Path(path)
    if path.stat().st_size > MAX_RESULT_BYTES:
        raise ValueError("Analysis result is too large.")
    text = path.read_text(encoding="utf-8")
    prefix = "window.HOLE_DATA=window.HOLE_DATA||{};window.HOLE_DATA[" + json.dumps(hole_id) + "]="
    if not text.startswith(prefix) or not text.rstrip().endswith(";"):
        raise ValueError("Unrecognised analysis result.")
    data = json.loads(text[len(prefix):].rstrip()[:-1],
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite result.")))
    if (not isinstance(data, dict) or data.get("hole") != hole_id or not SHA256.fullmatch(data.get("sha256", ""))
            or set(data.get("settings", {})) != SETTINGS or data.get("default") != "2-2"):
        raise ValueError("Incomplete analysis result.")
    def finite(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if (not finite(data.get("from")) or not finite(data.get("to")) or data["to"] <= data["from"]
            or not isinstance(data.get("metres"), list) or not data["metres"]
            or any(not finite(d) for d in data["metres"])
            or any(not isinstance(candidates, list) or any(not isinstance(c, dict) or not finite(c.get("depth")) for c in candidates)
                   for candidates in data["settings"].values())):
        raise ValueError("Invalid analysis depth values.")
    return data


def result_bytes(data):
    return ("window.HOLE_DATA=window.HOLE_DATA||{};window.HOLE_DATA[" + json.dumps(data["hole"])
            + "]=" + json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + ";\n").encode()


class ChangeViewer:
    def __init__(self, catalog_getter, data_root=None, analysis_root=None, cache_root=None, runner=None):
        self.catalog_getter = catalog_getter
        self.data_root = Path(data_root).resolve() if data_root is not None else None
        self.analysis_root = Path(analysis_root or DEFAULT_ANALYSIS).resolve()
        self.cache_root = Path(cache_root or DEFAULT_CACHE).resolve()
        self.runner = runner or self._calculate
        self.lock = threading.Lock()
        self.job = None
        self.errors = {}
        self._documents = {}
        self._database_file = None
        self._database_checked = False
        self._database_hash = None
        self.method_sha = self._method_sha()
        self.compute_available = runner is not None or importlib.util.find_spec("numpy") is not None

    def _method_sha(self):
        parts = ("build_viewer.py", "hylogger_pipeline/boundaries.py", "hylogger_pipeline/summary_csv.py")
        try:
            content = b"change-viewer-cache/1\0" + b"\0".join((self.analysis_root / p).read_bytes() for p in parts)
            return hashlib.sha256(content).hexdigest()
        except OSError:
            return None

    def _sources(self):
        catalog = self.catalog_getter()
        known = {h["hole_id"] for h in catalog.get("holes", [])}
        sources = {}
        for source in catalog.get("manifest", {}).get("sources", []):
            hid = source.get("hole_id", "")
            if hid in known and HOLE_ID.fullmatch(hid):
                if hid in sources and sources[hid] != source:
                    sources[hid] = None
                else:
                    sources[hid] = source
        return catalog, sources

    def _source_path(self, source):
        if self.data_root is None or not source.get("relative_path"):
            return None
        path = self.data_root / source["relative_path"]
        if not path.resolve().is_relative_to(self.data_root) or path.is_symlink() or not path.is_file():
            return None
        return path

    def _cache_path(self, hole_id, digest):
        key = hashlib.sha256(f"{hole_id}:{digest}:{self.method_sha}".encode()).hexdigest()[:40]
        return self.cache_root / f"{key}.js"

    def _database(self):
        if not self._database_checked:
            if self.data_root:
                self._database_file = next((p for p in sorted(self.data_root.rglob("HyLogger_Dataset_Package.sqlite"))
                                            if not p.is_symlink() and p.resolve().is_relative_to(self.data_root)), None)
            self._database_checked = True
        path = self._database_file
        if path is None:
            return None, None
        try:
            info = path.stat()
            stamp = (info.st_mtime_ns, info.st_size)
            if not self._database_hash or self._database_hash[0] != stamp:
                self._database_hash = (stamp, digest_file(path))
            return path, self._database_hash[1]
        except OSError:
            return None, None

    def _read(self, path, hole_id):
        try:
            info = path.stat()
            key = (str(path), info.st_mtime_ns, info.st_size)
            if key not in self._documents:
                self._documents[key] = read_result(path, hole_id)
            return self._documents[key]
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def _result(self, hole_id, digest):
        paths = []
        if self.method_sha:
            paths.append((self._cache_path(hole_id, digest), "local cache"))
        paths.append((self.analysis_root / "viewer" / "data" / f"{hole_id}.js", "provided analysis"))
        for path, origin in paths:
            data = self._read(path, hole_id)
            if data and data["sha256"] == digest:
                if origin == "local cache" and data.get("calculation", {}).get("method_sha256") != self.method_sha:
                    continue
                data = dict(data)
                if origin == "provided analysis":
                    data["reference_note"] = "Company-log lines supplied with the analysis package; reference database identity was not verified by this viewer."
                elif data.get("log") is not None:
                    _, reference_sha = self._database()
                    if (data.get("reference_source") or {}).get("sha256") != reference_sha or reference_sha is None:
                        data["log"] = None
                        data["reference_note"] = "Saved company-log lines are unavailable because their reference database is missing or changed."
                    else:
                        data["reference_note"] = "Company-log lines match the recorded local database checksum."
                return data, origin
        return None, None

    def _status(self, catalog, hole_id, source):
        row = {"hole_id": hole_id, "status": "unsupported", "can_compute": False, "reason": "Source version is ambiguous."}
        if source is None or not SHA256.fullmatch(source.get("sha256", "")):
            return row
        digest = source["sha256"]
        row["source_sha256"] = digest
        path = self._source_path(source)
        if path is None:
            row["reason"] = "The loaded source file is unavailable; refresh the data library."
            return row
        try:
            current = digest_file(path)
        except OSError:
            current = None
        if current != digest:
            row.update(status="stale", reason="The CSV changed after the library was loaded. Refresh library before computing.")
            return row
        data, origin = self._result(hole_id, digest)
        if data is not None:
            row.update(status="ready", reason="Result matches the loaded CSV.", computed_from=origin,
                       depth_from_m=data["from"], depth_to_m=data["to"],
                       candidate_count=len(data["settings"]["2-2"]), has_company_log=data.get("log") is not None)
            return row
        expected = set(COMPOSITION_COLUMNS)
        fields = source.get("fields", [])
        group_fields = {f for f in fields if re.fullmatch(r".+_\((System|User|Domained)_(SWIR|TIR|MIR)\)", f)
                        and f.split("_(", 1)[0].lower() != "invalid"}
        records = [r for r in catalog.get("records", []) if r["hole_id"] == hole_id]
        if group_fields != expected:
            row["reason"] = "This calculation requires the 36 System SWIR/TIR mineral-group columns."
            return row
        if not records or any(abs(r["to_m"] - r["from_m"] - 1) > 1e-6 for r in records):
            row["reason"] = "This calculation supports one-metre summary records."
            return row
        if not self.method_sha:
            row["reason"] = "The calculation module is not installed."
            return row
        if not self.compute_available:
            row["reason"] = "Calculation needs NumPy installed in the Python environment running this application. Saved results remain available."
            return row
        packaged = self._read(self.analysis_root / "viewer" / "data" / f"{hole_id}.js", hole_id)
        row.update(status="stale" if packaged else "missing", can_compute=True,
                   reason="A new result is needed for this CSV version." if packaged else "No saved result yet.")
        key = (hole_id, digest)
        with self.lock:
            error = self.errors.get(key)
            job = self.job
            if job and job["status"] == "running" and hole_id in job["pending"]:
                row.update(status="running", can_compute=False, reason="Calculating this hole." if job["current_hole"] == hole_id else "Queued for calculation.")
            elif error:
                row.update(status="error", reason=error)
        return row

    def snapshot(self):
        catalog, sources = self._sources()
        holes = [self._status(catalog, hid, source) for hid, source in sorted(sources.items())]
        with self.lock:
            job = {k: v for k, v in self.job.items() if k != "pending"} if self.job else None
        return {"holes": holes, "job": job, "max_holes": MAX_HOLES,
                "defaults": {"beta": 2, "min_m": 2}, "viewer_url": "/change-viewer/index.html",
                "note": "Full-hole calculation; the displayed depth range selects a view of saved results."}

    def start(self, payload):
        if set(payload) != {"hole_ids"} or not isinstance(payload["hole_ids"], list):
            raise ValueError("Provide a hole_ids list.")
        requested = payload["hole_ids"]
        if not 1 <= len(requested) <= MAX_HOLES or any(not isinstance(h, str) for h in requested) or len(set(requested)) != len(requested):
            raise ValueError("Select one to six distinct holes.")
        catalog, sources = self._sources()
        if any(hid not in sources for hid in requested):
            raise ValueError("Unknown hole_id.")
        entries = [(hid, sources[hid], self._status(catalog, hid, sources[hid])) for hid in requested]
        if any(row["status"] != "ready" and not row["can_compute"] and row["status"] != "running" for _, _, row in entries):
            raise ValueError("One or more selected sources cannot be calculated. Refresh the library or inspect their status.")
        pending = [(hid, dict(source)) for hid, source, row in entries if row["status"] != "ready"]
        with self.lock:
            if self.job and self.job["status"] == "running":
                raise BusyError("A calculation is already running. Its saved results will appear when ready.")
            if pending:
                self.job = {"id": uuid.uuid4().hex, "status": "running", "total": len(pending), "completed": 0,
                            "failed": 0, "current_hole": None, "hole_ids": [h for h, _ in pending],
                            "pending": [h for h, _ in pending]}
                for hid, source in pending:
                    self.errors.pop((hid, source["sha256"]), None)
        if pending:
            threading.Thread(target=self._run, args=(pending,), daemon=True, name="mineral-change-worker").start()
        return self.snapshot()

    def _run(self, entries):
        for hole_id, source in entries:
            with self.lock:
                self.job["current_hole"] = hole_id
            try:
                self.cache_root.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="build-", dir=self.cache_root) as folder:
                    out = Path(folder)
                    (out / "data").mkdir()
                    source_path = self._source_path(source)
                    if source_path is None or digest_file(source_path) != source["sha256"]:
                        raise ValueError("Source changed. Refresh library and calculate again.")
                    self.runner(source_path, out)
                    result = read_result(out / "data" / f"{hole_id}.js", hole_id)
                    _, current_sources = self._sources()
                    current = current_sources.get(hole_id)
                    if (result["sha256"] != source["sha256"] or not current or current["sha256"] != source["sha256"]
                            or digest_file(source_path) != source["sha256"]):
                        raise ValueError("Source changed during calculation. Refresh library and calculate again.")
                    result["validation"] = None
                    result["calculation"] = {"method_sha256": self.method_sha,
                                             "computed_at": datetime.now(timezone.utc).isoformat(),
                                             "source_sha256": source["sha256"], "scope": "full hole"}
                    target = self._cache_path(hole_id, source["sha256"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(".tmp")
                    temporary.write_bytes(result_bytes(result))
                    temporary.replace(target)
            except Exception as error:
                import traceback
                traceback.print_exc()
                message = str(error) if isinstance(error, ValueError) else "Calculation failed. Check the calculation dependencies and try again."
                with self.lock:
                    self.errors[(hole_id, source["sha256"])] = message
                    self.job["failed"] += 1
            finally:
                with self.lock:
                    self.job["completed"] += 1
                    self.job["pending"].remove(hole_id)
        with self.lock:
            self.job["status"] = "complete" if not self.job["failed"] else "complete_with_errors"
            self.job["current_hole"] = None

    def _calculate(self, source_path, out):
        database, reference_sha = self._database()
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(self.analysis_root),
                   str(source_path), str(out), str(database) if database else ""]
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=300,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise ValueError("Calculation exceeded five minutes for this hole. No partial result was saved.") from None
        if process.returncode:
            log = out / "calculation-error.txt"
            log.write_text(process.stderr or process.stdout, encoding="utf-8")
            if "No module named 'numpy'" in process.stderr:
                raise ValueError("Calculation needs NumPy installed in the Python environment running this application.")
            raise ValueError("Calculation could not read this summary. Check its mineral-group columns and one-metre intervals.")
        outputs = list((out / "data").glob("*.js"))
        if len(outputs) != 1:
            raise ValueError("Calculation did not produce one complete result.")
        data = read_result(outputs[0], outputs[0].stem)
        _, current_reference_sha = self._database()
        if current_reference_sha != reference_sha:
            data["log"] = None
        data["reference_source"] = {"filename": database.name, "sha256": reference_sha} if database else None
        outputs[0].write_bytes(result_bytes(data))

    def asset(self, relative):
        if relative == "":
            relative = "index.html"
        if relative in ASSETS:
            try:
                return (self.analysis_root / "viewer" / relative).read_bytes(), ASSETS[relative]
            except OSError:
                return None
        if relative == "data/index.js":
            ready = [row["hole_id"] for row in self.snapshot()["holes"] if row["status"] == "ready"]
            return ("window.HOLE_INDEX=" + json.dumps(ready) + ";\n").encode(), "text/javascript; charset=utf-8"
        match = re.fullmatch(r"data/([A-Za-z0-9][A-Za-z0-9_-]{0,99})\.js", relative)
        if not match:
            return None
        hole_id = match[1]
        catalog, sources = self._sources()
        if hole_id not in sources or self._status(catalog, hole_id, sources[hole_id])["status"] != "ready":
            return None
        data, _ = self._result(hole_id, sources[hole_id]["sha256"])
        return result_bytes(data), "text/javascript; charset=utf-8"


def worker(analysis_root, source_path, out, database):
    """Invoke the per-hole builder in an isolated Python process."""
    analysis_root, source_path, out = Path(analysis_root), Path(source_path), Path(out)
    spec = importlib.util.spec_from_file_location("mineral_change_builder", analysis_root / "build_viewer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = module.read_summary_csv(source_path)
    groups = {m["id"] for m in source["registry"] if m["kind"] == "mineral_group_proportion"}
    if (groups != set(COMPOSITION_COLUMNS) or not source["import_review"]["queryable"]
            or any(abs(float(length) - 1) > 1e-6 for length in source["record_lengths_m"])):
        raise ValueError("Expected a supported one-metre summary with 36 mineral groups.")
    if not HOLE_ID.fullmatch(source["hole_id"]):
        raise ValueError("Unsupported hole identifier.")
    hole_id, note = module.build(source_path, Path(database) if database else None, source_path.parent, out, {})
    if note.startswith("skipped"):
        raise ValueError("Summary was not accepted for analysis.")
    print(hole_id, note)


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "--worker":
    worker(*sys.argv[2:])
