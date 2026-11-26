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
     # renamed "X6100 Link" from 0.2.4 on: x6100-link-0.2.5-sdcard.img.xz (before: x6100-iu1wxy-0.2.3-sdcard.img)
     "feeds": [("IU1WXY/X6100-IU1WXY", r"^x6100-(iu1wxy|link)-[\d.]+-sdcard\.img(\.xz)?$")],
     "about": "IU1WXY (X6100 Link): oprogramowanie zamknięte, na warunkach autora (LICENSE w jego repo)",
     "no_logo": True},
    {"id": "r1cbu", "name": "R1CBU",
     "feeds": [("gdyuldin/x6100_gui", r"^sdcard.*\.img\.zip$")],
     "about": "klasyczne oprogramowanie R1CBU (gdyuldin)",
     "logo": "gdyuldin/AetherX6100Buildroot/HEAD/br2_external/board/X6100/linux/logo.png"},
]


class CatalogError(Exception):
    pass


# A user's own GitHub repository (an advanced setting): any card image in its releases, the X6100's
# before any other (an X6200 image is never taken; the app also tells an installer image apart)
ANY_IMAGE = r"\.img(\.zip|\.xz)?$"
MAX_OWN = 10
_REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


def _rank(name):
    n = name.lower()
    return (0 if "x6100" in n else 1, 0 if "sdcard" in n else 1)


def parse_repo(text):
    """"owner/repo" from what the user typed (owner/repo, or a github.com address of it or of a page
    in it); None when it is not one"""
    s = (text or "").strip()
    s = re.sub(r"^(?:https?://)?(?:www\.)?github\.com/", "", s, flags=re.I)
    parts = [p for p in s.split("/") if p]
    if len(parts) < 2:
        return None
    repo = "%s/%s" % (parts[0], re.sub(r"\.git$", "", parts[1]))
    return repo if _REPO.match(repo) and parts[1].strip(".") else None


def own_repos():
    from .i18n import setting
    v = setting("own_repos") or []
    return [r for r in v if isinstance(r, str) and parse_repo(r) == r][:MAX_OWN]


def add_own_repo(text):
    """Kept in the settings; returns "owner/repo", or None when the text is not a repository"""
    from .i18n import set_setting
    repo = parse_repo(text)
    if repo is None:
        return None
    have = own_repos()
    if repo.lower() not in [r.lower() for r in have]:
        set_setting("own_repos", (have + [repo])[-MAX_OWN:])
    return repo


def remove_own_repo(repo):
    from .i18n import set_setting
    set_setting("own_repos", [r for r in own_repos() if r.lower() != repo.lower()])


def own_source(repo):
    # named owner/repo: a fork called like a known project (x6100_gui...) is not taken for that project
    return {"id": "gh-" + re.sub(r"[^\w.-]", "_", repo.lower().replace("/", "--")), "name": repo,
            "feeds": [(repo, None)], "about": "github.com/" + repo, "own": True, "repo": repo}


def own_sources():
    return [own_source(r) for r in own_repos()]


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


# GitHub answers 60 questions an hour per address without an account (a release list is one; the
# systems list asks 7). So each answer is kept on the computer with its ETag: for FRESH seconds it is
# used as it is, after that asked again "if changed" (an unchanged answer costs nothing of the
# limit), and when GitHub refuses, the last answer serves, with its time. Kept apart from the
# fetched systems (those go when the app closes); a list of versions is small and checked anew.
FRESH = 30 * 60
last_from = {}          # url -> the time of the kept answer used instead of a fresh one (for the window)


def _store():
    from .i18n import _config_file
    return os.path.join(os.path.dirname(_config_file()), "github-cache.json")


def _load_store():
    try:
        with open(_store()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_store(data):
    path = _store()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w") as f:
            json.dump(data, f)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def token():
    """A GitHub token of the user's (settings, or GITHUB_TOKEN): 5000 questions an hour instead of 60"""
    from .i18n import setting
    return (setting("github_token") or os.environ.get("GITHUB_TOKEN") or "").strip()


def _get(url, timeout=20, now=None):
    import time as _time
    now = _time.time() if now is None else now
    store = _load_store()
    kept = store.get(url)
    last_from.pop(url, None)
    if kept and now - kept["at"] < FRESH:
        return kept["data"]
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if token():
        headers["Authorization"] = "Bearer " + token()
    if kept and kept.get("etag"):
        headers["If-None-Match"] = kept["etag"]
    req = urllib.request.Request(url, headers=headers)
    try:
        with _open(req, timeout) as r:
            data = json.loads(r.read().decode())
            store[url] = {"at": now, "etag": r.headers.get("ETag"), "data": data}
            _save_store(store)
            return data
    except urllib.error.HTTPError as e:
        if e.code == 304 and kept:                       # unchanged: free of the limit
            kept["at"] = now
            _save_store(store)
            return kept["data"]
        if kept:                                         # refused (the limit) or down: the last answer
            last_from[url] = kept["at"]
            return kept["data"]
        if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
            reset = e.headers.get("X-RateLimit-Reset")
            mins = max(1, int((int(reset) - now) // 60) + 1) if reset and reset.isdigit() else None
            raise CatalogError(t("GitHub chwilowo ogranicza zapytania (60 na godzinę bez konta). Spróbuj za {m} min "
                                 "albo wpisz token GitHub w oknie pobierania.", m=mins or "kilka"))
        if e.code == 401:
            raise CatalogError(t("GitHub nie przyjął tokenu: sprawdź go w oknie pobierania."))
        raise CatalogError(f"GitHub: {e.code} {e.reason}")
    except (urllib.error.URLError, OSError) as e:
        if kept:
            last_from[url] = kept["at"]
            return kept["data"]
        raise CatalogError(t("brak połączenia z GitHubem: {e}", e=getattr(e, "reason", e)))


def kept_since(source):
    """When a source's list shown is the kept one (GitHub refused or did not answer): its time, or None"""
    times = [last_from[API.format(repo=repo, n=15)] for repo, _a in source["feeds"]
             if API.format(repo=repo, n=15) in last_from]
    return min(times) if times else None


def releases(source, n=15, fetch=_get):
    """[{"tag", "date", "prerelease", "asset", "size", "url", "sha256", "repo"}] newest first,
    from every repository the source publishes in"""
    out = []
    for repo, asset in source["feeds"]:
        data = fetch(API.format(repo=repo, n=n))
        if not isinstance(data, list):
            raise CatalogError(t("nieoczekiwana odpowiedź GitHuba"))
        pat = re.compile(asset or ANY_IMAGE, re.I)
        for r in data:
            if r.get("draft"):
                continue
            assets = r.get("assets", [])
            if asset is None:           # a repository of the user's: its X6100 card image, whatever its name
                assets = sorted((a for a in assets if "x6200" not in a.get("name", "").lower()),
                                key=lambda a: _rank(a.get("name", "")))
            for a in assets:
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


def version_of(rel):
    """A release's version as said in the app: v0.3.12"""
    return rel["tag"] if rel["tag"].startswith("v") else "v" + rel["tag"]


def label(source, rel):
    return "%s %s" % (source["name"], rel["tag"] if rel["tag"].startswith("v") else "v" + rel["tag"])


def _safe_name(name):
    """A tag's or a file's name from a release as one plain name in a folder (a repository of the
    user's own can name them anyhow: no slashes, no .. )"""
    s = re.sub(r"[^\w.-]", "_", os.path.basename(str(name))).lstrip(".")
    return s or "file"


def download(source, rel, cache_dir, progress=None):
    """The release's image in cache_dir/downloads (kept: a second use does not fetch it again)"""
    d = os.path.join(cache_dir, "downloads", source["id"], _safe_name(rel["tag"]))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, _safe_name(rel["asset"]))
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
    for src in own_sources():
        if name.lower() == src["name"].lower() or name.lower().startswith(src["name"].lower() + " "):
            return src
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
