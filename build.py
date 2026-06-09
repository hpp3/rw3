"""One-shot build: extract data + copy icons into site/.
Usage:  .venv/Scripts/python.exe build.py
Reads ONLY from the game install dir; writes only into ./site/."""
import runpy, os
HERE = os.path.dirname(os.path.abspath(__file__))
print("== extracting data ==")
runpy.run_path(os.path.join(HERE, "extract.py"), run_name="__main__")
print("== copying icons ==")
runpy.run_path(os.path.join(HERE, "copy_icons.py"), run_name="__main__")
print("== animating monster sprites (idle loop) ==")
runpy.run_path(os.path.join(HERE, "animate_monsters.py"), run_name="__main__")
print("== generating favicon ==")
runpy.run_path(os.path.join(HERE, "make_favicon.py"), run_name="__main__")
print("== done. serve with:  python -m http.server --directory site ==")
