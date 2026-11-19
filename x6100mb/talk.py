"""The talking boot menu's prompts (Extras, alpha), for blind operators.

The menu itself is Jim Ruiz's talkmenu (X6100 Talking MultiBoot, GPL-2.0-or-later): it plays
BOOT/TALK/MENU.WAV ("Boot menu. Press F1 for ..."), STARTn.WAV for the key pressed, WAITn.WAV and
OFF.WAV, reads BOOT/talkmenu.txt, marks the choice in the card's sector 2 ("BM" and the key's digit)
and switches the radio off; at the next power-on the screen menu starts that system once.

The prompts are put together here, for each card, from short recordings in the voice Jim's menu
uses (RHVoice Lyubov; extras/talk/voice.py makes them, the app carries them as talk-voice.zip):
whole sentences for the keys, and each system's name said word by word (known names as they are
spoken, version numbers as numbers, anything else letter by letter).
"""
import array
import io
import json
import re
import wave
import zipfile

KEYS = range(1, 6)
LETTERS = {"a": "ay", "b": "bee", "c": "see", "d": "dee", "e": "ee", "f": "eff", "g": "gee", "h": "aitch",
           "i": "eye", "j": "jay", "k": "kay", "l": "el", "m": "em", "n": "en", "o": "oh", "p": "pee",
           "q": "cue", "r": "are", "s": "ess", "t": "tee", "u": "you", "v": "vee", "w": "double you",
           "x": "ex", "y": "why", "z": "zed"}
# Names said as their projects say them (whole words: they sound better than spelt)
NAMES = {"openx6x00": "Open X 6 X hundred", "openx6100": "Open X 6 1 hundred", "xiegu": "Xiegu",
         "doom": "Doom", "nes": "N E S emulator", "debian": "Debian", "emmc": "from the radio's memory",
         "cx8anm": "C X 8 A N M", "1ko125": "1 K O 1 2 5", "iu1wxy": "I U 1 W X Y", "r1cbu": "R 1 C B U",
         "x6100": "X 6 1 hundred", "x6x00": "X 6 X hundred"}
WORDS = ["version", "point", "test", "beta", "alpha", "original", "speech", "access", "with", "the",
         "menu", "system", "talking", "games", "emulator", "classic", "and", "no"]
FRAGMENTS = {
    "boot_menu": "Boot menu.",
    "press_power": "Press the power button to begin booting.",
    "power_off": "Power off.",
    **{"press_%d" % k: "Press F%d for" % k for k in KEYS},
    **{"pressed_%d" % k: "You pressed F%d," % k for k in KEYS},
    **{"wait_%d" % k: "If no key is pressed, F%d starts by itself." % k for k in KEYS},
    **{"name_" + k: v for k, v in NAMES.items()},
    **{"word_" + w: w for w in WORDS},
    **{"letter_" + k: v for k, v in LETTERS.items()},
    **{"num_%d" % n: str(n) for n in list(range(0, 21)) + list(range(30, 101, 10))},
}
XIEGU = object()                  # the Xiegu system from the eMMC: said as a sentence of its own
RATE = 48000                      # what the talking menu plays (aplay on the card's codec)


def _number(run):
    """Digits as words: up to 100 as a number (29: twenty nine), longer ones digit by digit"""
    n = int(run)
    if n > 100 or str(n) != run:
        return ["num_%s" % d for d in run]
    if n <= 20 or n % 10 == 0:
        return ["num_%d" % n]
    return ["num_%d" % (n - n % 10), "num_%d" % (n % 10)]


def _word(w):
    """Fragment keys for one word of a name"""
    if w in NAMES:
        return ["name_" + w]
    if w in WORDS:
        return ["word_" + w]
    out = []
    for run in re.findall(r"[a-z]+|\d+", w):
        if run.isdigit():
            out += _number(run)
        else:
            out += ["letter_" + ch for ch in run]
    return out


def speak(name):
    """A system's name as fragment keys: "OpenX6X00 v0.3.12" -> Open X 6 X hundred, version 0 point 3
    point 12; None between them is a short pause"""
    s = name.lower().replace("(", " ").replace(")", " ")
    out = []
    for tok in re.split(r"[\s/_]+", s):
        if not tok:
            continue
        m = re.fullmatch(r"v?(\d+(?:\.\d+)+)(?:-?([a-z]+)(\d*))?", tok)
        if m:                                     # a version: v0.3.12, 1.1-beta1
            if out and out[-1] is not None:
                out.append(None)
            out.append("word_version")
            for i, part in enumerate(m.group(1).split(".")):
                if i:
                    out.append("word_point")
                out += _word(part)
            if m.group(2):
                out += _word(m.group(2)) + (_word(m.group(3)) if m.group(3) else [])
            continue
        for k, part in enumerate(tok.split("-")):
            if part:
                if k:
                    out.append(None)
                out += _word(part)
        out.append(None)
    while out and out[-1] is None:
        out.pop()
    return out


class Voice:
    """The recordings (talk-voice.zip), each cut at its silences, as 48 kHz samples"""

    def __init__(self, zip_path):
        self.clips = {}
        with zipfile.ZipFile(zip_path) as z:
            index = json.loads(z.read("index.json"))["files"]
            for key, fname in index.items():
                with wave.open(io.BytesIO(z.read(fname))) as w:
                    rate = w.getframerate()
                    pcm = array.array("h", w.readframes(w.getnframes()))
                self.clips[key] = _resample(_trim(pcm, rate), rate)

    def join(self, keys, gap_ms=60, pause_ms=260):
        """Samples of the fragments one after another: gap_ms between words, pause_ms where None"""
        out = array.array("h")
        gap = array.array("h", bytes(2 * RATE * gap_ms // 1000))
        pause = array.array("h", bytes(2 * RATE * pause_ms // 1000))
        for k in keys:
            if k is None:
                out.extend(pause)
                continue
            clip = self.clips.get(k)
            if clip is None:
                continue
            out.extend(clip)
            out.extend(gap)
        return out


def _trim(pcm, rate, level=350, keep_ms=30):
    """Leading and trailing silence cut, a little kept"""
    n = len(pcm)
    a = next((i for i in range(n) if abs(pcm[i]) > level), 0)
    b = next((i for i in range(n - 1, -1, -1) if abs(pcm[i]) > level), n - 1)
    keep = rate * keep_ms // 1000
    return pcm[max(0, a - keep):min(n, b + keep + 1)]


def _resample(pcm, rate):
    """To 48 kHz by straight lines between the samples (as Jim's rhv_fetch.py does)"""
    if rate == RATE:
        return array.array("h", pcm)
    out = array.array("h")
    m = len(pcm)
    for j in range(m * RATE // rate):
        x = j * rate / RATE
        i = int(x)
        f = x - i
        v = pcm[i] if i + 1 >= m else int(pcm[i] + (pcm[i + 1] - pcm[i]) * f)
        out.append(v)
    return out


def _wav(mono):
    """48 kHz stereo 16-bit, both channels the same (what the talking menu plays)"""
    st = array.array("h", bytes(4 * len(mono)))
    st[0::2] = mono
    st[1::2] = mono
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(st.tobytes())
    return buf.getvalue()


def prompts(voice, choices):
    """BOOT/TALK's files for the keys in choices {key: a system's name, or XIEGU}: {file name: WAV bytes}"""
    files = {}
    menu = ["boot_menu", None]
    for k, name in sorted(choices.items()):
        said = (["word_the", "word_original", "name_xiegu", "word_system", None, "name_emmc"]
                if name is XIEGU else speak(name))
        menu += ["press_%d" % k] + said + [None]
        files["START%d.WAV" % k] = _wav(voice.join(["pressed_%d" % k] + said + [None, "press_power"]))
    files["MENU.WAV"] = _wav(voice.join(menu))
    for k in KEYS:
        files["WAIT%d.WAV" % k] = _wav(voice.join(["wait_%d" % k]))
    files["OFF.WAV"] = _wav(voice.join(["power_off"]))
    return files


def settings(default_key, self_key, wait=30, volume=20, headphone=47):
    """BOOT/talkmenu.txt (read by the talking menu)"""
    return ("# The talking menu: the key started when no key is pressed (1-5), seconds of talking before\r\n"
            "# it starts (0: waits for a key), the radio's volume while it talks (0-55), the codec's level\r\n"
            "# to the radio board (0-63), the talking menu's own key\r\n"
            "default=%d\r\nwait=%d\r\nvolume=%d\r\nheadphone=%d\r\nself=%d\r\n"
            % (default_key, wait, volume, headphone, self_key)).encode()
