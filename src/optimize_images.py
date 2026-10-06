#!/usr/bin/env python3
"""Оптимизация картинок: ужать до 1200px по длинной стороне, WebP q=80."""
import os, sys, glob
from PIL import Image

SRC = "img_raw"
DST = "../img"
MAX = 1200
os.makedirs(DST, exist_ok=True)

files = sorted(glob.glob(os.path.join(SRC, "*")))
total_in = total_out = 0
made = 0
errors = 0

for f in files:
    base = os.path.splitext(os.path.basename(f))[0]
    out = os.path.join(DST, base + ".webp")
    if os.path.exists(out) and os.path.getsize(out) > 0:
        total_in += os.path.getsize(f)
        total_out += os.path.getsize(out)
        made += 1
        continue
    try:
        im = Image.open(f)
        im.load()
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            im2 = im.convert("RGBA")
            bg.paste(im2, mask=im2.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > MAX:
            if w >= h:
                nw, nh = MAX, max(1, round(h * MAX / w))
            else:
                nw, nh = max(1, round(w * MAX / h)), MAX
            im = im.resize((nw, nh), Image.LANCZOS)
        im.save(out, "WEBP", quality=80, method=6)
        total_in += os.path.getsize(f)
        total_out += os.path.getsize(out)
        made += 1
    except Exception as e:
        errors += 1
        print("ОШИБКА", f, e)

print("сделано:", made, "ошибок:", errors)
print("было МБ:", round(total_in / 1048576, 1), "→ стало МБ:", round(total_out / 1048576, 1))
