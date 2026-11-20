"""The talking menu's voice: short recordings made with RHVoice (voice Lyubov, as Jim Ruby's
X6100 Talking MultiBoot uses), from which the app puts together each card's own prompts
(x6100mb/talk.py: the systems' names, the keys, the sentences).

    python3 voice.py OUT.zip        (needs RHVoice-test and the voice: apt install rhvoice rhvoice-english)

The voice: RHVoice Lyubov, (c) Artem Plaksin, Sergey Parshakov, Beka Gozalishvili, Lyubov Sablina,
CC BY-NC-ND 4.0 (non-commercial use, with credit; the recordings are not changed, only cut
at their silences and joined). RHVoice itself: LGPL-2.1+, Olga Yakovleva.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import wave
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from x6100mb.talk import FRAGMENTS, _trim  # noqa: E402
import array  # noqa: E402

VOICE = os.environ.get("TALK_VOICE", "lyubov")
RATE = os.environ.get("TALK_RATE", "120")      # % of the voice's own pace: a little faster (Jim Ruby's test, 2026-11-20)


def say(text, tmp):
    src, out = os.path.join(tmp, "in.txt"), os.path.join(tmp, "out.wav")
    with open(src, "w") as f:
        f.write(text + "\n")
    subprocess.run(["RHVoice-test", "-p", VOICE, "-r", RATE, "-i", src, "-o", out], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with wave.open(out) as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1, text
        return w.getframerate(), w.readframes(w.getnframes())


def main(out):
    tmp = tempfile.mkdtemp()
    index = {}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for key, text in FRAGMENTS.items():
            rate, pcm = say(text, tmp)
            pcm = _trim(array.array("h", pcm), rate, keep_ms=40).tobytes()     # the silences around it cut
            name = key + ".wav"
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm)
            z.writestr(name, buf.getvalue())
            index[key] = name
        z.writestr("index.json", json.dumps({"voice": VOICE, "rate": RATE, "files": index}, indent=1))
    print(out, len(index), "recordings")


if __name__ == "__main__":
    main(sys.argv[1])
