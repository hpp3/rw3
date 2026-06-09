"""Generate site/favicon.png from the Magic Rune component icon, cropped tight
to the non-transparent pixels on all sides."""
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "site", "icons", "components", "magic_rune.png")
OUT = os.path.join(HERE, "site", "favicon.png")

im = Image.open(SRC).convert("RGBA")
alpha = im.getchannel("A")
bbox = alpha.getbbox()          # tightest box around non-transparent pixels
if bbox:
    im = im.crop(bbox)
print("cropped size", im.size)

# Upscale (nearest = keep crisp pixel art) to a comfortable favicon size.
target = 64
scale = max(1, target // max(im.size))
if scale > 1:
    im = im.resize((im.size[0] * scale, im.size[1] * scale), Image.NEAREST)

im.save(OUT)
print("wrote", OUT, im.size)
