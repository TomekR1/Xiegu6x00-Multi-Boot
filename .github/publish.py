"""Puts one app into the newest release as soon as that app is built (run by each app's job).

The release is named after the three apps' own version numbers (x6100mb/assets/versions.json).
The first app ready makes the release, marked Latest, with the other apps of the previous release
in it until theirs are built; each app then replaces its own file. A push in which no version
number went up (the release exists for another commit) releases nothing.
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time

REPO = os.environ["GITHUB_REPOSITORY"]
SHA = os.environ["GITHUB_SHA"]
MINE = sys.argv[1:]                       # this job's files: its app and the U-Boot
# A version given with a hyphen (v0.2.11-test1): a pre-release for testers, not the newest release
# on the repository's page; made of this build's own files only
TEST = bool(re.search(r"-(test|beta|rc)", os.environ.get("GIVEN") or ""))
# What a release holds; anything else in it (a file of an earlier way of packing, carried over) goes
KNOWN = {"Xiegu-Multi-Patcher-Windows.zip", "Xiegu-Multi-Patcher-macOS.zip", "Xiegu-Multi-Patcher-Linux.zip",
         "u-boot-x6100-menu.bin", "nes-x6100-rootfs.ext4.xz", "nes-x6100-rootfs.ext4.xz.sha256", "nes-version.txt"}

# A former test version kept as a page with a link to the release (links to it went round): pruning leaves it
MOVED = "<!-- moved-to-main -->"
# Test versions kept while final releases come out (alphas tested on the radio for longer)
KEEP_TESTS = ("talk-alpha",)


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit("gh %s: %s" % (" ".join(args), r.stderr))
    return r


def tag_commit(tag):
    r = gh("api", "repos/%s/commits/%s" % (REPO, tag), "--jq", ".sha", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


TALK_NOTES = """**Wersja alfa: menu mówione dla niewidomych operatorów.** Do testów na radiu; zwykłe wydanie: [Releases](https://github.com/{repo}/releases/latest).
**Alpha: a talking boot menu for blind operators.** For testing on the radio; the regular release: [Releases](https://github.com/{repo}/releases/latest).

Windows {w} · macOS {m} · Linux {l}. Pliki jak w zwykłym wydaniu: `.zip` dla swojego komputera, w środku instrukcja. / The files as in the regular release: the `.zip` for your computer, with the guide inside.

### Menu mówione / Talking menu
- W aplikacji: **Extras → + Menu mówione (alfa)**, czas na ekranie najlepiej 3 s. / In the app: **Extras → + Talking menu (alpha)**, the screen's time best 3 s.
- Gdy przy włączaniu radia nikt nie wciśnie klawisza, menu czyta wybór na głos: „Boot menu. Press F1 for …”. / When nobody presses a key at power-on, the menu says the choices aloud.
- F1–F5: radio się wyłącza i prosi o POWER; po włączeniu startuje wybrany system. Bez wyboru po 30 s startuje system z ★. / F1–F5: the radio switches off and asks for POWER; at power-on the chosen system starts. Without a choice, the ★ system starts after 30 s.
- Każde menu (także bez menu mówionego) uruchamia raz system zaznaczony w sektorze 2 karty („BM” i cyfra). / Every menu starts a system marked in the card's sector 2 ("BM" and a digit) once.

Program menu: **talkmenu** z [X6100 Talking MultiBoot](https://github.com/Jimr9/X6100-Talking-MultiBoot), Jim Ruby (GPL-2.0-or-later). Głos / voice: **RHVoice Lyubov** (Artem Plaksin, Sergey Parshakov, Beka Gozalishvili, Lyubov Sablina; CC BY-NC-ND 4.0, non-commercial).

Uwagi i błędy / Feedback: [Issues](https://github.com/{repo}/issues).
"""


def notice():
    """A notice for this release, centred in the middle of its description (.github/NOTICE.md; ""
    without it: take the file away once it no longer applies)"""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "NOTICE.md"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def whats_new():
    """The release's own short list of news (.github/WHATS-NEW.md: Polish, a line of ---, English);
    ("", "") without it"""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "WHATS-NEW.md"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return "", ""
    pl, _, en = text.partition("\n---\n")
    return pl.strip(), en.strip()


def notes(v):
    if TEST and (os.environ.get("GIVEN") or "").startswith("talk-alpha"):
        return TALK_NOTES.format(w=v["windows"], m=v["macos"], l=v["linux"], repo=REPO)
    if TEST:
        return ("**Wersja testowa (pre-release), nie do zwykłego użytku.**\n\n"
                "**A test version (pre-release), not for everyday use.**\n\n"
                f"Windows {v['windows']} · macOS {v['macos']} · Linux {v['linux']}\n")
    pl_new, en_new = whats_new()
    pl_news = f"\n### Co nowego\n{pl_new}\n" if pl_new else ""
    en_news = f"\n### What's new\n{en_new}\n" if en_new else ""
    middle = f"\n---\n\n{notice()}\n\n---\n" if notice() else "\n---\n"
    return f"""Kilka systemów na jednej karcie SD do **Xiegu X6100**. Przy włączaniu radia wybierasz system klawiszem **F1–F5**.

### Pobierz
Na dole strony, w części **Assets**, pobierz plik dla swojego komputera:
- **Windows** ({v['windows']}): `Xiegu-Multi-Patcher-Windows.zip`. Rozpakuj (prawy przycisk → Wyodrębnij wszystkie) i uruchom `Xiegu Multi Patcher.exe`.
- **macOS** ({v['macos']}): `Xiegu-Multi-Patcher-macOS.zip`. Rozpakuj i przenieś do Programów. Jeśli macOS zablokuje aplikację: Ustawienia systemowe → Prywatność i ochrona → Otwórz mimo to.
- **Linux** ({v['linux']}): `Xiegu-Multi-Patcher-Linux.zip`. Rozpakuj i uruchom `Xiegu Multi Patcher`.

W każdej paczce jest **instrukcja krok po kroku**: `INSTRUKCJA.html` (otwórz w przeglądarce).

### Co potrafi
- Pobiera systemy radia (OpenX6X00, OpenX6100, CX8ANM, 1KO125, IU1WXY, R1CBU) prosto od ich autorów, także z Twojego własnego repozytorium GitHub.
- W menu może być też oryginalny system Xiegu z pamięci radia.
- Przenosi ustawienia, logi i parowania ze starej karty na nową.
- Dodatki: **Doom** i **emulator NES** (Twoje gry, pady USB i Bluetooth, gry wgrywane przez WiFi).
{pl_news}{middle}
Several systems on one SD card for the **Xiegu X6100**. At power-on you choose one with the **F1–F5** keys.

### Download
At the bottom of this page, under **Assets**, get the file for your computer:
- **Windows** ({v['windows']}): `Xiegu-Multi-Patcher-Windows.zip`. Unpack it (right-click → Extract All) and run `Xiegu Multi Patcher.exe`.
- **macOS** ({v['macos']}): `Xiegu-Multi-Patcher-macOS.zip`. Unpack it and move it to Applications. If macOS blocks it: System Settings → Privacy & Security → Open Anyway.
- **Linux** ({v['linux']}): `Xiegu-Multi-Patcher-Linux.zip`. Unpack it and run `Xiegu Multi Patcher`.

Every package has a **step-by-step guide**: `INSTRUCTIONS.html` (open it in a browser).

### What it does
- Fetches the radio's systems (OpenX6X00, OpenX6100, CX8ANM, 1KO125, IU1WXY, R1CBU) straight from their authors, or from your own GitHub repository.
- The menu can also start the original Xiegu system from the radio's memory.
- Carries your settings, logs and pairings over from the old card to the new one.
- Extras: **Doom** and a **NES emulator** (your own games, USB and Bluetooth pads, games uploaded over WiFi).
{en_news}
---

The other files (`u-boot-…`, `nes-…`) are used by the app and the emulator's update; you don't need to download them.
Problems / Problemy: [Issues](https://github.com/{REPO}/issues) · SQ6RT, https://www.qrz.com/db/SQ6RT
"""


def tidy(tag):
    """Files in the release on tag that it should not hold (KNOWN says which) removed"""
    for rid, assets in releases_of(tag):
        if not [a for a in assets if a not in KNOWN]:
            continue
        r = gh("api", "repos/%s/releases/%d/assets" % (REPO, rid), check=False)
        for asset in json.loads(r.stdout or "[]") if r.returncode == 0 else []:
            if asset["name"] not in KNOWN:
                gh("api", "-X", "DELETE", "repos/%s/releases/assets/%d" % (REPO, asset["id"]), check=False)
                print("removed a file the release should not hold:", asset["name"])


def releases_of(tag):
    """[(id, [asset names])] of the releases on this tag, oldest first (two jobs creating it in the
    same second can leave two)"""
    r = gh("api", "repos/%s/releases?per_page=100" % REPO, check=False)
    out = []
    for rel in json.loads(r.stdout or "[]") if r.returncode == 0 else []:
        if rel.get("tag_name") == tag:
            out.append((rel["id"], [a["name"] for a in rel.get("assets", [])]))
    return sorted(out)


def merge_duplicates(tag):
    """Two releases on one tag (a race): the newer ones' files moved into the oldest, then removed"""
    rels = releases_of(tag)
    for rid, assets in rels[1:]:
        tmp = tempfile.mkdtemp()
        for name in assets:
            a = gh("api", "repos/%s/releases/%d/assets" % (REPO, rid), check=False)
            for asset in json.loads(a.stdout or "[]") if a.returncode == 0 else []:
                if asset["name"] == name:
                    with open(os.path.join(tmp, name), "wb") as f:
                        f.write(subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream",
                                                "repos/%s/releases/assets/%d" % (REPO, asset["id"])],
                                               capture_output=True).stdout)
        files = glob.glob(os.path.join(tmp, "*"))
        if files:
            gh("release", "upload", tag, "-R", REPO, "--clobber", *files, check=False)
        gh("api", "-X", "DELETE", "repos/%s/releases/%d" % (REPO, rid), check=False)
        print("merged a second release of", tag, "into the first:", assets)


def prune_tests(keep):
    """Every pre-release but `keep` (earlier tests, betas) and its tag go: one test version at a time,
    and none once a final release is out;
    by id, so that two releases on one tag cannot trip it up"""
    r = gh("api", "repos/%s/releases?per_page=100" % REPO, check=False)
    tags = set()
    for rel in json.loads(r.stdout or "[]") if r.returncode == 0 else []:
        if MOVED in (rel.get("body") or ""):
            continue                      # a page that only points to the release (its link was shared)
        if (rel.get("tag_name") or "").startswith(KEEP_TESTS):
            continue                      # a long-lived alpha (the talking menu): testers keep its link
        if rel.get("prerelease") and rel.get("tag_name") != keep:
            gh("api", "-X", "DELETE", "repos/%s/releases/%d" % (REPO, rel["id"]), check=False)
            tags.add(rel["tag_name"])
            print("removed the earlier pre-release", rel["tag_name"])
    for tg in tags:
        gh("api", "-X", "DELETE", "repos/%s/git/refs/tags/%s" % (REPO, tg), check=False)


def renote(tag):
    """The description of the release on tag written anew from notes() (Build workflow, input notes_tag)"""
    with open("x6100mb/assets/versions.json") as f:
        v = json.load(f)
    nf = os.path.join(tempfile.mkdtemp(), "notes.md")
    with open(nf, "w", encoding="utf-8") as f:
        f.write(notes(v))
    title = "Xiegu Multi Patcher · Windows %s · macOS %s · Linux %s" % (v["windows"], v["macos"], v["linux"])
    if TEST:
        title = "TEST (pre-release) " + tag + " · " + title
    gh("release", "edit", tag, "-R", REPO, "--notes-file", nf, "--title", title)
    print(tag, ": description written anew")


def main():
    if MINE[:1] == ["--notes"]:
        renote(MINE[1])
        return
    with open("x6100mb/assets/versions.json") as f:
        v = json.load(f)
    tag = os.environ.get("GIVEN") or "win%s-mac%s-linux%s" % (v["windows"], v["macos"], v["linux"])
    title = "Xiegu Multi Patcher · Windows %s · macOS %s · Linux %s" % (v["windows"], v["macos"], v["linux"])
    if TEST:
        title = "TEST (pre-release) " + tag + " · " + title
    have = tag_commit(tag)
    if have and have != SHA and TEST:
        # a test version built again under its name: the tag moves to this commit and the files are
        # put in place of the earlier ones, so the links given out stay good
        gh("api", "-X", "PATCH", "repos/%s/git/refs/tags/%s" % (REPO, tag), "-f", "sha=" + SHA, "-F", "force=true",
           check=False)
        print(f"{tag}: a test version built again, its files replaced")
    elif have and have != SHA:
        print(f"{tag} is out already (another commit): no version number went up, nothing to release")
        tidy(tag)
        return
    names = {os.path.basename(m) for m in MINE}
    if not releases_of(tag):
        # The tag first: creating a tag that exists fails, so of two jobs only one goes on to make the
        # release; the other waits for it and puts its files in
        made = gh("api", "-X", "POST", "repos/%s/git/refs" % REPO, "-f", "ref=refs/tags/" + tag, "-f", "sha=" + SHA,
                  check=False).returncode == 0
        # a tag pushed by hand starts the build itself: there the release is still to be made (two
        # jobs both making one are merged below)
        made = made or os.environ.get("GITHUB_REF") == "refs/tags/" + tag
        if made:
            tmp = tempfile.mkdtemp()
            carried = []
            prev = gh("release", "view", "-R", REPO, "--json", "tagName,assets", check=False)
            if prev.returncode == 0 and not TEST:
                p = json.loads(prev.stdout)
                for a in p["assets"]:
                    if a["name"] not in names and a["name"] in KNOWN:
                        gh("release", "download", p["tagName"], "-R", REPO, "-p", a["name"], "-D", tmp)
                carried = glob.glob(os.path.join(tmp, "*"))
            nf = os.path.join(tmp, "notes.md")
            with open(nf, "w", encoding="utf-8") as f:
                f.write(notes(v))
            gh("release", "create", tag, "-R", REPO, "--verify-tag", "--title", title, "--notes-file", nf,
               *(["--prerelease", "--latest=false"] if TEST else ["--latest"]), *carried, *MINE)
            print(f"{tag}: released{'' if TEST else ', Latest'} ({', '.join(sorted(names))}; carried over: {len(carried)})")
            # a test version replaces the earlier tests; a final release clears every test away
            prune_tests(tag)
            gh("release", "delete", "test-build", "--cleanup-tag", "--yes", "-R", REPO, check=False)
            merge_duplicates(tag)
            tidy(tag)
            return
        print("the tag was made by another job: waiting for its release")
        for _ in range(60):
            if releases_of(tag):
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
    merge_duplicates(tag)
    tidy(tag)
    if not TEST:
        gh("release", "edit", tag, "-R", REPO, "--latest")
    print(f"{tag}: {', '.join(os.path.basename(m) for m in MINE)} in")


if __name__ == "__main__":
    main()
