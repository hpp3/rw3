"""Turn each monster spritesheet in site/icons/units/ into a looping animated
APNG of just its idle animation (the last row of frames).

Sprite format (from the game's RiftWizard3 Anim loader):
  - frames are square: frame_size = (60 if width%60==0 else 16) * (1 + 2*radius)
  - idle animation = the LAST row, all `columns` frames
  - idle advances every 6 game frames at 30 fps  ->  ~5 fps (200 ms/frame)
"""
import os, json
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
UNITS_DIR = os.path.join(HERE, "site", "icons", "units")
DATA = os.path.join(HERE, "site", "data.json")
FRAME_MS = 200   # 6/30 s

def main():
    data = json.load(open(DATA, encoding="utf-8"))
    radius_of = {}                       # icon filename -> radius
    for u in data["units"].values():
        radius_of.setdefault(u["icon"], u.get("radius", 0) or 0)

    animated = static = skipped = 0
    for icon, radius in radius_of.items():
        path = os.path.join(UNITS_DIR, icon)
        if not os.path.exists(path):
            skipped += 1
            continue
        im = Image.open(path).convert("RGBA")
        w, h = im.size
        base = 60 if w % 60 == 0 else 16
        fs = base * (1 + 2 * radius)
        if fs <= 0 or w % fs or h % fs:
            skipped += 1
            continue
        cols, rows = w // fs, h // fs
        idle_y = (rows - 1) * fs

        frames = []
        for col in range(cols):
            fr = im.crop((col * fs, idle_y, col * fs + fs, idle_y + fs))
            frames.append(fr)
        # drop trailing fully-transparent frames (avoid blank flicker in the loop)
        while len(frames) > 1 and frames[-1].getbbox() is None:
            frames.pop()

        if len(frames) <= 1:
            frames[0].save(path)         # static single idle frame
            static += 1
        else:
            frames[0].save(path, save_all=True, append_images=frames[1:],
                           duration=FRAME_MS, loop=0, disposal=2, blend=0, format="PNG")
            animated += 1

    print(f"animated: {animated}, static: {static}, skipped: {skipped}")

if __name__ == "__main__":
    main()
