"""Diagnostics for systems users report trouble with: each newest release fetched as the app does,
the archive's insides listed, the image read, and cards composed with it first, later, and with the
extras. Prints everything; run by the Build workflow's "inspect" input."""
import os
import sys
import traceback
import zipfile

sys.path.insert(0, os.getcwd())
from x6100mb import catalog                                   # noqa: E402
from x6100mb.compose import compose, kernel_donor, name_entries  # noqa: E402
from x6100mb.image import SourceSystem, cache_dir, open_source   # noqa: E402

def dump(raw):
    """The image's partitions, each FAT's files and every boot script, whatever the app makes of it"""
    from x6100mb.fat import FatReader
    from x6100mb.image import SECTOR, parse_script_image, read_mbr
    with open(raw, "rb") as f:
        parts = read_mbr(f)
        print("  partitions (n, type, start, sectors, boot):", parts)
        for p in parts:
            f.seek(p[2] * SECTOR + 1024)
            sb = f.read(1024)
            kind = "ext" if sb[56:58] == b"\x53\xef" else ""
            try:
                fat = FatReader(f, p[2] * SECTOR)
                names = [e[0] for e in fat.listdir()]
                print("  p%d FAT: %s" % (p[0], names))
                for n in names:
                    if n.lower().endswith((".scr", ".cmd", ".env", ".txt", ".bak")):
                        data = fat.read_file(n)
                        text = parse_script_image(data) if n.lower().endswith(".scr") else data.decode(errors="replace")
                        print("  ---- p%d/%s:\n%s" % (p[0], n, "\n".join("    | " + l for l in text.splitlines()[:80])))
            except Exception as e:
                print("  p%d %s (not FAT: %s)" % (p[0], kind, type(e).__name__))


specs = sys.argv[1:]
systems = {}
for spec in specs:
    sid = spec.split("@")[0].lower()
    src = next(x for x in catalog.SOURCES if x["id"] == sid)
    print("=" * 70, "\n%s" % spec, flush=True)
    try:
        rels = catalog.releases(src)
        for r in rels[:5]:
            print("  release %-14s %s %s %5d MB%s%s" % (r["tag"], r["date"], r["asset"], r["size"] >> 20,
                  " (test)" if r["prerelease"] else "", " (name guessed)" if r.get("guessed") else ""))
        rel = next((r for r in rels if not r["prerelease"]), rels[0])
        path = catalog.download(src, rel, cache_dir())
        print("  fetched", os.path.basename(path), os.path.getsize(path) >> 20, "MB")
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for i in z.infolist():
                    with z.open(i) as f:
                        head = f.read(512) if not i.is_dir() else b""
                    print("    zip: %-60s %8d MB  partition table: %s" % (i.filename, i.file_size >> 20,
                          head[510:512] == b"\x55\xaa"))
        raw = open_source(path, cache_dir())
        print("  image used:", os.path.basename(raw))
        dump(raw)
        s = SourceSystem(path, raw)
        print("  partitions:", s.parts)
        print("  boot files:", getattr(s, "boot_files", None))
        print("  A/B:", getattr(s, "is_ab", False), "| kernel on BOOT:", "kernel" in (s.files or {}))
        print("  summary:", s.summary(), "| warnings:", s.warnings)
        print("  boot script:\n" + "\n".join("    | " + l for l in s.script.splitlines()[:60]))
        s.name, s.version = src["name"], catalog.version_of(rel)
        systems[sid] = s
    except Exception:
        traceback.print_exc()

if "openx6x00" not in systems:
    try:
        src = catalog.SOURCES[0]
        rel = next(r for r in catalog.releases(src) if not r["prerelease"])
        p = catalog.download(src, rel, cache_dir())
        systems["openx6x00"] = SourceSystem(p, open_source(p, cache_dir()))
        systems["openx6x00"].name = "OpenX6X00"
    except Exception:
        traceback.print_exc()


def card(order, extras=()):
    ents = [{"kind": "sd", "name": systems[k].name, "base": systems[k].name, "sys": systems[k]} for k in order]
    ents += [{"kind": x, "name": x.upper()} for x in extras]
    name_entries(ents)
    label = " + ".join([e["name"] for e in ents])
    try:
        donor = kernel_donor(ents)
        if extras:
            from x6100mb.compose import resolve_extras
            import lzma
            fake = os.path.join(cache_dir(), "fake-extra.ext4.xz")
            with lzma.open(fake, "wb") as f:
                f.write(b"\0" * (2 << 20))
            ents = resolve_extras(ents, {x: fake for x in extras})
        for mode in ("separate", "shared"):
            plan = compose(ents, default=0, data_mb=64, data_mode=mode)
            print("  OK   %-60s %-8s %s" % (label, mode, [(x["key"], x["partition"]) for x in plan.info["entries"]]))
        if extras:
            print("       kernel for the extras from:", donor.name if donor else None)
    except Exception as e:
        print("  FAIL %-60s %s: %s" % (label, type(e).__name__, e))


print("=" * 70, "\ncards", flush=True)
for sid in [k for k in systems if k != "openx6x00"]:
    card([sid])
    card([sid, "openx6x00"])
    card(["openx6x00", sid])
    card([sid, "openx6x00"], ("doom",))
    card(["openx6x00", sid], ("nes",))
