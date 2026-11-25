"""x6100-multiboot

    python -m x6100mb                      the window
    python -m x6100mb info IMAGE...        what each image holds
    python -m x6100mb build -o OUT.img [--xiegu] [--default N] [--timeout S] [--data-mb MB] IMAGE...
        IMAGE: a file, or a release to fetch: openx6x00@latest, openx6100@v1.2.0, r1cbu@latest
    python -m x6100mb catalog              the systems it can fetch, newest releases
    python -m x6100mb list                 the removable cards seen
    python -m x6100mb write-plan PLAN DEVICE PROGRESS   (used by the window, with admin rights)
"""
import argparse
import os
import sys


def _fetch(spec):
    """'openx6x00@latest' or 'openx6100@v1.2.0': that release's image, fetched; (path, name)"""
    from . import catalog
    from .image import cache_dir
    sid, _, ver = spec.partition("@")
    src = next((x for x in catalog.SOURCES if x["id"] == sid.lower()), None)
    if src is None:
        raise SystemExit(f"{spec}: unknown system (known: {', '.join(x['id'] for x in catalog.SOURCES)})")
    rels = catalog.releases(src)
    if ver in ("", "latest"):
        rel = next((r for r in rels if not r["prerelease"]), rels[0] if rels else None)
    else:
        rel = next((r for r in rels if r["tag"].lstrip("v") == ver.lstrip("v")), None)
    if rel is None:
        raise SystemExit(f"{spec}: no such release with an X6100 image")
    print(f"fetching {catalog.label(src, rel)}: {rel['url']}", file=sys.stderr)
    return catalog.download(src, rel, cache_dir()), (src["name"], catalog.version_of(rel))


def _load(paths):
    from .image import SourceSystem, cache_dir, open_source
    out = []
    for p in paths:
        name = ver = None
        if "@" in p and not os.path.exists(p):
            p, (name, ver) = _fetch(p)
        raw = open_source(p, cache_dir())
        s = SourceSystem(p, raw)
        if name:
            s.name, s.version = name, ver
        out.append(s)
    return out


def cli(argv):
    if argv and argv[0] == "card-data":
        from .cardata import main_card_data
        return main_card_data(argv[1:])
    if argv and argv[0] in ("access", "--access"):
        # the accessible mode (screen readers): a page of plain controls in a window of its own
        from .access import main as access_main
        return access_main()
    if argv and argv[0] == "write-plan":
        from .writer import main_write_plan
        return main_write_plan(argv[1:])
    ap = argparse.ArgumentParser(prog="x6100mb", description="Xiegu Multi Patcher: multi-boot SD cards for the "
                                 "Xiegu X6100", epilog="Aplikacja: SQ6RT, https://www.qrz.com/db/SQ6RT")
    sub = ap.add_subparsers(dest="cmd")
    i = sub.add_parser("info")
    i.add_argument("images", nargs="+")
    b = sub.add_parser("build")
    b.add_argument("-o", "--output", required=True)
    b.add_argument("--xiegu", action="store_true", help="an entry for Xiegu's system on the eMMC (last)")
    b.add_argument("--doom", action="store_true", help="the Doom easter egg (with the first system's kernel)")
    b.add_argument("--doom-rootfs", help="its root filesystem (.ext4.xz; default: the one in the app)")
    b.add_argument("--talk", action="store_true",
                   help="the talking boot menu for blind operators (alpha; Jim Ruby's talkmenu, voice RHVoice Lyubov)")
    b.add_argument("--talk-rootfs", help="its root filesystem (.ext4.xz; default: the one in the app)")
    b.add_argument("--talk-voice", help="its voice (talk-voice.zip; default: the one in the app)")
    b.add_argument("--nes", action="store_true", help="the NES emulator (with the first system's kernel)")
    b.add_argument("--nes-rootfs", help="its root filesystem (.ext4.xz; default: the one in the app)")
    b.add_argument("--nes-game", action="append", default=[], metavar="FILE",
                   help="a NES game of your own (.nes/.fds/.unf/.nsf, a .zip of them, or a folder of them) for the card; repeatable")
    b.add_argument("--default", type=int, default=1, help="default entry, 1 = F1")
    b.add_argument("--timeout", type=int, default=5, help="seconds before the default starts (0-15)")
    b.add_argument("--wait", action="store_true", help="no default: the menu waits for a key")
    b.add_argument("--data", choices=["shared", "separate"], default="shared",
                   help="one DATA partition for all systems, or one per system")
    b.add_argument("--logo", action="append", default=[], metavar="N=FILE",
                   help="a picture for entry N (1 = F1) in the graphic menu; repeatable")
    b.add_argument("--no-graphics", action="store_true", help="text menu only")
    b.add_argument("--data-mb", type=int, default=1024)
    b.add_argument("--names", help="entry names, comma-separated")
    b.add_argument("--uboot", help="U-Boot: a u-boot-sunxi-with-spl.bin file, or 'image' for the first image's "
                   "(default: the bundled menu U-Boot when there is one)")
    b.add_argument("--script-only", action="store_true", help="print the menu script, write nothing")
    b.add_argument("images", nargs="+")
    sub.add_parser("list")
    sub.add_parser("catalog", help="the systems the app can fetch, with their newest releases")
    sub.add_parser("access", help="the accessible mode for screen readers (NVDA, JAWS, Narrator, VoiceOver)")
    a = ap.parse_args(argv)

    if a.cmd == "info":
        for s in _load(a.images):
            print(f"{s.name}\n  {s.summary()}\n  bootargs: {s.bootargs}")
            for w in s.warnings:
                print("  warning:", w)
        return 0
    if a.cmd == "catalog":
        from . import catalog
        for src in catalog.SOURCES:
            print(f"{src['id']:10s} {src['name']} ({', '.join(r for r, _ in src['feeds'])})")
            try:
                for r in catalog.releases(src)[:5]:
                    print(f"    {r['tag']:12s} {r['date']}  {r['size'] >> 20} MB{'  (test)' if r['prerelease'] else ''}")
            except catalog.CatalogError as e:
                print(f"    error: {e}")
        return 0
    if a.cmd == "list":
        from .devices import list_cards
        for c in list_cards():
            print(f"{c['path']}\t{c['size'] / 1e9:.1f} GB\t{c['name']}\t{c['bus']}")
        return 0
    if a.cmd == "build":
        from .compose import compose
        from .writer import Progress, write_image_file
        systems = _load(a.images)
        names = a.names.split(",") if a.names else [s.name for s in systems]
        entries = [{"kind": "sd", "name": n, "sys": s, "version": getattr(s, "version", None),
                    "base": s.name if getattr(s, "version", None) else None} for n, s in zip(names, systems)]
        from .compose import name_entries
        name_entries(entries)                     # no version numbers, unless two would share a name
        if a.doom:
            from .compose import DOOM_NAME
            entries.append({"kind": "doom", "name": DOOM_NAME})
        if a.nes:
            from .compose import NES_NAME
            entries.append({"kind": "nes", "name": NES_NAME, "games": a.nes_game})
        if a.xiegu:
            entries.append({"kind": "xiegu", "name": "Xiegu (eMMC)"})
        if a.talk:
            from .compose import TALK_NAME
            entries.append({"kind": "talk", "name": TALK_NAME})
        for spec in a.logo:
            n, _, path = spec.partition("=")
            if not n.isdigit() or not 1 <= int(n) <= len(entries) or not path:
                raise SystemExit(f"--logo {spec}: expected N=FILE with N from 1 to {len(entries)}")
            entries[int(n) - 1]["logo"] = path
        ub = None
        if a.uboot == "image":
            ub = systems[0]
        elif a.uboot:
            from .image import UBoot
            ub = UBoot(a.uboot)
        from .compose import resolve_extras
        entries = resolve_extras(entries, {"doom": a.doom_rootfs, "nes": a.nes_rootfs, "talk": a.talk_rootfs})
        plan = compose(entries, default=a.default - 1, timeout_s=a.timeout, data_mb=a.data_mb, uboot_from=ub,
                       data_mode=a.data, graphics=not a.no_graphics, wait=a.wait,
                       talk_voice=a.talk_voice)
        if a.script_only:
            print(plan.script)
            return 0
        last = [0]

        def show(phase, done, total, msg=""):
            pct = done * 100 // max(total, 1)
            if pct != last[0] or phase == "done":
                last[0] = pct
                print(f"\r{phase:7s} {pct:3d}%", end="", flush=True)

        write_image_file(plan, a.output, Progress(show))
        print(f"\n{a.output}: {plan.size // 2**20} MB, {plan.info}")
        return 0
    # A screen reader on (Windows: NVDA, JAWS, Narrator; macOS: VoiceOver): the accessible mode at once,
    # the drawn window being next to silent for it
    from .access import screen_reader_running
    if not argv and screen_reader_running():
        from .access import main as access_main
        return access_main()
    from .gui import main
    return main()


def main():
    try:
        return cli(sys.argv[1:])
    except KeyboardInterrupt:
        return 130
    except Exception as e:          # a message, not a traceback
        if "--debug" in sys.argv:
            raise
        print(f"błąd: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
