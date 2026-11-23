"""Run the shop reader on config/debug_bg.png (or a given image) without the
game: prints gold, every OCR row in the shop bands, parsed cards, and saves
a crop around the REFRESH point. Run: python _shopcheck.py [image]"""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from core import battle, ocr  # noqa: E402


class FakeEng:
    _scale = (1.0, 1.0)

    def _log(self, t):
        print("LOG", t)


p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "config", "debug_bg.png")
img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
print("image", p, img.shape)
eng = FakeEng()
print("gold", battle.read_gold(eng, img))
for name, reg in [("NAMES", battle.SHOP_NAMES), ("CARDS", battle.SHOP_CARDS),
                  ("PACT", [120, 640, 1013, 28])]:
    rows = ocr.read_text(img, reg)
    print(name, [(t, int(x), int(y)) for t, x, y in rows])
print("cards", battle.read_shop_cards(eng, img))
rx, ry = battle.REFRESH
cv2.imwrite(os.path.join(ROOT, "config", "_refresh_crop.png"),
            img[max(0, ry - 40):ry + 40, max(0, rx - 60):rx + 60])
print("refresh crop saved around", battle.REFRESH)
