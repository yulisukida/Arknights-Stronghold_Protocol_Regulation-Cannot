"""Build emulator templates + rules_emu.json from real emulator screenshots.

Probes the existing PC templates against the emulator screenshots (cached
chat images 31/32/33) at several scales, crops the in-emulator pixels as
*_emu templates, then rewrites rules_emu.json with emulator-correct regions,
scroll landing offset and card pre-click coordinates.

Run:  python make_emu_templates.py
"""

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
CACHE = Path(r"C:\Users\win11\.claude\image-cache\a26467e8-0d8f-46db-88cf-dd10ab9be089")
TPL = ROOT / "templates"
EMU = TPL / "emu"
RULES = ROOT / "config" / "rules_emu.json"

EMU.mkdir(parents=True, exist_ok=True)

# rule id -> (pc template file, emulator screenshot number)
PROBES = {
    "r09tmate": ("btn_search_teammate.png", 31),
    "r08scrll": ("hdr_23_strategy.png", 32),
    "r04buy":   ("btn_ready_red.png", 33),
}

GRID_CENTER = (925, 445)      # strategy grid center in the emulator screen
CARD_SLOT4 = (920, 600)       # 4th card slot center in the emulator screen


def autofit(probe_bgr, target_bgr):
    """Locate probe in target over scales 0.88..1.12. Returns (x, y, w, h, score)."""
    p0 = cv2.cvtColor(probe_bgr, cv2.COLOR_BGR2GRAY)
    t = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2GRAY)
    best = (0.0, None, None)
    for s in [i / 100 for i in range(88, 113, 2)]:
        p = cv2.resize(p0, None, fx=s, fy=s)
        if p.shape[0] >= t.shape[0] or p.shape[1] >= t.shape[1]:
            continue
        res = cv2.matchTemplate(t, p, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx > best[0]:
            best = (mx, s, loc)
    mx, s, loc = best
    if s is None:
        return None
    h, w = p0.shape
    return loc[0], loc[1], int(w * s), int(h * s), mx, s


def main() -> None:
    rules = json.loads((ROOT / "config" / "rules.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rules}
    boxes = {}

    for rid, (fname, img_no) in PROBES.items():
        probe = cv2.imread(str(TPL / fname), cv2.IMREAD_COLOR)
        target = cv2.imread(str(CACHE / f"{img_no}.png"), cv2.IMREAD_COLOR)
        if probe is None or target is None:
            print(f"跳过 {fname}: 缺文件")
            continue
        hit = autofit(probe, target)
        if not hit or hit[4] < 0.55:
            print(f"!! {fname} 在模拟器图{img_no}中未找到 (score={hit[4]:.2f})" if hit
                  else f"!! {fname} 未找到")
            continue
        x, y, w, h, score, s = hit
        out = EMU / fname
        cv2.imwrite(str(out), target[y:y + h, x:x + w])
        boxes[rid] = (x, y, w, h, score)
        by_id[rid]["template"] = str(out)
        print(f"模拟器模板 {fname} <- 图{img_no} box=({x},{y},{w},{h}) "
              f"score={score:.3f} scale={s}")

    # emulator-specific coordinate fixes
    r08 = by_id["r08scrll"]
    r08["region"] = [400, 0, 400, 110]
    if "r08scrll" in boxes:
        x, y, w, h, _ = boxes["r08scrll"]
        cx, cy = x + w // 2, y + h // 2
        r08["offset"] = [GRID_CENTER[0] - cx, GRID_CENTER[1] - cy]
    r04 = by_id["r04buy"]
    r04["pre_clicks"] = [list(CARD_SLOT4), list(CARD_SLOT4)]

    RULES.write_text(json.dumps(rules, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print(f"已写 {RULES}")


if __name__ == "__main__":
    main()
