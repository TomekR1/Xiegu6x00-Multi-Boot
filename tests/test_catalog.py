"""The catalog against a canned GitHub answer, and a download from a file:// URL."""
import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from x6100mb import catalog  # noqa: E402

ANSWER = [
    {"tag_name": "v0.4.0-rc1", "published_at": "2026-11-20T10:00:00Z", "prerelease": True, "draft": False,
     "assets": [{"name": "OpenX6X00-x6100-v0.4.0-sdcard.img.zip", "size": 10, "browser_download_url": "u1"}]},
    {"tag_name": "v0.3.9", "published_at": "2026-11-06T10:00:00Z", "prerelease": False, "draft": False,
     "assets": [{"name": "OpenX6X00-x6200-v0.3.9-sdcard.img.zip", "size": 9, "browser_download_url": "x6200"},
                {"name": "OpenX6X00-x6100-v0.3.9-sdcard.img.zip", "size": 8, "browser_download_url": "u2",
                 "digest": "sha256:" + "ab" * 32},
                {"name": "OpenX6X00-x6100-v0.3.9-update.tar.gz", "size": 7, "browser_download_url": "upd"}]},
    {"tag_name": "v0.3.8", "published_at": "2026-10-30T10:00:00Z", "prerelease": False, "draft": True,
     "assets": [{"name": "OpenX6X00-x6100-v0.3.8-sdcard.img.zip", "size": 6, "browser_download_url": "u3"}]},
    {"tag_name": "v0.3.7", "published_at": "2026-10-20T10:00:00Z", "prerelease": False, "draft": False,
     "assets": [{"name": "notes.txt", "size": 1, "browser_download_url": "n"}]},
]


class CatalogTest(unittest.TestCase):
    def test_releases_pick_x6100_images_newest_first(self):
        src = catalog.SOURCES[0]
        rels = catalog.releases(src, fetch=lambda url: ANSWER)
        self.assertEqual([r["tag"] for r in rels], ["v0.4.0-rc1", "v0.3.9"])   # no draft, no image-less one
        self.assertTrue(rels[0]["prerelease"])
        self.assertEqual(rels[1]["url"], "u2")                                  # x6100, not x6200 or the bundle
        self.assertEqual(rels[1]["sha256"], "ab" * 32)
        self.assertEqual(catalog.label(src, rels[1]), "OpenX6X00 v0.3.9")

    def test_other_sources_match_their_assets(self):
        names = {"openx6100": ["sdcard.v1.2.0.img.zip"], "r1cbu": ["sdcard.img.zip"],
                 "cx8anm": ["OpenX6X00-CX8ANM-x6100-v1.1.5-sdcard.img.zip", "Xiegu_X6100-CX8ANM_v1.0.52.img.zip"]}
        for src in catalog.SOURCES[1:]:
            want = names[src["id"]]
            feeds = {repo: want[k] for k, (repo, _) in enumerate(src["feeds"])}

            def fetch(url, feeds=feeds):
                repo = url.split("/repos/")[1].split("/releases")[0]
                return [{"tag_name": "v1." + str(len(repo)), "published_at": "2026-01-%02d" % len(repo), "assets": [
                    {"name": "OpenX6X00-CX8ANM-x6200-v1.1.5-sdcard.img.zip", "size": 1, "browser_download_url": "x"},
                    {"name": feeds[repo], "size": 1, "browser_download_url": repo}]}]
            rels = catalog.releases(src, fetch=fetch)
            self.assertEqual(len(rels), len(want), src["id"])
            self.assertTrue(all(r["url"] != "x" for r in rels))

    def test_download_checks_size_and_sha(self):
        d = tempfile.mkdtemp()
        f = os.path.join(d, "img.zip")
        data = b"x" * 3000
        with open(f, "wb") as fh:
            fh.write(data)
        src = catalog.SOURCES[0]
        good = {"tag": "v1", "asset": "a.img.zip", "size": len(data), "url": "file://" + f,
                "sha256": hashlib.sha256(data).hexdigest()}
        cache = os.path.join(d, "cache")
        path = catalog.download(src, good, cache)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), data)
        bad = dict(good, tag="v2", sha256="00" * 32)
        with self.assertRaises(catalog.CatalogError):
            catalog.download(src, bad, cache)


if __name__ == "__main__":
    unittest.main()
