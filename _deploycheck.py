"""Check green-tile detection on the deploy screenshots and the tier-VI
colour test on the shop-card crops. Run: python _deploycheck.py"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import battle  # noqa: E402

DEPLOY = [r"D:\videos\Captures\明日方舟 11_23_2026 6_48_46 PM.png",
          r"D:\videos\Captures\明日方舟 11_22_2026 11_38_23 PM.png",
          r"D:\videos\Captures\明日方舟 11_23_2026 6_53_39 PM.png",
          r"C:\Users\win11\Downloads\_cgi-bin_mmwebwx-bin_webwxgetmsgimg__&MsgID=6491339935567689759&skey=@crypt_869417b5_5e373047fa3e23853846042a2fcef718&mmweb_appid=wx_webfilehelper.jpg"]
SS = r"C:\Users\win11\Pictures\Screenshots"
CARDS = ["Screenshot 2026-11-23 141854.png",     # 卡达, tier I
         "Screenshot 2026-11-23 190100.png",     # orange VI numeral
         "Screenshot 2026-11-23 190437.png",
         "Screenshot 2026-11-23 190630.png",
         "Screenshot 2026-11-23 190656.png"]


def load(p):
    return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)


for p in DEPLOY:
    im = load(p)
    if im is None:
        print("missing", p)
        continue
    if im.shape[1] != 1280:
        im = cv2.resize(im, (1280, int(im.shape[0] * 1280 / im.shape[1])))
    g = battle.find_green_tiles(im)
    print(f"{os.path.basename(p)[-20:]} size={im.shape[1]}x{im.shape[0]} n={len(g)} green={g}")
    # paint detections so they can be eyeballed
    vis = im.copy()
    x0, y0, x1, y1 = battle.BOARD
    cv2.rectangle(vis, (x0, y0), (x1, y1), (255, 255, 255), 1)
    m = battle.green_mask(im)
    over = vis[y0:y1, x0:x1]
    over[m > 0] = (0.5 * over[m > 0] + (0, 0, 127)).astype("uint8")   # tint detected green red
    # simulate 3 successive deploys
    placed = []
    for k in range(3):
        t = battle.green_target(im, placed)
        print(f"   deploy {k + 1} -> {t}")
        if t is None:
            break
        cv2.circle(vis, t, 12, (255, 0, 0), 3)
        cv2.putText(vis, str(k + 1), (t[0] - 6, t[1] + 6), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2)
        placed.append(t)
    cv2.imwrite(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config",
                f"_green_{DEPLOY.index(p)}.png"), vis)

print()
for f in CARDS:
    im = load(os.path.join(SS, f))
    if im is None:
        print("missing", f)
        continue
    h, w = im.shape[:2]
    # whole crop and its top-left quarter
    pa, ga = battle.tier6_score(im)
    pt, gt = battle.tier6_score(im[: max(1, h // 3), : max(1, w // 2)])
    print(f"{f} size={w}x{h} whole pink={pa:.3f} green={ga:.3f} | "
          f"top-left pink={pt:.3f} green={gt:.3f}")
