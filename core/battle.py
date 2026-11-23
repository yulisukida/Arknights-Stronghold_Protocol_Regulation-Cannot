"""In-game round-preparation flow mimicking MAA StrongholdProtocol prep_phase.

Sequence: read gold -> buy operators -> drag them onto the board -> upgrade the
shop when gold allows -> click 准备就绪. All coordinates are MAA's 1280x720
client basis (our capture is native client, same basis).

This is a first functional port; bench/tile/shop positions may need calibration
against the live board view.
"""
import time

import cv2

from . import ocr, scanner, win32

# --- MAA 1280x720 client coordinates ---
GOLD = [1190, 512, 43, 32]
ROUND = [485, 21, 33, 31]
SLOTS = [1241, 377, 24, 28]
UPGRADE_TEXT = [0, 636, 507, 66]        # 升级 / 确认升级 / 满级 (button shifts)
SHOP_NAMES = [120, 666, 1013, 44]       # operator names on shop cards
SHOP_CARDS = [120, 513, 1013, 153]      # cost / empty / pact labels
READY = (1187, 113)
REFRESH = (1191, 457)
BENCH_SCAN = [120, 380, 930, 35]        # bench tier badges
BENCH_OFF = (50, 110)                   # press point = badge top-left + offset
CARD_FACE_Y = 610
CARD_BUY_Y = 681
SELL_POINT = (1180, 600)
# deploy tiles (path / safe / rear), melee-first ordering
TILES = [(872, 233), (795, 233), (883, 297), (802, 297),
         (810, 365), (894, 365), (995, 439), (907, 439)]


def _screen(eng, cx, cy):
    ox, oy = eng._pre_frame or (0, 0)
    return int(ox + cx), int(oy + cy)


def _click(eng, cx, cy):
    sx, sy = _screen(eng, cx, cy)
    eng._act(sx, sy, "left")


def _grab(eng):
    g = eng._grab()
    return g[0] if g else None


def read_gold(eng, img):
    return ocr.read_number(img, GOLD, eng._scale)


def read_slots(eng, img):
    v = ocr.read_number(img, SLOTS, eng._scale)
    return v % 10 if v is not None else None


MAX_LEVEL = 6
_ROMAN_UNI = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V",
              "Ⅵ": "VI", "ⅰ": "I", "ⅱ": "II", "ⅲ": "III", "ⅳ": "IV",
              "ⅴ": "V", "ⅵ": "VI"}
_ROMAN_VAL = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}


def roman(text):
    """Parse an OCR'd roman numeral (Ⅰ..Ⅵ). OCR often renders the bars as
    l / | / 1 / !, so those are folded to I. Returns 1..6 or None."""
    t = "".join(_ROMAN_UNI.get(ch, ch) for ch in text.strip())
    t = t.upper().replace(" ", "").replace("LEVEL", "").replace("LV", "")
    for ch in "L|1!ı]":
        t = t.replace(ch, "I")
    # anything else (e.g. "LEVE", "02", CJK) means this is not a bare numeral
    if not t or any(ch not in "IV" for ch in t):
        return None
    return _ROMAN_VAL.get(t)


def _roman_in(eng, img, region):
    for inv in (False, True):
        for text, _cx, _cy in ocr.read_text(img, region, eng._scale, invert=inv,
                                            zoom=4, pad=40):
            if "0" in text:
                continue            # "01" card index
            v = roman(text)
            if v:
                return v
    return None


# LEVEL box relative to the 升级 text centre (the card grows/moves with level,
# this offset stays fixed). Generous on purpose; tighten after calibration.
# Measured from the user's level-card crop (95x190 native): 升级 text centre
# (47,148), numeral centre (47,56), "LEVEL" label (47,35). So the numeral is
# ~92px straight above 升级; the box stops just below the LEVEL label.
# Live check: the old box (-108..-74) sat on the "LEVEL" label (centre ~-91,
# bottom ~-84), so the numeral is below it. Box now starts under the label.
LEVEL_BOX = (-28, -86, 56, 42)         # dx, dy, w, h (top raised 4px: glyph was clipped; LEVEL label ends ~-84)


def _roman_shape(crop):
    """OCR fallback for the blocky numeral font: threshold the bright glyph,
    split into connected parts left-to-right; tall narrow part = I, wide
    part = V. Returns 1..6 or None."""
    if crop is None or crop.size == 0:
        return None
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if bw.mean() > 127:
        bw = 255 - bw               # glyph must be the white part
    ys, xs = (bw > 0).nonzero()
    if len(xs) < 20:
        return None
    bw = bw[ys.min():ys.max() + 1, xs.min():xs.max() + 1] > 0
    gh, gw = bw.shape
    # columns mostly filled = vertical strokes (serif bars of Ⅱ don't count)
    col = bw.mean(axis=0)
    runs, start = [], None
    for x, f in enumerate(list(col) + [0]):
        if f >= 0.6 and start is None:
            start = x
        elif f < 0.6 and start is not None:
            runs.append((start, x))
            start = None
    # whatever is left after removing the bars: a V (wide top, narrow bottom)
    rest = bw.copy()
    for a, b in runs:
        rest[:, max(0, a - 1):b + 1] = False
    rx = rest.any(axis=0).nonzero()[0]
    has_v = False
    if rest.sum() > bw.sum() * 0.25 and len(rx):
        top = rest[: max(1, gh // 4)].any(axis=0).sum()
        bot = rest[-max(1, gh // 4):].any(axis=0).sum()
        has_v = top > bot * 1.6
    if not has_v:
        return {1: 1, 2: 2, 3: 3}.get(len(runs))
    v_center = (rx.min() + rx.max()) / 2.0
    left_bars = sum(1 for a, b in runs if (a + b) / 2.0 < v_center)
    right_bars = len(runs) - left_bars
    if left_bars == 1 and right_bars == 0:
        return 4
    if left_bars == 0:
        return {0: 5, 1: 6}.get(right_bars)
    return None


def _level_by_template(eng, img, region):
    """Match templates/lv_1.png .. lv_6.png (numeral crops taken from the
    game) inside a slightly enlarged level box. Highest score >= 0.8 wins."""
    from . import paths
    # generous search window: the user's hand-cut crops can be bigger than
    # the OCR box and need room to slide
    dx, dy = 40, 30
    big = [region[0] - dx, region[1] - dy, region[2] + 2 * dx, region[3] + 2 * dy]
    area = ocr._crop(img, big, eng._scale)
    if area is None:
        return None
    scores = []
    for lv in range(1, 6):                  # Ⅵ is detected via 已满级 text
        tpl = scanner.load_template(str(paths.TEMPLATE_DIR / f"lv_{lv}.png"))
        if tpl is None or tpl.shape[0] > area.shape[0] or tpl.shape[1] > area.shape[1]:
            continue
        s = float(cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED).max())
        scores.append((s, tpl.shape[1], lv))
    if not scores:
        return None
    eng._log("[局内] 等级模板分 " + " ".join(f"{lv}:{s:.2f}" for s, _w, lv in scores))
    ok = [x for x in scores if x[0] >= 0.8]
    if not ok:
        return None
    # Ⅰ is contained in Ⅱ/Ⅲ and Ⅴ in Ⅳ, so the smaller numeral also scores
    # high on the bigger one: among good matches prefer the widest template.
    best = max(x[0] for x in ok)
    near = [x for x in ok if x[0] >= best - 0.08]
    return max(near, key=lambda x: x[1])[2]


def read_level(eng, img, ux, uy):
    """Command-center level: roman numeral in the LEVEL box of the same card
    as 升级, searched at a fixed offset from the 升级 text. Logs raw OCR so
    the box can be calibrated; saves the crop to config/debug_level.png."""
    dx, dy, w, h = LEVEL_BOX
    region = [int(ux) + dx, int(uy) + dy, w, h]
    raw = [t for t, _x, _y in ocr.read_text(img, region, eng._scale, zoom=4, pad=40)]
    try:
        from . import paths
        crop = ocr._crop(img, region, eng._scale)
        if crop is not None:
            cv2.imwrite(str(paths.CONFIG_DIR / "debug_level.png"), crop)
    except Exception:
        pass
    v = _level_by_template(eng, img, region)
    if v is None:
        v = _roman_in(eng, img, region)
    if v is None:
        # Shape reading misreads Ⅳ->3 and Ⅴ->2 (checked against lv_4/lv_5),
        # so it is only logged, never used. Ⅵ comes from the 已满级 text.
        sv = _roman_shape(ocr._crop(img, region, eng._scale))
        eng._log(f"[局内] 等级模板/OCR未识别(形状参考={sv}，不采用)")
    if v is None:
        eng._log(f"[局内] 等级识别失败 升级@({int(ux)},{int(uy)}) OCR={raw}")
    return v


CARD_X0, CARD_STEP = 128, 162          # 6 shop card columns (left edges)


def tier6_score(crop):
    """Tier-VI cards have a pink -> bright-green gradient behind the shimmering
    Ⅵ (plus a pink/green stripe down the card's left edge). Normal cards show
    a dark grey box with a white numeral. Returns (pink_frac, green_frac)."""
    if crop is None or crop.size == 0:
        return 0.0, 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    vivid = (s >= 70) & (v >= 120)
    pink = vivid & (h >= 140) & (h <= 178)
    green = vivid & (h >= 35) & (h <= 95)
    n = float(h.size)
    return float(pink.sum()) / n, float(green.sum()) / n


# Measured on card crops: tier-VI top-left pink 0.34-0.43 / green 0.14-0.15,
# tier-I (卡达) 0.00 / 0.00. Thresholds sit well between the two.
TIER6_PINK, TIER6_GREEN = 0.12, 0.05


def is_tier6(eng, img, name_x):
    """Colour test on the card's top-left numeral box (animation-proof: the
    sparkle changes, the gradient colours stay)."""
    idx = max(0, min(5, int((name_x - CARD_X0) // CARD_STEP)))
    left = CARD_X0 + CARD_STEP * idx
    crop = ocr._crop(img, [left - 4, 510, 64, 56], eng._scale)
    p, g = tier6_score(crop)
    return p >= TIER6_PINK and g >= TIER6_GREEN, p, g


def read_tier(eng, img, name_x):
    """6 for tier-VI cards (colour test), else None: other tiers are not
    distinguished."""
    six, _p, _g = is_tier6(eng, img, name_x)
    return 6 if six else None


def read_upgrade(eng, img):
    """Return (state, button_x, cost); state in upgrade/confirm/maxed/None.
    Also stores the text centre y in eng._upgrade_y for read_level."""
    rows = ocr.read_text(img, UPGRADE_TEXT, eng._scale)
    state, ux, uy = None, None, None
    for text, cx, cy in rows:
        t = text.strip()
        if t == "升级":
            state, ux, uy = "upgrade", cx, cy
        elif t == "确认升级":
            state, ux, uy = "confirm", cx, cy
        elif "满级" in t or "MAX" in t.upper():
            state, ux, uy = "maxed", cx, cy
    eng._upgrade_y = uy
    cost = None
    if state in ("upgrade", "confirm") and ux is not None:
        cost = ocr.read_number(img, [ux - 15, 520, 30, 28], eng._scale)
        if cost is None:
            cost = ocr.read_number(img, [0, 513, 160, 120], eng._scale)
    return state, ux, cost


def _is_oper_name(t):
    # operator names are >=2 CJK chars; rejects key labels (G/C), footer
    # (CLOUDX SOL SYSTEM), digits and symbols.
    cjk = sum(1 for ch in t if "一" <= ch <= "鿿")
    return cjk >= 2


def read_shop_cards(eng, img):
    """Find operator shop cards: list of {x, cost, name}. Uses name OCR for x,
    cost OCR near each card top. Filters out key labels / footer / equipment."""
    names = ocr.read_text(img, SHOP_NAMES, eng._scale)
    labels = ocr.read_text(img, SHOP_CARDS, eng._scale)
    # 盟约 pact label band (operators have it, equipment does not)
    pacts = ocr.read_text(img, [120, 640, 1013, 28], eng._scale)
    pact_xs = [px for pt, px, py in pacts if _is_oper_name(pt) or "盟" in pt]
    cards = []
    for text, cx, cy in names:
        t = text.strip()
        if not _is_oper_name(t):
            continue
        if any(abs(cx - c["x"]) <= 30 for c in cards):
            continue   # dedup same column
        if not any(abs(cx - px) <= 70 for px in pact_xs):
            continue   # no pact label -> equipment, skip
        # cost digit sits at the card's top-right, measured ~61px right of the
        # name centre (names 666/828/991 -> costs 727/889/1051). The "01"
        # index sits top-left (~-32px) and is excluded by the window and by
        # its leading 0. Take the closest candidate.
        cost, best = None, None
        for lt, lx, ly in labels:
            if not (cx + 20 <= lx <= cx + 100 and ly < cy - 80):
                continue
            d = "".join(c for c in lt if c.isdigit())
            if not d or len(d) > 2 or d.startswith("0"):
                continue
            dist = abs(lx - (cx + 61))
            if best is None or dist < best:
                cost, best = int(d), dist
        cards.append({"x": cx, "cost": cost, "name": t,
                      "tier": read_tier(eng, img, cx)})
    cards.sort(key=lambda c: c["x"])
    return cards


def _stopped(eng):
    return eng._stop.is_set()


MIN_GOLD = 9          # maxed: keep shopping until gold drops below this
MAX_REFRESH = 30      # safety cap on refreshes per round


def _pick(eng, cards, gold, tier6_only):
    """Choose a card and log why nothing was chosen. A card whose cost OCR
    failed is still a candidate: buy_oper verifies the purchase by the gold
    drop, so an unaffordable click just does nothing."""
    desc = " ".join(f"{c['name']}(费{c['cost']},阶{c.get('tier')})" for c in cards)
    eng._log(f"[局内] 商店识别: {desc or '无干员卡'}")
    pool = [c for c in cards if c.get("tier") == MAX_LEVEL] if tier6_only else cards
    afford = [c for c in pool
              if c["cost"] is None or gold is None or c["cost"] <= gold]
    if not afford:
        if pool:
            eng._log(f"[局内] 买不起：金币{gold}")
        return None
    known = [c for c in afford if c["cost"] is not None]
    return known[0] if known else afford[0]


def _buy_and_deploy(eng, pick, gold):
    if not buy_oper(eng, pick, gold):
        eng._log(f"[局内] 购买 {pick['name']} 失败（金币未减少）")
        return False
    eng._log(f"[局内] 买入 {pick['name']} 阶{pick.get('tier')} 费用{pick['cost']}")
    time.sleep(0.5)
    if _stopped(eng):
        return True
    img = _grab(eng)
    if img is not None:
        bench = detect_bench(eng, img)
        if bench:
            deploy(eng, bench[0])
        else:
            eng._log("[局内] 整备区没找到干员，跳过部署")
    return True


def _maxed_shopping(eng, gold):
    """Command center VI: no one-per-round limit. Buy only tier-VI operators,
    refreshing the shop when none is on offer, until gold < MIN_GOLD."""
    refreshes = 0
    while not _stopped(eng):
        img = _grab(eng)
        if img is None:
            return
        gold = read_gold(eng, img)
        if gold is None or gold < MIN_GOLD:
            eng._log(f"[局内] 金币{gold}<{MIN_GOLD}，停止购买")
            return
        pick = _pick(eng, read_shop_cards(eng, img), gold, tier6_only=True)
        if pick is not None:
            if _buy_and_deploy(eng, pick, gold):
                continue
        if refreshes >= MAX_REFRESH:
            eng._log(f"[局内] 已刷新{refreshes}次，本回合停止")
            return
        _click(eng, *REFRESH)
        refreshes += 1
        eng._log(f"[局内] 无6阶干员，刷新商店（第{refreshes}次）")
        time.sleep(1.0)


def buy_oper(eng, card, gold):
    """Click card face then buy button; return True if gold dropped (bought)."""
    if _stopped(eng):
        return False
    x = card["x"]
    before = read_gold(eng, _grab(eng))
    _click(eng, x, CARD_FACE_Y)
    time.sleep(0.4)
    if _stopped(eng):
        return False
    _click(eng, x, CARD_BUY_Y)
    time.sleep(0.6)
    after = read_gold(eng, _grab(eng))
    if card.get("cost") == 0:
        return True
    if before is not None and after is not None and after < before:
        return True
    return False


def detect_bench(eng, img):
    """Locate bench operators by tier badges; return press points (x,y)."""
    scx, scy = eng._scale
    x0, y0 = int(BENCH_SCAN[0] * scx), int(BENCH_SCAN[1] * scy)
    x1 = x0 + int(BENCH_SCAN[2] * scx)
    y1 = y0 + int(BENCH_SCAN[3] * scy)
    strip = img[y0:y1, x0:x1]
    if strip.size == 0:
        return []
    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    pts = []
    for c in contours:
        rx, ry, rw, rh = cv2.boundingRect(c)
        if 20 <= rw <= 36 and 20 <= rh <= 36:
            bx = x0 + rx + BENCH_OFF[0]
            by = y0 + ry + BENCH_OFF[1]
            pts.append((bx, by))
    pts.sort(key=lambda p: -p[0])   # right-to-left
    return pts


# map area. Bottom kept at 470: extending to 530 picked up a green UI band at
# y~485 (same x 903/960/1017 on three different maps = not the map).
BOARD = (140, 50, 1150, 470)      # x0, y0, x1, y1
MAX_DEPLOY = 8
NEAR = 55                         # px: within this of a placed op = occupied


INSIDE = 18      # px a drop point must lie inside the green area


def green_target(img, placed, near=None):
    """Bottom-right-most point lying >= INSIDE px inside the green highlight,
    away from already placed operators. Adjacent green tiles merge into one
    blob, so blob centres can land on rocks; a distance transform instead
    guarantees the point sits on green. Returns (x, y) or None."""
    m = green_mask(img)
    if m is None:
        return None
    dist = cv2.distanceTransform((m > 0).astype("uint8"), cv2.DIST_L2, 5)
    ys, xs = (dist >= INSIDE).nonzero()
    if not len(xs):
        return None
    x0, y0 = BOARD[0], BOARD[1]
    H, W = m.shape
    order = (xs + ys).argsort()[::-1]
    for i in order[::3]:
        x, y = int(xs[i]) + x0, int(ys[i]) + y0
        if any(_same_tile(x, y, p) for p in placed):
            continue
        # (x, y) is near the tile's bottom-right corner: move to the tile
        # centre so the next pick can't fall in the same tile
        w, h = tile_size(y)
        cx, cy = int(x - w / 2 + INSIDE), int(y - h / 2 + INSIDE)
        lx, ly = cx - x0, cy - y0
        if 0 <= lx < W and 0 <= ly < H and m[ly, lx] > 0 \
                and not any(_same_tile(cx, cy, p) for p in placed):
            return cx, cy
        return x, y
    return None


def tile_size(y):
    """Approx on-screen tile (width, height) at screen row y. Perspective
    makes lower tiles bigger. Fitted to the user's maps: neighbouring tile
    centres ~82px apart around y=320, rows ~65-70px apart."""
    w = 57 + 0.08 * y
    return w, w * 0.8


def _same_tile(x, y, p):
    """True if (x, y) is in the tile centred at p (or overlapping it)."""
    w, h = tile_size(p[1])
    return abs(x - p[0]) < 0.75 * w and abs(y - p[1]) < 0.75 * h


def green_mask(img):
    x0, y0, x1, y1 = BOARD
    roi = img[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    return _green(roi)


def find_green_tiles(img):
    """Centres of green blobs (adjacent tiles merge). Used for logging only."""
    m = green_mask(img)
    if m is None:
        return []
    x0, y0 = BOARD[0], BOARD[1]
    n, _lab, stats, cents = cv2.connectedComponentsWithStats(m)
    return [(int(cents[i][0]) + x0, int(cents[i][1]) + y0)
            for i in range(1, n) if stats[i][4] >= 250]


def _green(roi):
    # Wide green window: the highlight is blended with floors of different
    # colours, so hue/saturation drift. Two conditions together:
    #  - hue 28..88 (OpenCV 0..180; cyan of the bench UI is ~90-100), sat>=40
    #  - green channel clearly dominant: G >= R+18 and G >= B+18. Cyan has
    #    B close to G, so it fails this even if its hue drifts into range.
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    m_h = cv2.inRange(hsv, (28, 40, 70), (88, 255, 255))
    b, g, r = [c.astype("int16") for c in cv2.split(roi)]
    m_d = (((g - r) >= 18) & ((g - b) >= 18)).astype("uint8") * 255
    m = cv2.bitwise_and(m_h, m_d)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    # close small dark gaps (grime/texture on the floor) inside the highlight
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))


def _deploy_state(eng):
    """Per-game list of placed tile centres (oldest first). Reset when no
    prep phase ran for 5 min (= a new game)."""
    now = time.time()
    if now - getattr(eng, "_deploy_t", 0) > 300:
        eng._deployed = []
        eng._deploy_n = 0
    eng._deploy_t = now
    return eng._deployed


def deploy(eng, bench_pt):
    """Press the bench operator, drag a little so the deployable tiles light
    up green, capture, keep holding and drag onto a free green tile (or onto
    the oldest operator once 8 are placed), release, then swipe right for
    facing. Returns the tile used, or None."""
    if _stopped(eng) or not eng._hwnd:
        return None
    placed = _deploy_state(eng)
    bx, by = bench_pt
    drag = win32.Drag(eng._hwnd, bx, by)
    drag.move(bx, by - 70, steps=6, duration=0.15)
    drag.hold(0.5)
    img = win32.capture_window(eng._hwnd)
    greens = find_green_tiles(img) if img is not None else []
    target = None
    if eng._deploy_n >= MAX_DEPLOY and placed:
        target = placed[(eng._deploy_n - MAX_DEPLOY) % len(placed)]
        why = f"替换第{(eng._deploy_n - MAX_DEPLOY) % len(placed) + 1}个位置"
    else:
        target = green_target(img, placed) if img is not None else None
        why = f"最右下的空绿格，绿色区域{len(greens)}块"
    if img is not None:
        try:
            from . import paths
            vis = img.copy()
            if target:
                cv2.circle(vis, target, 12, (0, 0, 255), 3)
            for p in placed:
                cv2.circle(vis, p, 12, (255, 0, 0), 2)
            cv2.imwrite(str(paths.CONFIG_DIR / "debug_deploy.png"), vis)
        except Exception:
            pass
    if target is None:
        drag.move(bx, by, steps=6, duration=0.15)     # put it back on the bench
        drag.release(0.1)
        eng._log(f"[局内] 未找到可部署的绿色格子(检测到{len(greens)}个)")
        return None
    drag.move(target[0], target[1], steps=14, duration=0.4)
    drag.release(0.3)
    time.sleep(0.4)
    if eng._deploy_n < MAX_DEPLOY:
        placed.append(target)
    eng._deploy_n += 1
    eng._log(f"[局内] 部署到{target}（{why}），累计部署{eng._deploy_n}")
    if _stopped(eng):
        return target
    tile = target
    tx, ty = _screen(eng, *tile)
    # set facing: swipe right from the tile
    dist = min(400, 1280 - 1 - tile[0])
    fx, fy = _screen(eng, tile[0] + dist, tile[1])
    win32.post_swipe(eng._hwnd, tx, ty, fx, fy, steps=8, duration=0.15)
    time.sleep(0.3)
    return target


def do_upgrade(eng, gold):
    """Locate the upgrade button, click it, re-locate (升级->确认升级), click
    again. Returns True if an upgrade was performed."""
    if _stopped(eng):
        return False
    img = _grab(eng)
    if img is None:
        return False
    state, ux, cost = read_upgrade(eng, img)
    if state == "maxed" or ux is None:
        return False
    if cost is not None and gold is not None and gold < cost:
        return False
    _click(eng, ux, 660)          # click 1: 升级
    time.sleep(0.5)
    if _stopped(eng):
        return True
    img = _grab(eng)              # re-locate (button now 确认升级, may shift)
    if img is not None:
        _s2, ux2, _c2 = read_upgrade(eng, img)
        if ux2 is not None:
            _click(eng, ux2, 660)  # click 2: 确认升级
            time.sleep(0.5)
    return True


def prep_phase(eng):
    """One round. gold>30 and command center below VI: upgrade (twice) then
    ready, no buying. Otherwise buy ONE operator (tier-VI first once the
    command center is VI) -> drag deploy -> ready. Honors the stop flag."""
    if _stopped(eng):
        return False
    img = _grab(eng)
    if img is None:
        return False
    gold = read_gold(eng, img)
    state, ux, _cost = read_upgrade(eng, img)
    uy = getattr(eng, "_upgrade_y", None)
    level = read_level(eng, img, ux, uy) if ux is not None and uy is not None else None
    if ux is None:
        eng._log("[局内] 未找到“升级”文字，无法定位等级框")
    maxed = state == "maxed" or (level is not None and level >= MAX_LEVEL)
    eng._log(f"[局内] 金币={gold} 指挥中心等级={level}{'(满级)' if maxed else ''}")

    # gold > 30 and not max level: skip buying this round, upgrade then ready
    if gold is not None and gold > 30 and not maxed:
        if do_upgrade(eng, gold):
            eng._log(f"[局内] 金币{gold}>30，本回合不买人，已升级")
        if _stopped(eng):
            return False
        _click(eng, *READY)
        time.sleep(0.8)
        eng._log("[局内] 已准备就绪")
        return True

    if maxed:
        _maxed_shopping(eng, gold)
    else:
        # buy ONE affordable operator
        cards = read_shop_cards(eng, img)
        pick = _pick(eng, cards, gold, tier6_only=False)
        if pick is not None and not _stopped(eng):
            _buy_and_deploy(eng, pick, gold)

    # ready
    if _stopped(eng):
        return False
    _click(eng, *READY)
    time.sleep(0.8)
    eng._log("[局内] 已准备就绪")
    return True