"""One-off: crop templates from the chat screenshots and fill rules.json.

Run from the screenbot folder:  python make_templates.py
"""

import json
from pathlib import Path

from PIL import Image

CACHE = Path(r"C:\Users\win11\.claude\image-cache\a26467e8-0d8f-46db-88cf-dd10ab9be089")
TPL = Path(__file__).resolve().parent / "templates"
RULES = Path(__file__).resolve().parent / "config" / "rules.json"

TPL.mkdir(exist_ok=True)

# (rule id, source image, crop box left/top/right/bottom, template filename)
CROPS = [
    ("r09tmate", 1, (985, 615, 1262, 700), "btn_search_teammate.png"),
    ("r10start", 2, (1010, 628, 1265, 698), "btn_start_search.png"),
    ("r05rdy",   3, (1030, 628, 1262, 700), "btn_ready_green.png"),
    ("r08scrll", 4, (480, 40, 720, 95), "hdr_23_strategy.png"),
    ("r07cann",  5, (815, 175, 910, 265), "card_cannot.png"),
    ("r06cfrm",  5, (985, 622, 1262, 700), "btn_confirm_choice.png"),
    ("r04buy",   7, (1110, 118, 1250, 168), "btn_ready_red.png"),
    ("r01die",  10, None, "avatar_dead.png"),
    ("r03cont", 11, (998, 625, 1262, 705), "btn_continue_search.png"),
    ("r02conf", 12, (875, 465, 990, 520), "btn_confirm_exit.png"),
    ("r12bconf", ("autofit", 29, 27), None, "btn_confirm_bounty.png"),
]


def autofit(probe_no: int, target_no: int, fname: str) -> None:
    """Probe image may be zoomed: find its true scale/position inside the
    real game screenshot and crop the in-game pixels as the template."""
    import cv2
    probe = cv2.imread(str(CACHE / f"{probe_no}.png"), cv2.IMREAD_GRAYSCALE)
    target = cv2.imread(str(CACHE / f"{target_no}.png"), cv2.IMREAD_GRAYSCALE)
    best = (0.0, None, None)
    for s in [i / 100 for i in range(30, 131, 5)]:
        p = cv2.resize(probe, None, fx=s, fy=s)
        if p.shape[0] >= target.shape[0] or p.shape[1] >= target.shape[1]:
            continue
        res = cv2.matchTemplate(target, p, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx > best[0]:
            best = (mx, s, loc)
    mx, s, loc = best
    if s is None or mx < 0.6:
        raise SystemExit(f"autofit 失败: {fname} score={mx:.3f}")
    ph, pw = probe.shape
    x, y = loc
    box = (x, y, x + int(pw * s), y + int(ph * s))
    Image.open(CACHE / f"{target_no}.png").crop(box).save(TPL / fname)
    print(f"模板 {fname}  <- autofit {probe_no}.png@{target_no}.png "
          f"scale={s} score={mx:.3f} box={box}")

# rule id -> extra fields
EXTRA = {
    "r01die":   {"region": [10, 150, 120, 500], "pre_clicks": [[65, 90]]},
    "r02conf":  {"region": [0, 440, 1280, 110]},
    "r03cont":  {"region": [640, 360, 640, 360]},
    "r04buy":   {"region": [640, 0, 640, 360],
                 "pre_clicks": [[1000, 645], [1000, 645]]},
    "r05rdy":   {"region": [640, 360, 640, 360]},
    "r06cfrm":  {"region": [640, 360, 640, 360]},
    "r07cann":  {"region": [500, 130, 720, 570]},
    "r08scrll": {"region": [400, 30, 400, 80], "offset": [270, 353],
                 "scroll": 48},
    "r09tmate": {"region": [640, 360, 640, 360]},
    "r10start": {"region": [640, 360, 640, 360]},
    "r12bconf": {"region": [150, 110, 970, 610]},
    "r11bounty": {
        "template": "",
        "region": None,
        "bright_slots": [[285, 122], [665, 122], [980, 122],
                         [285, 418], [665, 418], [980, 418]],
        "bright_thresh": 150.0,
        "bright_min": 5,
        "dark_slots": [[285, 250], [665, 250], [980, 250],
                       [285, 550], [665, 550], [980, 550]],
        "dark_offset": [0, 85],
        "dark_thresh": 100.0,
        "dark_clicks": 1,
        "once_per_appearance": False,
    },
}


def main() -> None:
    for rid, img_no, box, fname in CROPS:
        if isinstance(img_no, tuple) and img_no[0] == "autofit":
            autofit(img_no[1], img_no[2], fname)
            continue
        src = CACHE / f"{img_no}.png"
        if not src.exists():
            raise SystemExit(f"缺少源截图: {src}")
        img = Image.open(src)
        (img if box is None else img.crop(box)).save(TPL / fname)
        print(f"模板 {fname}  <- {src.name} {box}")

    rules = json.loads(RULES.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rules}
    for rid, _n, _b, fname in CROPS:
        by_id[rid]["template"] = str(TPL / fname)
    for rid, fields in EXTRA.items():
        by_id[rid].update(fields)
    RULES.write_text(json.dumps(rules, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print(f"已回填 {RULES}")


if __name__ == "__main__":
    main()
