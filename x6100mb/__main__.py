"""x6100-multiboot

    python -m x6100mb                      the window
    python -m x6100mb info IMAGE...        what each image holds
    python -m x6100mb build -o OUT.img [--xiegu] [--default N] [--timeout S] [--data-mb MB] IMAGE...
    python -m x6100mb list                 the removable cards seen
    python -m x6100mb write-plan PLAN DEVICE PROGRESS   (used by the window, with admin rights)
"""
import argparse
import sys


def _load(paths):
    from .image import SourceSystem, cache_dir, open_source
    out = []
    for p in paths:
        raw = open_source(p, cache_dir())
        out.append(SourceSystem(p, raw))
    return out


def cli(argv):
    if argv and argv[0] == "write-plan":
        from .writer import main_write_plan
        return main_write_plan(argv[1:])
    ap = argparse.ArgumentParser(prog="x6100mb", description="Multi-boot SD cards for the Xiegu X6100")
    sub = ap.add_subparsers(dest="cmd")
    i = sub.add_parser("info")
    i.add_argument("images", nargs="+")
    b = sub.add_parser("build")
    b.add_argument("-o", "--output", required=True)
    b.add_argument("--xiegu", action="store_true", help="an entry for Xiegu's system on the eMMC (last)")
    b.add_argument("--default", type=int, default=1, help="default entry, 1 = F1")
    b.add_argument("--timeout", type=float, default=5)
    b.add_argument("--data-mb", type=int, default=1024)
    b.add_argument("--names", help="entry names, comma-separated")
    b.add_argument("--script-only", action="store_true", help="print the menu script, write nothing")
    b.add_argument("images", nargs="+")
    sub.add_parser("list")
    a = ap.parse_args(argv)

    if a.cmd == "info":
        for s in _load(a.images):
            print(f"{s.name}\n  {s.summary()}\n  bootargs: {s.bootargs}")
            for w in s.warnings:
                print("  warning:", w)
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
        entries = [{"kind": "sd", "name": n, "sys": s} for n, s in zip(names, systems)]
        if a.xiegu:
            entries.append({"kind": "xiegu", "name": "Xiegu (eMMC)"})
        plan = compose(entries, default=a.default - 1, timeout_s=a.timeout, data_mb=a.data_mb)
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
