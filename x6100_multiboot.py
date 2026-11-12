"""Start programu (także punkt wejścia dla PyInstaller): python x6100_multiboot.py"""
import sys

from x6100mb.__main__ import cli

if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
