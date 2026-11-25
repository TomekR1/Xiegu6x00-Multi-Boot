"""The talking boot menu (alpha): names said word by word, prompts put together, the card's files."""
import array
import io
import json
import os
import sys
import tempfile
import unittest
import wave
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from x6100mb import talk  # noqa: E402
from x6100mb.compose import compose, menu_script  # noqa: E402
from x6100mb.fat import FatReader  # noqa: E402
from x6100mb.image import SourceSystem, parse_script_image, read_mbr, SECTOR  # noqa: E402
from x6100mb.writer import write_image_file  # noqa: E402
from test_compose import fake_card  # noqa: E402


def fake_voice(path):
    """A voice zip of short tones, one per fragment (no RHVoice needed for the tests)"""
    with zipfile.ZipFile(path, "w") as z:
        index = {}
        for k, key in enumerate(talk.FRAGMENTS):
            pcm = array.array("h", ([0] * 200) + ([4000, -4000] * (300 + k)) + ([0] * 200))
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm.tobytes())
            z.writestr(key + ".wav", buf.getvalue())
            index[key] = key + ".wav"
        z.writestr("index.json", json.dumps({"voice": "test", "files": index}))


def said(name):
    return " ".join(talk.FRAGMENTS[k] if k else "|" for k in talk.speak(name))


class TalkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_names_said(self):
        self.assertEqual(said("OpenX6X00 v0.3.12"), "Open X 6 X hundred | version 0 point 3 point 12")
        self.assertEqual(said("R1CBU v0.29"), "R 1 C B U | version 0 point 20 9")
        self.assertEqual(said("1KO125 v1.1-beta1"), "1 K O 1 2 5 | version 1 point 1 beta 1")
        self.assertEqual(said("NES"), "N E S emulator")
        self.assertEqual(said("me/fw v12"), "em ee | eff double you | vee 12")
        for key in talk.speak("anything at all 123456 v9.99"):
            self.assertTrue(key is None or key in talk.FRAGMENTS, key)

    def test_prompts(self):
        vz = os.path.join(self.tmp, "voice.zip")
        fake_voice(vz)
        files = talk.prompts(talk.Voice(vz), {1: "OpenX6X00 v0.3.12", 3: talk.XIEGU})
        self.assertEqual(sorted(files), ["BOOT1.WAV", "BOOT3.WAV", "MENU.WAV", "OFF.WAV", "START1.WAV", "START3.WAV"] +
                         ["WAIT%d.WAV" % k for k in talk.KEYS])
        for name, data in files.items():
            with wave.open(io.BytesIO(data)) as w:
                self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (48000, 2, 2), name)
                self.assertGreater(w.getnframes(), 1000, name)

    def test_every_menu_starts_a_marked_system_once(self):
        a = os.path.join(self.tmp, "a.img")
        fake_card(a)
        s = menu_script([{"kind": "sd", "name": "A", "sys": SourceSystem(a, a), "dir": "SYS1", "part": 2},
                         {"kind": "xiegu", "name": "Xiegu"}], 0, 5)
        self.assertIn("mmc read 0x45200000 2 1", s)
        self.assertIn("if itest.b *0x45200002 == 0x32; then setenv bm_once 2; fi", s)
        self.assertNotIn("== 0x33", s)                        # only the keys there are
        self.assertIn("mmc write 0x45200000 2 1", s)           # the mark cleared
        self.assertLess(s.index("bm_once"), s.index('while test -z "${bm_choice}"'))

    def test_card_with_the_talking_menu(self):
        from x6100mb.compose import resolve_extras
        import lzma
        a, b = os.path.join(self.tmp, "a.img"), os.path.join(self.tmp, "b.img")
        fake_card(a)
        fake_card(b)
        rootfs, vz = os.path.join(self.tmp, "talk.ext4.xz"), os.path.join(self.tmp, "voice.zip")
        with lzma.open(rootfs, "wb") as f:
            f.write(b"\0" * (2 << 20))
        fake_voice(vz)
        ents = resolve_extras([{"kind": "sd", "name": "OpenX6X00 v0.3.12", "sys": SourceSystem(a, a)},
                               {"kind": "talk", "name": "Talking menu"},
                               {"kind": "sd", "name": "OpenX6100 v1.2.0", "sys": SourceSystem(b, b)}],
                              {"talk": rootfs})
        plan = compose(ents, default=2, timeout_s=3, data_mb=40, talk_voice=vz, wait=True)
        out = os.path.join(self.tmp, "card.img")
        write_image_file(plan, out)
        with open(out, "rb") as f:
            parts = {p[0]: p for p in read_mbr(f)}
            boot = FatReader(f, parts[1][2] * SECTOR)
            conf = boot.read_file("talkmenu.txt").decode()
            env = boot.read_file("bootmenu.env").decode()
            script = parse_script_image(boot.read_file("boot.scr"))
            self.assertTrue(boot.read_file("TALK/MENU.WAV"))
            self.assertTrue(boot.read_file("TALK/START1.WAV"))
            self.assertTrue(boot.read_file("TALK/START3.WAV"))
            self.assertIsNone(boot.find("TALK/START2.WAV"))      # its own key is not a choice
        self.assertIn("default=3", conf)                         # the app's default, said by the menu
        self.assertIn("self=2", conf)
        self.assertIn("bm_default=2", env)                       # the screen starts the talking menu
        self.assertIn("bm_wait=0", env)                          # never waits: it must start by itself
        talk_boot = next(l for l in script.splitlines() if l.startswith("setenv bm_boot2 "))
        self.assertIn("doom_modules=/dev/mmcblk0p2", talk_boot)  # sound and kernel from OpenX6X00


if __name__ == "__main__":
    unittest.main()
