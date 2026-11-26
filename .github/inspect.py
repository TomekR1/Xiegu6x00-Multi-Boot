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
                        print("  ---- p%d/%s:\n%s" % (p[0], n, "\n".join("    | " + l for l in text.splitlines()[:400])))
            except Exception as e:
                print("  p%d %s (not FAT: %s)" % (p[0], kind, type(e).__name__))
                if kind == "ext":
                    ext_look(f, raw, p)


def ext_look(f, raw, p):
    """An ext partition: its /boot, and the places that write a boot loader to the card (dd to the
    card at 8 KiB, u-boot files, the loader's marker)"""
    import re
    import subprocess
    from x6100mb.image import SECTOR
    part = raw + ".p%d" % p[0]
    with open(part, "wb") as out:
        f.seek(p[2] * SECTOR)
        left = p[3] * SECTOR
        while left > 0:
            d = f.read(min(left, 8 << 20))
            if not d:
                break
            out.write(d)
            left -= len(d)
    for cmd in ("ls -l /boot", "ls -l /usr/share/x6100/uboot", "ls -l /usr/libexec", "cat /usr/libexec/x6100-finddisk",
                "cat /usr/share/x6100/uboot/meta"):
        r = subprocess.run(["debugfs", "-R", cmd, part], capture_output=True, text=True)
        if r.stdout.strip():
            print("  p%d %s:\n%s" % (p[0], cmd, "\n".join("    " + l for l in r.stdout.splitlines()[:40])))
    r = subprocess.run(["strings", "-n", "8", part], capture_output=True, text=True)
    pat = re.compile(r"(seek=8\b|seek=16\b|bs=1024 seek|u-boot-sunxi|x6100ub|mmcblk0 .*seek|of=/dev/mmcblk0\b|"
                     r"boot ?loader|bootloader|flash_uboot|uboot\.bin|u-boot\.bin|spl)", re.I)
    hits = sorted({l.strip()[:200] for l in r.stdout.splitlines() if pat.search(l)})
    print("  p%d strings about writing a boot loader: %d" % (p[0], len(hits)))
    # the files behind it, whole: the boot loader's updater and what starts it
    import shutil
    import tempfile
    root = tempfile.mkdtemp()
    subprocess.run(["debugfs", "-R", "rdump / " + root, part], capture_output=True)
    r = subprocess.run(["grep", "-rlI", "-e", "sigstamp", "-e", "bootscr", "-e", "x6100-sysupdate", root + "/usr/libexec", root + "/etc/init.d"],
                       capture_output=True, text=True)
    for fn in sorted(set(r.stdout.split()))[:12]:
        try:
            text = open(fn, errors="replace").read()
        except OSError:
            continue
        print("  ==== p%d file %s (%d lines)" % (p[0], fn[len(root):], text.count("\n")))
        lines = text.splitlines()
        whole = len(lines) < 120 or "sigstamp" in fn or "S00" in fn
        keep = range(len(lines)) if whole else [i for i, l in enumerate(lines) if re.search(r"boot\.scr|mmcblk0p1|ab\.env|/boot|fatwrite|mount|bootscr", l)]
        shown = sorted({j for i in keep for j in range(max(0, i - 3), min(len(lines), i + 4))})
        print("\n".join("    %4d: %s" % (j + 1, lines[j]) for j in shown[:220]))
    shutil.rmtree(root, ignore_errors=True)
    os.remove(part)


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


def deep(order):
    """A whole card with IU1WXY 0.2.4+ written out and read back: what the radio will find on it"""
    import io
    import re
    from x6100mb.fat import FatReader
    from x6100mb.image import SECTOR, parse_script_image, read_mbr
    from x6100mb.writer import write_image_file
    ents = [{"kind": "sd", "name": systems[k].name, "base": systems[k].name, "sys": systems[k]} for k in order]
    name_entries(ents)
    out = os.path.join(cache_dir(), "deep.img")
    try:
        write_image_file(compose(ents, default=0, data_mb=64, data_mode="separate"), out)
        with open(out, "rb") as f:
            parts = read_mbr(f)
            print("  card partitions:", parts)
            boot = FatReader(f, parts[0][2] * SECTOR)
            print("  BOOT:", [e[0] for e in boot.listdir()], "MENU:", [e[0] for e in boot.listdir(boot.find("MENU")[2])])
            menu = parse_script_image(boot.read_file("MENU/MENU.SCR"))
            own = parse_script_image(boot.read_file("boot.scr"))
            print("  boot.scr is the menu:", "bm_boot" in own, "| IU1WXY's:", "PARTUUID=58363130" in own)
            for i, e in enumerate(ents):
                t = boot.read_file(e["dir"] + "/MBR.BIN")
                print("  %s %s: signature %s, table %s" % (e["dir"], e["name"], t[440:444].hex(),
                                                        read_mbr(io.BytesIO(t))))
                m = re.search(r"setenv bm_boot%d '([^']*)'" % (i + 1), menu)
                print("    bm_boot%d: %s" % (i + 1, m.group(1) if m else None))
        os.remove(out)
    except Exception:
        traceback.print_exc()


print("=" * 70, "\ncards", flush=True)
for sid in [k for k in systems if getattr(systems[k], "ab_v2", False)]:
    print("deep", sid, flush=True)
    deep(["openx6x00", sid])
    deep([sid, "openx6x00"])
for sid in [k for k in systems if k != "openx6x00"]:
    card([sid])
    card([sid, "openx6x00"])
    card(["openx6x00", sid])
    card([sid, "openx6x00"], ("doom",))
    card(["openx6x00", sid], ("nes",))
