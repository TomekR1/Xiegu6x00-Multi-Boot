@echo off
rem X6100 Multiboot: start okna. Potrzebny Python 3.9+ z python.org (z zaznaczonym "Add to PATH").
cd /d "%~dp0"
python -m x6100mb
if errorlevel 1 pause
