"""One-shot build: extract data + copy icons into site/.
Usage:  .venv/Scripts/python.exe build.py
Reads ONLY from the game install dir; writes only into ./site/."""
import runpy, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
print("== extracting data ==")
runpy.run_path(os.path.join(HERE, "extract.py"), run_name="__main__")
print("== copying icons ==")
runpy.run_path(os.path.join(HERE, "copy_icons.py"), run_name="__main__")
# Monster idle animation is done in pure CSS (background-position) from the full
# spritesheets, so no per-sprite processing here. The favicon is a committed
# static asset (regenerate once with make_favicon.py if the source ever changes).
print("== verifying data.json against the game (tests.py) ==")
if subprocess.run([sys.executable, os.path.join(HERE, "tests.py")]).returncode != 0:
    sys.exit("== BUILD FAILED: data.json does not match the game; see failures above ==")
# Per-entry share pages (site/s/): stdlib only, so this stays runnable anywhere
# data.json is. Their card pictures need a headless browser and are shot by the
# deploy workflow instead (`share.py --cards`); run that by hand to preview them
# locally.
print("== generating share pages ==")
subprocess.run([sys.executable, os.path.join(HERE, "share.py")], check=True)
print("== done. serve with:  python devserver.py ==")
