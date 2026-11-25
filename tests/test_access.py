"""The accessible mode (alpha): its page, its actions as a screen reader hears them, its server's key."""
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from x6100mb import access, devices  # noqa: E402
from x6100mb.image import SourceSystem  # noqa: E402
from test_compose import fake_card  # noqa: E402


class AccessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._list = devices.list_cards
        devices.list_cards = lambda: [{"path": "/dev/fake", "name": "Fake SD", "size": 8 << 30, "mounts": []}]

    def tearDown(self):
        devices.list_cards = self._list

    def said(self, e):
        return [m["text"] for m in e.state()["messages"]]

    def test_page_is_whole_and_labelled(self):
        p = access.page()
        self.assertNotIn("{{", p)
        self.assertIn('role="status"', p)
        self.assertIn('role="alert"', p)
        # every select and input sits in a label (or is a file input in one)
        for m in re.finditer(r"<(select|input)\b[^>]*>", p):
            before = p[:m.start()]
            self.assertGreater(before.rfind("<label"), before.rfind("</label>"), m.group(0))

    def test_actions_are_said(self):
        e = access.Engine()
        a = os.path.join(self.tmp, "a.img")
        fake_card(a)
        with self.assertRaises(ValueError):
            e.add_extra("talk")                     # no system with a kernel yet
        e.entries.append({"kind": "sd", "name": "OpenX6X00", "base": "OpenX6X00", "version": "v0.3.13",
                          "sys": SourceSystem(a, a)})
        e.add_extra("xiegu")
        e.add_extra("talk")
        e.move(2, -1)
        e.set_default(1)
        st = e.state()
        self.assertEqual([x["name"] for x in st["entries"]], ["OpenX6X00", "Talking menu", "Xiegu (eMMC)"])
        self.assertTrue(st["entries"][1]["default"])
        said = " | ".join(self.said(e))
        self.assertIn("F3", said)
        self.assertIn("F2", said)
        e.remove(0)
        self.assertEqual(e.state()["entries"][0]["key"], "F1")

    def test_write_is_asked_first(self):
        e = access.Engine()
        a = os.path.join(self.tmp, "a.img")
        fake_card(a)
        e.entries.append({"kind": "sd", "name": "OpenX6X00", "sys": SourceSystem(a, a)})
        try:
            text = e.ask_write(0)
        except ValueError as ex:                    # no menu U-Boot in a source checkout: said plainly
            self.assertIn("U-Boot", str(ex))
            return
        self.assertIn("Fake SD", text)
        self.assertIn("F1 OpenX6X00", text)
        e.do_write(False)                           # "Cancel": nothing written
        self.assertIsNone(e.state()["confirm"])
        self.assertFalse(e.state()["busy"])

    def test_server_needs_its_key(self):
        url, srv, _closed = access.serve(access.Engine())
        try:
            with urllib.request.urlopen(url + "api/state") as r:
                self.assertIn("entries", json.loads(r.read()))
            bad = url.rsplit("/", 2)[0] + "/wrongkey/api/state"
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(bad)
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
