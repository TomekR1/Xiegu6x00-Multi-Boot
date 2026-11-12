"""Systems the app can fetch by itself: their releases on GitHub, newest first.

Each source is a public GitHub repository whose releases carry an X6100 SD card image. The
list of versions comes from GitHub's API (no account needed; GitHub allows some 60 such
requests an hour per address), the image from the release's download link, checked against
the size and, where GitHub gives one, the SHA-256 it publishes.
"""
import hashlib
import json
import os
import re
import urllib.error
import urllib.request

UA = "xiegu-multi-patcher"
API = "https://api.github.com/repos/{repo}/releases?per_page={n}"

SOURCES = [
    {"id": "openx6x00", "name": "OpenX6X00", "repo": "Guru-RF/OpenX6X00",
     "asset": r"^OpenX6X00-x6100-v[\d.]+-sdcard\.img\.zip$",
     "about": "Guru-RF: nowe GUI, aktualizacje przez sieć, Wavelog, FT8/JS8"},
    {"id": "openx6100", "name": "OpenX6100", "repo": "OpenX6100/x6100_gui",
     "asset": r"^sdcard.*\.img\.zip$",
     "about": "następca R1CBU, rozwijany przez społeczność OpenX6100"},
    {"id": "r1cbu", "name": "R1CBU", "repo": "gdyuldin/x6100_gui",
     "asset": r"^sdcard.*\.img\.zip$",
     "about": "klasyczne oprogramowanie R1CBU (gdyuldin)"},
]


class CatalogError(Exception):
    pass


def _get(url, timeout=20):
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):          # in CI: a higher request limit
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0":
            raise CatalogError("GitHub chwilowo ogranicza zapytania (limit na godzinę). Spróbuj za kilka minut.")
        raise CatalogError(f"GitHub: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise CatalogError(f"brak połączenia z GitHubem: {e.reason}")


def releases(source, n=15, fetch=_get):
    """[{"tag", "date", "prerelease", "asset", "size", "url", "sha256"}] newest first"""
    data = fetch(API.format(repo=source["repo"], n=n))
    if not isinstance(data, list):
        raise CatalogError("nieoczekiwana odpowiedź GitHuba")
    pat = re.compile(source["asset"], re.I)
    out = []
    for r in data:
        if r.get("draft"):
            continue
        for a in r.get("assets", []):
            if not pat.search(a.get("name", "")):
                continue
            digest = a.get("digest") or ""
            out.append({
                "tag": r.get("tag_name", "?"),
                "date": (r.get("published_at") or "")[:10],
                "prerelease": bool(r.get("prerelease")),
                "asset": a["name"],
                "size": int(a.get("size") or 0),
                "url": a["browser_download_url"],
                "sha256": digest[7:] if digest.startswith("sha256:") else None,
            })
            break
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def label(source, rel):
    return "%s %s" % (source["name"], rel["tag"] if rel["tag"].startswith("v") else "v" + rel["tag"])


def download(source, rel, cache_dir, progress=None):
    """The release's image in cache_dir/downloads (kept: a second use does not fetch it again)"""
    d = os.path.join(cache_dir, "downloads", source["id"], re.sub(r"[^\w.-]", "_", rel["tag"]))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, rel["asset"])
    if os.path.exists(path) and (not rel["size"] or os.path.getsize(path) == rel["size"]):
        return path
    tmp = path + ".part"
    h = hashlib.sha256()
    req = urllib.request.Request(rel["url"], headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or rel["size"] or 0)
            done = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except urllib.error.URLError as e:
        raise CatalogError(f"pobieranie przerwane: {getattr(e, 'reason', e)}")
    if rel["size"] and os.path.getsize(tmp) != rel["size"]:
        os.remove(tmp)
        raise CatalogError("pobrany plik ma inny rozmiar niż na GitHubie (przerwane pobieranie?)")
    if rel["sha256"] and h.hexdigest() != rel["sha256"]:
        os.remove(tmp)
        raise CatalogError("suma kontrolna pobranego pliku się nie zgadza")
    os.replace(tmp, path)
    return path
