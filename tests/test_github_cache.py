import email.message
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from x6100mb import catalog  # noqa: E402


class Fake:
    """GitHub as the catalog sees it: answers, 304 for an unchanged list, 403 at the limit"""

    def __init__(self):
        self.calls, self.mode = [], "ok"

    def __call__(self, req, timeout):
        self.calls.append(dict(req.header_items()))
        h = email.message.Message()
        if self.mode == "limit":
            h["X-RateLimit-Remaining"] = "0"
            raise urllib.error.HTTPError(req.full_url, 403, "rate limit", h, io.BytesIO())
        if self.mode == "down":
            raise urllib.error.URLError("no network")
        if req.get_header("If-none-match") == '"v1"':
            raise urllib.error.HTTPError(req.full_url, 304, "not modified", h, io.BytesIO())

        class R(io.BytesIO):
            headers = {"ETag": '"v1"'}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R(json.dumps([{"tag_name": "v1"}]).encode())


class GithubCacheTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.environ["XDG_CONFIG_HOME"] = self.d
        os.environ.pop("APPDATA", None)
        os.environ.pop("GITHUB_TOKEN", None)
        self.fake = Fake()
        self._open = catalog._open
        catalog._open = self.fake
        catalog.last_from.clear()

    def tearDown(self):
        catalog._open = self._open
        shutil.rmtree(self.d, ignore_errors=True)

    def test_kept_conditional_and_stale(self):
        url = "https://api.github.com/repos/a/b/releases?per_page=15"
        self.assertEqual(catalog._get(url, now=1000)[0]["tag_name"], "v1")
        catalog._get(url, now=1000 + 60)                       # within 30 min: GitHub not asked
        self.assertEqual(len(self.fake.calls), 1)
        catalog._get(url, now=1000 + 3600)                     # later: asked "if changed" -> 304
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(self.fake.calls[1].get("If-none-match"), '"v1"')
        self.fake.mode = "limit"                               # refused: the kept list, marked so
        self.assertEqual(catalog._get(url, now=1000 + 9000)[0]["tag_name"], "v1")
        self.assertIn(url, catalog.last_from)
        self.fake.mode = "down"
        self.assertEqual(catalog._get(url, now=1000 + 20000)[0]["tag_name"], "v1")

    def test_limit_without_anything_kept(self):
        self.fake.mode = "limit"
        with self.assertRaises(catalog.CatalogError) as e:
            catalog._get("https://api.github.com/repos/x/y/releases?per_page=15", now=5)
        self.assertIn("60", str(e.exception))

    def test_token_sent(self):
        from x6100mb import i18n
        i18n.set_setting("github_token", "abc")
        catalog._get("https://api.github.com/repos/t/t/releases?per_page=15", now=1)
        self.assertEqual(self.fake.calls[-1].get("Authorization"), "Bearer abc")


if __name__ == "__main__":
    unittest.main()
