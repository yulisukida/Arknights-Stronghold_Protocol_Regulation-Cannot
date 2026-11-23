"""Check lv_1..lv_5 templates: size, shape-read numeral, cross-match matrix.
Run: python _lvcheck.py   (from the screenbot_v2 folder)"""
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import battle  # noqa: E402

T = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
imgs = {}
for lv in range(1, 6):
    p = os.path.join(T, f"lv_{lv}.png")
    im = cv2.imread(p)
    imgs[lv] = im
    shape = None if im is None else im.shape
    sv = None if im is None else battle._roman_shape(im)
    print(f"lv_{lv}.png size={shape} shape-read={sv}")

print("\ncross match (row = image, col = template):")
print("      " + "  ".join(f"t{c}  " for c in range(1, 6)))
for r in range(1, 6):
    row = []
    for c in range(1, 6):
        a, t = imgs[r], imgs[c]
        if a is None or t is None or t.shape[0] > a.shape[0] or t.shape[1] > a.shape[1]:
            row.append(" -- ")
            continue
        row.append(f"{cv2.matchTemplate(a, t, cv2.TM_CCOEFF_NORMED).max():.2f}")
    print(f"img{r}  " + "  ".join(row))
