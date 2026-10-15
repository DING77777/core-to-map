"""Serve the local HyLogger workspace and query API.

Author: Ding Qing
Date: 2026-10-15
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import analysis_overlay
import core_photos
import comparison
import change_viewer
import depth_ranges
import engine
import library

ROOT = Path(__file__).resolve().parent
MAX_BODY = 2 * 1024 * 1024
APP_ID = "hylogger-interval-explorer"
LAUNCH_PROTOCOL = 1


def application_identity(data_root):
    """Identify this installation and data location without exposing local paths."""
    def path_id(path):
        normalized = os.path.normcase(str(Path(path).resolve()))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return {"app_id": APP_ID, "launch_protocol": LAUNCH_PROTOCOL,
            "instance_id": path_id(ROOT), "data_root_id": path_id(data_root)}


def strict_json(data):
    return json.loads(data, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid JSON number: {value}")))


def load_app_catalog(data_root):
    return library.load_library(Path(data_root))


def catalog_payload(catalog):
    return {
        "holes": catalog["holes"],
        "depth_ranges": depth_ranges.summarize(catalog),
        "metric": catalog["metric_registry"][engine.METRIC_ID],
        "metrics": list(catalog["metric_registry"].values()),
        "default_query": catalog.get("default_query", engine.DEFAULT_QUERY),
        "groups": catalog.get("groups", engine.HOLE_GROUPS),
        "versions": catalog["versions"],
        "audit": catalog["audit"],
        "manifest": catalog["manifest"],
        "library": catalog.get("library", {}),
        "core_images": catalog.get("core_images", []),
        "core_image_issues": catalog.get("core_image_issues", []),
        "notes": [
            "Source one-metre summaries. N.A. means not detected or below threshold.",
            "Feature wavelengths, absorption depths and mineral proportions are distinct measures.",
            "Along-hole depth does not align geological layers between holes.",
        ],
    }


def query_payload(result):
    """Send plotted values and evidence without repeating all source columns."""
    payload = dict(result)
    for field in ("records", "evidence"):
        payload[field] = [{key: value for key, value in row.items() if key != "raw_row"}
                          for row in result[field]]
    payload["profiles"] = [{"metric": profile["metric"],
                            "records": [{key: value for key, value in row.items() if key != "raw_row"}
                                        for row in profile["records"]]}
                           for profile in result["profiles"]]
    return payload


def create_server(catalog, host="127.0.0.1", port=8050, identity=None, data_root=None, analysis_root=None,
                  change_viewer_root=None, change_viewer_cache=None):
    if host != "127.0.0.1":
        raise ValueError("This local prototype binds only to 127.0.0.1.")
    health_identity = dict(identity or {"app_id": APP_ID, "launch_protocol": LAUNCH_PROTOCOL})
    state = {"catalog": catalog}
    refresh_lock = threading.Lock()
    viewer = change_viewer.ChangeViewer(lambda: state["catalog"], data_root, change_viewer_root, change_viewer_cache)

    class Handler(BaseHTTPRequestHandler):
        server_version = "HyLoggerLocal/2.0"

        def send(self, status, data, content_type="application/json; charset=utf-8", download=None, frame_ancestors="'none'"):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' https://public-services.slip.wa.gov.au; object-src 'none'; base-uri 'none'; frame-ancestors " + frame_ancestors)
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{download}"')
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            authority = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if authority not in allowed:
                self.send(403, {"error": "Use the local application URL."})
                return False
            return True

        def do_GET(self):
            catalog = state["catalog"]
            if not self.valid_host():
                return
            path = urlparse(self.path).path
            if path == "/health":
                return self.send(200, {"status": "ok", "engine_version": catalog["versions"]["engine_version"],
                                       "pid": os.getpid(), **health_identity})
            if path == "/api/catalog":
                return self.send(200, catalog_payload(catalog))
            if path == "/api/change-viewer":
                return self.send(200, viewer.snapshot())
            if path.startswith("/change-viewer/"):
                asset = viewer.asset(path.removeprefix("/change-viewer/"))
                if asset is None:
                    return self.send(404, {"error": "Verified analysis asset is unavailable."})
                return self.send(200, asset[0], asset[1], frame_ancestors="'self'")
            if path == "/api/analysis":
                params = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                if set(params) != {"hole_id"} or len(params["hole_id"]) != 1:
                    return self.send(400, {"error": "Provide one hole_id."})
                hole_id = params["hole_id"][0]
                if hole_id not in {hole["hole_id"] for hole in catalog["holes"]}:
                    return self.send(400, {"error": "Unknown hole_id."})
                overlay = analysis_overlay.load_hole_overlay(catalog, hole_id, analysis_root)
                return self.send(200, overlay)
            if path.startswith("/core-images/") and path.endswith(".jpg") and data_root is not None:
                photo_id = path.removeprefix("/core-images/").removesuffix(".jpg")
                photo = core_photos.read_photo(data_root, catalog, photo_id)
                if photo is not None:
                    return self.send(200, photo, "image/jpeg")
                return self.send(404, {"error": "Verified core tray photo is not present in this data library."})
            routes = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/imagery.js": ("imagery.js", "text/javascript; charset=utf-8"),
                      "/profiles.js": ("profiles.js", "text/javascript; charset=utf-8"),
                      "/profiles.css": ("profiles.css", "text/css; charset=utf-8"),
                      "/change-viewer.js": ("change-viewer.js", "text/javascript; charset=utf-8"),
                      "/change-viewer.css": ("change-viewer.css", "text/css; charset=utf-8"),
                      "/scalar-picker.js": ("scalar-picker.js", "text/javascript; charset=utf-8"),
                      "/scalar-picker.css": ("scalar-picker.css", "text/css; charset=utf-8"),
                      "/app.css": ("app.css", "text/css; charset=utf-8"),
                      "/sources.txt": ("../docs/PAGE_DATA_SOURCES.txt", "text/plain; charset=utf-8"),
                      "/qgis.txt": ("../docs/QGIS_CONNECTION.txt", "text/plain; charset=utf-8"),
                      "/qgis-landgate.xml": ("../docs/qgis_landgate_wms.xml", "application/xml; charset=utf-8"),
                      "/basemap.json": ("basemap.json", "application/geo+json; charset=utf-8")}
            if path not in routes:
                return self.send(404, {"error": "Not found"})
            filename, mime = routes[path]
            try:
                self.send(200, (ROOT / "static" / filename).read_bytes(), mime)
            except FileNotFoundError:
                self.send(503, {"error": "Application assets are unavailable."})

        def do_POST(self):
            catalog = state["catalog"]
            if not self.valid_host():
                return
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                return self.send(403, {"error": "Cross-origin requests are not accepted."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self.send(413, {"error": "JSON payload must be between 1 byte and 2 MB."})
                # Unread request bytes can reset a Windows HTTP connection.
                raw = self.rfile.read(length)
                if self.headers.get_content_type() != "application/json":
                    return self.send(415, {"error": "Send application/json."})
                payload = strict_json(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object.")
                path = urlparse(self.path).path
                if path == "/api/change-viewer/compute":
                    try:
                        return self.send(202, viewer.start(payload))
                    except change_viewer.BusyError as error:
                        return self.send(409, {"error": str(error)})
                if path == "/api/library/refresh":
                    if payload or data_root is None:
                        raise ValueError("Refresh requires an empty object and a configured data library.")
                    with refresh_lock:
                        replacement = load_app_catalog(data_root)
                        state["catalog"] = replacement
                    return self.send(200, catalog_payload(replacement))
                if path == "/api/query":
                    return self.send(200, query_payload(engine.run_query(catalog, payload)))
                if path == "/api/availability":
                    return self.send(200, comparison.availability(catalog, payload))
                if path == "/api/restore":
                    return self.send(200, query_payload(engine.restore_query(catalog, payload)))
                if path == "/api/export":
                    result = engine.restore_query(catalog, payload)
                    return self.send(200, engine.make_export(catalog, result), "application/zip", f"hylogger-{result['query_id'][:12]}.zip")
                self.send(404, {"error": "Not found"})
            except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
                self.send(400, {"error": str(error)})
            except Exception:
                self.send(500, {"error": "Unexpected application error. See the server terminal."})
                import traceback
                traceback.print_exc()

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    local_data = ROOT / "data"
    default_data = local_data if local_data.is_dir() else ROOT.parent / "data"
    parser.add_argument("--data-root", type=Path, default=Path(os.environ.get("HYLOGGER_DATA_ROOT", default_data)))
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    parser.add_argument("--port", type=int, default=8051)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--analysis-root", type=Path, help="Optional local directory containing per-hole candidate analysis packages")
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "work")
    args = parser.parse_args()
    try:
        catalog = load_app_catalog(args.data_root)
        args.work_dir.mkdir(parents=True, exist_ok=True)
        for filename, obj in (("data_audit.json", catalog["audit"]), ("data_manifest.json", catalog["manifest"]), ("versions.json", catalog["versions"])):
            (args.work_dir / filename).write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        if args.audit_only:
            print(json.dumps({"versions": catalog["versions"], "audit": catalog["audit"]}, ensure_ascii=False))
            return
        server = create_server(catalog, args.host, args.port, identity=application_identity(args.data_root), data_root=args.data_root,
                               analysis_root=args.analysis_root)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Cannot start HyLogger: {error}\n")
    print(f"HyLogger Interval Explorer: http://127.0.0.1:{server.server_port}", flush=True)
    print("Local only. Stop with Ctrl+C. Source files are read-only.", flush=True)
    if args.open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(f"http://127.0.0.1:{server.server_port}/")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
