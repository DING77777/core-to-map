"""Photo links require matching native tray metadata and retain source identity.

Author: Ding Qing
Date: 2026-10-15
"""

import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import app
import core_photos
import engine
import library
from tests.test_library import summary


class CorePhotoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "nvcl_wa/TESTA/extracted/package"
        self.folder.mkdir(parents=True)
        self.header = self.folder / "TESTA_tsg.tsg"
        self.header.write_text("0:s T=0001 L=1 P=1 D=1.2 X=2 H=TESTA\n"
                               "1:s T=0001 L=1 P=2 D=2.4 X=3 H=TESTA\n"
                               "2:s T=0001 L=2 P=1 D=3.6 X=2 H=TESTA\n")
        self.photo = self.folder / "TESTA_0001.jpg"
        self.write_photo()

    def tearDown(self):
        self.temp.cleanup()

    def write_photo(self, tray=1, rows=2):
        comment = f"IOL34_JID1,{tray:04d},{rows},1\x00".encode("ascii")
        self.photo.write_bytes(b"\xff\xd8\xff\xfe" + (len(comment) + 2).to_bytes(2, "big") + comment + b"\xff\xd9")

    def index(self):
        return core_photos.index_photos(self.root, ["TESTA"])

    def test_ranges_come_from_samples_and_keep_row_gaps(self):
        photos, files, issues = self.index()
        self.assertFalse(issues)
        photo = photos[0]
        self.assertEqual((photo["depth_from_m"], photo["depth_to_m"]), (1.2, 3.6))
        self.assertEqual([(r["from_m"], r["to_m"]) for r in photo["rows"]], [(1.2, 2.4), (3.6, 3.6)])
        self.assertEqual(photo["scan_count"], 3)
        self.assertEqual(photo["depth_sha256"], core_photos.digest(self.header))
        self.assertEqual(core_photos.read_photo(self.root, {"core_image_files": files}, photo["photo_id"]), self.photo.read_bytes())

    def test_tray_and_row_mismatches_exclude_photo(self):
        for tray, rows in [(2, 2), (1, 1)]:
            with self.subTest(tray=tray, rows=rows):
                self.write_photo(tray, rows)
                photos, _, issues = self.index()
                self.assertEqual(photos, [])
                self.assertEqual(len(issues), 1)

    def test_wrong_hole_or_nonfinite_depth_excludes_package(self):
        original = self.header.read_text()
        for bad in [original.replace("H=TESTA", "H=OTHER"), original.replace("D=1.2", "D=nan")]:
            with self.subTest(header=bad):
                self.header.write_text(bad)
                photos, _, issues = self.index()
                self.assertFalse(photos)
                self.assertTrue(issues)

    def test_missing_photo_or_metadata_has_no_fallback(self):
        self.photo.unlink()
        self.assertEqual(self.index()[0], [])
        self.photo.write_bytes(b"not an indexed photo")
        self.assertEqual(self.index()[0], [])

    def test_multiple_packages_are_not_silently_mixed(self):
        second = self.folder.parent / "another"
        second.mkdir()
        (second / self.header.name).write_text(self.header.read_text())
        self.assertEqual(self.index()[0], [])
        self.assertTrue(self.index()[2])

    def test_changed_or_unlisted_files_are_not_served(self):
        photos, files, _ = self.index()
        catalog = {"core_image_files": files}
        self.assertIsNone(core_photos.read_photo(self.root, catalog, "../TESTA_0001"))
        self.photo.write_bytes(b"replaced")
        self.assertIsNone(core_photos.read_photo(self.root, catalog, photos[0]["photo_id"]))

    def test_photo_index_does_not_change_query_identity(self):
        summary(self.root, "TESTA")
        before = library.load_library(self.root)
        self.assertEqual(len(before["core_images"]), 1)
        self.photo.unlink()
        after = library.load_library(self.root)
        self.assertEqual(after["core_images"], [])
        self.assertEqual(engine.run_query(before, before["default_query"])["query_id"],
                         engine.run_query(after, after["default_query"])["query_id"])

    def test_http_only_serves_verified_photo_ids(self):
        summary(self.root, "TESTA")
        catalog = library.load_library(self.root)
        server = app.create_server(catalog, port=0, data_root=self.root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(base + catalog["core_images"][0]["url"]) as response:
                self.assertEqual(response.read(), self.photo.read_bytes())
                self.assertEqual(response.headers.get_content_type(), "image/jpeg")
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + "/core-images/TESTA.jpg")
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    @unittest.skipUnless(os.environ.get("HYLOGGER_DATA_ROOT"), "Real data not configured")
    def test_local_cmdd_photos_have_verified_trays(self):
        photos, _, issues = core_photos.index_photos(os.environ["HYLOGGER_DATA_ROOT"], ["CMDD001", "CMDD002"])
        self.assertFalse(issues)
        self.assertEqual(sum(p["hole_id"] == "CMDD001" for p in photos), 12)
        self.assertEqual(sum(p["hole_id"] == "CMDD002" for p in photos), 23)
        matched = [p["tray_number"] for p in photos if p["hole_id"] == "CMDD002"
                   and any(r["from_m"] < 146 and r["to_m"] >= 128 for r in p["rows"])]
        self.assertEqual(matched, [18, 19, 20, 21, 22])


if __name__ == "__main__":
    unittest.main()
