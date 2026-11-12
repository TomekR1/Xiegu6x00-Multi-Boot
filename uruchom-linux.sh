#!/bin/sh
# X6100 Multiboot: start okna. Potrzebne: python3, python3-tk; do zapisu na kartę pkexec (polkit).
cd "$(dirname "$0")" && exec python3 -m x6100mb "$@"
