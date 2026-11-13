"""Systems the app can fetch by itself: their releases on GitHub, newest first.

Each source is a public GitHub repository whose releases carry an X6100 SD card image. The
list of versions comes from GitHub's API (no account needed; GitHub allows some 60 such
requests an hour per address), the image from the release's download link, checked against
the size and, where GitHub gives one, the SHA-256 it publishes. A source may publish in
more than one repository (CX8ANM moved its newer releases): their lists are merged.
"""
import hashlib
import json
import os
from .i18n import t
import re
import urllib.error
import urllib.request

UA = "xiegu-multi-patcher"
API = "https://api.github.com/repos/{repo}/releases?per_page={n}"

SOURCES = [
    {"id": "openx6x00", "name": "OpenX6X00",
     "feeds": [("Guru-RF/OpenX6X00", r"^OpenX6X00-x6100-v[\d.]+-sdcard\.img\.zip$")],
     "about": "Guru-RF: nowe GUI, aktualizacje przez sieć, Wavelog, FT8/JS8",
     "logo": "Guru-RF/OpenX6X00/HEAD/boot/logo.png", "crop": (0.0, 0.0, 1.0, 0.42)},
    {"id": "openx6100", "name": "OpenX6100",
     "feeds": [("OpenX6100/x6100_gui", r"^sdcard.*\.img\.zip$")],
     "about": "następca R1CBU, rozwijany przez społeczność OpenX6100",
     "logo": "OpenX6100/AetherX6100Buildroot/HEAD/br2_external/board/X6100/linux/logo.png"},
    {"id": "cx8anm", "name": "CX8ANM",
     "feeds": [("condoruy/OpenX6X00-CX8ANM", r"^OpenX6X00-CX8ANM-x6100-v[\d.]+-sdcard\.img\.zip$"),
               ("condoruy/X6100-CX8ANM", r"^Xiegu_X6100-CX8ANM_v[\d.]+\.img\.zip$")],
     "about": "CX8ANM: wydania 1.1.x (na bazie OpenX6X00) i wcześniejsze 1.0.x",
     "logo": "condoruy/X6100-CX8ANM/HEAD/boot/logo.png", "crop": (0.0, 0.0, 1.0, 0.70)},
    {"id": "1ko125", "name": "1KO125",
     "feeds": [("TheMurusTeam/x6100_gui", r"^sdcard-1KO125-[\w.\-]+\.img\.zip$")],
     "about": "1KO125 (na bazie OpenX6100): WEFAX, SSTV, NAVTEX, DSC, FT8 CB; na razie wersje testowe"},
    {"id": "iu1wxy", "name": "IU1WXY",
     "feeds": [("IU1WXY/X6100-IU1WXY", r"^x6100-iu1wxy-[\d.]+-sdcard\.img$")],
     "about": "IU1WXY (X6100 Link): oprogramowanie zamknięte, na warunkach autora (LICENSE w jego repo)",
     "no_logo": True},
    {"id": "r1cbu", "name": "R1CBU",
     "feeds": [("gdyuldin/x6100_gui", r"^sdcard.*\.img\.zip$")],
     "about": "klasyczne oprogramowanie R1CBU (gdyuldin)",
     "logo": "gdyuldin/AetherX6100Buildroot/HEAD/br2_external/board/X6100/linux/logo.png"},
]


class CatalogError(Exception):
    pass


_ctx = None


def _ssl():
    """The system's certificates plus certifi's: a Python packed into an app on macOS sees none of
    the system's (CERTIFICATE_VERIFY_FAILED), and certifi alone would miss a company's own CA"""
    global _ctx
    if _ctx is None:
        import ssl
        _ctx = ssl.create_default_context()
        try:
            import certifi
            _ctx.load_verify_locations(certifi.where())
        except Exception:
            pass
    return _ctx


def _open(req, timeout):
    if isinstance(req, str) and req.startswith("file:"):
        return urllib.request.urlopen(req, timeout=timeout)
    if isinstance(req, urllib.request.Request) and req.full_url.startswith("file:"):
        return urllib.request.urlopen(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl())


def _get(url, timeout=20):
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):          # in CI: a higher request limit
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(url, headers=headers)
    try:
        with _open(req, timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0":
            raise CatalogError(t("GitHub chwilowo ogranicza zapytania (limit na godzinę). Spróbuj za kilka minut."))
        raise CatalogError(f"GitHub: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise CatalogError(t("brak połączenia z GitHubem: {e}", e=e.reason))


def releases(source, n=15, fetch=_get):
    """[{"tag", "date", "prerelease", "asset", "size", "url", "sha256", "repo"}] newest first,
    from every repository the source publishes in"""
    out = []
    for repo, asset in source["feeds"]:
        data = fetch(API.format(repo=repo, n=n))
        if not isinstance(data, list):
            raise CatalogError(t("nieoczekiwana odpowiedź GitHuba"))
        pat = re.compile(asset, re.I)
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
                    "repo": repo,
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
        with _open(req, 60) as r, open(tmp, "wb") as f:
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
        raise CatalogError(t("pobieranie przerwane: {e}", e=getattr(e, "reason", e)))
    except Exception as e:      # the connection dropped or timed out half way, IncompleteRead
        raise CatalogError(t("pobieranie przerwane: {e}", e=e))
    if rel["size"] and os.path.getsize(tmp) != rel["size"]:
        os.remove(tmp)
        raise CatalogError(t("pobrany plik ma inny rozmiar niż na GitHubie (przerwane pobieranie?)"))
    if rel["sha256"] and h.hexdigest() != rel["sha256"]:
        os.remove(tmp)
        raise CatalogError(t("suma kontrolna pobranego pliku się nie zgadza"))
    os.replace(tmp, path)
    return path


RAW = "https://raw.githubusercontent.com/"


def source_for(name):
    """The catalog source a system's name belongs to (CX8ANM before OpenX6X00: its 1.1.x is named
    OpenX6X00-CX8ANM; 1KO125 and IU1WXY before the trees they come from), or None"""
    n = name.lower().replace(" ", "").replace("_", "").replace("-", "")
    for sid in ("1ko125", "iu1wxy", "cx8anm", "openx6100", "openx6x00", "r1cbu"):
        if sid in n:
            return next(x for x in SOURCES if x["id"] == sid)
    if "x6100gui" in n or "aether" in n:
        return next(x for x in SOURCES if x["id"] == "r1cbu")
    return None


# Where projects of this family keep their boot logo, tried in each of the source's repositories
# when its own address does not answer (the project moved it, or none was set)
LOGO_PATHS = ["boot/logo.png", "logo.png", "assets/logo.png", "images/logo.png", "docs/logo.png",
              "br2_external/board/X6100/linux/logo.png", "board/X6100/linux/logo.png"]
_missing = set()


def _raw_png(path, timeout):
    if path in _missing:
        return None
    try:
        req = urllib.request.Request(RAW + path, headers={"User-Agent": UA})
        with _open(req, timeout) as r:
            data = r.read(4 << 20)
    except (urllib.error.URLError, OSError, ValueError):
        _missing.add(path)
        return None
    if not data.startswith(b"\x89PNG"):
        _missing.add(path)
        return None
    return data


def logo_candidates(source):
    """The addresses to try for a source's logo, its own first"""
    if not source or source.get("no_logo"):
        return []
    out = [source["logo"]] if source.get("logo") else []
    for repo, _ in source["feeds"]:
        owner = repo.split("/")[0]
        for p in LOGO_PATHS:
            out.append("%s/HEAD/%s" % (repo, p))
        # x6100_gui forks keep the boot logo in their buildroot tree
        for p in LOGO_PATHS[-2:]:
            out.append("%s/AetherX6100Buildroot/HEAD/%s" % (owner, p))
    seen = set()
    return [x for x in out if not (x in seen or seen.add(x))]


def fetch_logo(source, cache_dir, timeout=8, fetch=None):
    """The project's own logo (its boot screen picture, from its repository), cached; None when
    there is none to be had (offline, nothing found, or a project whose terms keep its graphics)"""
    cands = logo_candidates(source)
    if not cands:
        return None
    d = os.path.join(cache_dir, "logos")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, source["id"] + ".png")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    get = fetch or (lambda p: _raw_png(p, timeout))
    for c in cands:
        data = get(c)
        if data:
            with open(path + ".part", "wb") as f:
                f.write(data)
            os.replace(path + ".part", path)
            return path
    return None
