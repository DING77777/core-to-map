"""Download the recorded public sources; verify bytes before adding to the library.

Author: Ding Qing
Date: 2026-10-15
"""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.parse import urlparse
import urllib.request
import zipfile

import coords


ROOT = Path(__file__).resolve().parent
HOSTS = {"dasc.dmirs.wa.gov.au", "warsydprdstadasc.blob.core.windows.net"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_path(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Download destination escapes the data library")
    return target


def fetch(url, target, expected_hash, max_bytes):
    if target.is_file():
        if digest(target) != expected_hash:
            raise ValueError(f"Existing file differs from the recorded version: {target.name}. Move it aside for review.")
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS:
        raise ValueError("Download URL is not an approved official source")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "HyLogger-Interval-Explorer/2.1"})
        with urllib.request.urlopen(request, timeout=60) as response:
            final = urlparse(response.url)
            if final.scheme != "https" or final.hostname not in HOSTS:
                raise ValueError("Unexpected download redirect")
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".download-", delete=False) as stream:
                temporary = Path(stream.name)
                count = 0
                while block := response.read(1024 * 1024):
                    count += len(block)
                    if count > max_bytes:
                        raise ValueError("Download exceeds expected size limit")
                    stream.write(block)
        if digest(temporary) != expected_hash:
            raise ValueError(f"Downloaded source version changed: {target.name}. Nothing was imported.")
        if target.exists():
            raise ValueError("Destination was created during download; no file overwritten")
        temporary.replace(target)
        return True
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def download(data_root, demo=False, skip_collars=False):
    root = Path(data_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "inbox").mkdir(exist_ok=True)
    manifest = json.loads((ROOT / "download_manifest.json").read_text(encoding="utf-8"))
    chosen = manifest["summaries"]
    if demo:
        chosen = [item for item in chosen if item["hole_id"] in {"TBDD126", "TBDD127", "TBDD128"}]
    failures = []
    for item in chosen:
        try:
            changed = fetch(item["url"], safe_path(root, item["relative_path"]), item["sha256"], 20 * 1024 * 1024)
            print(("Downloaded " if changed else "Verified   ") + item["hole_id"], flush=True)
        except (OSError, ValueError) as error:
            failures.append(f"{item['hole_id']}: {error}")
            print(f"Unable to fetch {item['hole_id']}: {error}", flush=True)
    if not skip_collars:
        collar = manifest["collars"]
        files_present = (root / coords.DATABASE_PATH).is_file() and (root / coords.METADATA_PATH).is_file()
        trusted = files_present and (digest(root / coords.DATABASE_PATH), digest(root / coords.METADATA_PATH)) in coords.TRUSTED_RELEASES
        if not trusted:
            print("Downloading the official collar package (about 86 MB)...", flush=True)
            archive = root / "downloads" / collar["archive_name"]
            try:
                fetch(collar["url"], archive, collar["sha256"], 256 * 1024 * 1024)
                with zipfile.ZipFile(archive) as source:
                    for member in collar["members"]:
                        target = safe_path(root, collar["destination"] + "/" + member)
                        expected = source.read(member)
                        if target.exists() and target.read_bytes() != expected:
                            raise ValueError(f"Existing collar package member differs: {target.name}")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not target.exists():
                            target.write_bytes(expected)
                print("Verified collar package extracted with its metadata and licence.", flush=True)
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                failures.append(f"Collar package: {error}")
                print(f"Map locations unavailable: {error}. Depth profiles can still work.", flush=True)
    receipt = {"summaries_requested": len(chosen), "failures": failures, "manifest": "download_manifest.json"}
    (root / "download_receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--demo", action="store_true", help="Only fetch the three TBDD demonstration summaries")
    parser.add_argument("--skip-collars", action="store_true", help="Profiles only; do not download the large coordinate package")
    args = parser.parse_args()
    result = download(args.data_root, args.demo, args.skip_collars)
    if result["failures"]:
        parser.exit(1, "Some downloads failed. See data/download_receipt.json; retrying keeps verified files.\n")


if __name__ == "__main__":
    main()
