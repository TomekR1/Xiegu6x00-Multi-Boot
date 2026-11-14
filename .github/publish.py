"""Puts one app into the newest release as soon as that app is built (run by each app's job).

The release is named after the three apps' own version numbers (x6100mb/assets/versions.json).
The first app ready makes the release, marked Latest, with the other apps of the previous release
in it until theirs are built; each app then replaces its own file. A push in which no version
number went up (the release exists for another commit) releases nothing.
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import time

REPO = os.environ["GITHUB_REPOSITORY"]
SHA = os.environ["GITHUB_SHA"]
MINE = sys.argv[1:]                       # this job's files: its app and the U-Boot
# A version given with a hyphen (v0.2.11-test1): a pre-release for testers, not the newest release
# on the repository's page; made of this build's own files only
TEST = "-" in (os.environ.get("GIVEN") or "")


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit("gh %s: %s" % (" ".join(args), r.stderr))
    return r


def tag_commit(tag):
    r = gh("api", "repos/%s/commits/%s" % (REPO, tag), "--jq", ".sha", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def notes(v):
    msg = (os.environ.get("MSG") or "").strip().split("\n")[0]
    if TEST:
        return ("**Wersja testowa (pre-release): do sprawdzenia przed wydaniem, nie do zwykłego użytku.**\n\n"
                "**A test version (pre-release): for checking before the release, not for everyday use.**\n\n"
                f"Windows {v['windows']} · macOS {v['macos']} · Linux {v['linux']}\n\n"
                "Do sprawdzenia: sekcja 4 „Kopie ustawień (DATA)”: kopia DATA, przywracanie, DATA każdego systemu, "
                "własna kopia DATA dla nowej karty.\n")
    return f"""Kilka systemów na jednej karcie SD dla Xiegu X6100, z menu na ekranie radia (F1–F5).

**Pobierz aplikację dla swojego komputera** (każda ma swój numer wersji):
- Windows {v['windows']}: `Xiegu-Multi-Patcher.exe`
- macOS {v['macos']}: `Xiegu-Multi-Patcher-macOS.zip` (rozpakuj; za pierwszym razem: Ustawienia systemowe → Prywatność i ochrona → Otwórz mimo to)
- Linux {v['linux']}: `Xiegu-Multi-Patcher-Linux` (`chmod +x`; do zapisu karty potrzebny pkexec)

Systemy radia (OpenX6X00, OpenX6100, CX8ANM, 1KO125, IU1WXY, R1CBU) pobierasz w aplikacji
przyciskiem **+ Z internetu…**, prosto z wydań ich autorów. Instrukcja: README w repozytorium.

W sekcji **Extras** aplikacji: klasyczny Doom na radiu (Freedoom), z dźwiękiem i muzyką na głośniku radia,
myszą i klawiaturą USB albo Bluetooth.

Ostatnia zmiana: {msg or 'zobacz historię zmian'}

`u-boot-x6100-menu.bin`: U-Boot menu z obsługą ekranu X6100 (aplikacja ma go w sobie).

Problemy zgłaszaj w Issues. Aplikacja: SQ6RT, https://www.qrz.com/db/SQ6RT
"""


def main():
    with open("x6100mb/assets/versions.json") as f:
        v = json.load(f)
    tag = os.environ.get("GIVEN") or "win%s-mac%s-linux%s" % (v["windows"], v["macos"], v["linux"])
    title = "Xiegu Multi Patcher · Windows %s · macOS %s · Linux %s" % (v["windows"], v["macos"], v["linux"])
    if TEST:
        title = "TEST (pre-release) " + tag + " · " + title
    have = tag_commit(tag)
    if have and have != SHA:
        print(f"{tag} is out already (another commit): no version number went up, nothing to release")
        return
    if not have:
        tmp = tempfile.mkdtemp()
        names = {os.path.basename(m) for m in MINE}
        prev = gh("release", "view", "-R", REPO, "--json", "tagName,assets", check=False)
        carried = []
        if prev.returncode == 0 and not TEST:
            p = json.loads(prev.stdout)
            for a in p["assets"]:
                if a["name"] not in names and a["name"].startswith("Xiegu-Multi-Patcher"):
                    gh("release", "download", p["tagName"], "-R", REPO, "-p", a["name"], "-D", tmp)
            carried = glob.glob(os.path.join(tmp, "*"))
        nf = os.path.join(tmp, "notes.md")
        with open(nf, "w", encoding="utf-8") as f:
            f.write(notes(v))
        r = gh("release", "create", tag, "-R", REPO, "--target", SHA, "--title", title, "--notes-file", nf,
               *(["--prerelease", "--latest=false"] if TEST else ["--latest"]), *carried, *MINE, check=False)
        if r.returncode == 0:
            print(f"{tag}: released, Latest ({', '.join(sorted(names))}; carried over: {len(carried)})")
            gh("release", "delete", "test-build", "--cleanup-tag", "--yes", "-R", REPO, check=False)
            return
        print("create:", r.stderr.strip(), "- another app made it first; uploading into it")
        for _ in range(10):
            if tag_commit(tag):
                break
            time.sleep(5)
    # Two apps finishing at once: a second try once the other's upload is over
    for attempt in range(5):
        r = gh("release", "upload", tag, "-R", REPO, "--clobber", *MINE, check=False)
        if r.returncode == 0:
            break
        print("upload:", r.stderr.strip(), "- again")
        time.sleep(10 * (attempt + 1))
    else:
        raise SystemExit("upload failed")
    if not TEST:
        gh("release", "edit", tag, "-R", REPO, "--latest")
    print(f"{tag}: {', '.join(os.path.basename(m) for m in MINE)} in")


if __name__ == "__main__":
    main()
