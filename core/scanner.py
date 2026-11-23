import os

import cv2
import pygetwindow as gw

from . import adb, capture, matcher, paths, win32

_cache = {}

# Reference CLIENT size (pure game, no title bar) — same basis as MAA. The
# client-only capture yields this directly; other client sizes scale by ratio.
REF_W, REF_H = 1280, 720

# Single-scale matching: the UI render ratio (1.0 or 0.9) is calibrated once at
# startup and folded into the engine scale, so no per-match scale search needed.
MATCH_SCALES = (1.0,)


def _scaled(tpl, scale):
    sx, sy = scale
    if abs(sx - 1.0) < 1e-3 and abs(sy - 1.0) < 1e-3:
        return tpl
    h, w = tpl.shape[:2]
    return cv2.resize(tpl, (max(1, int(round(w * sx))), max(1, int(round(h * sy)))),
                      interpolation=cv2.INTER_AREA)


def find_window(title: str):
    """(left, top, width, height, hwnd) or None."""
    if not title:
        return None
    for w in gw.getWindowsWithTitle(title):
        if w.width > 1 and w.height > 1:
            return (w.left, w.top, w.width, w.height, getattr(w, "_hWnd", None))
    return None


def activate_window(title: str) -> None:
    """Bring the game window to the foreground before clicking (best effort)."""
    if not title:
        return
    try:
        wins = gw.getWindowsWithTitle(title)
        if wins and not wins[0].isActive:
            wins[0].activate()
    except Exception:
        pass


def grab_frame(settings):
    """Returns (BGR image, frame origin, is_window, hwnd).

    Window mode: the image is the game window, regions/coordinates are
    window-relative. Background mode renders via PrintWindow (no focus
    needed); on failure it falls back to a screen grab of the window rect.
    Screen mode: the image is the primary monitor.
    """
    if settings.get("emu_mode"):
        exe = settings.get("adb_exe", "adb")
        addr = settings.get("adb_addr", "")
        img = adb.screencap(exe, addr)
        if img is None:
            adb.connect(addr, exe)
            img = adb.screencap(exe, addr)
        if img is None:
            return None, None, True, None
        return img, (0, 0), True, None
    if settings.get("use_window") and settings.get("window_title"):
        win = find_window(settings["window_title"])
        if win is None:
            return None, None, True, None
        hwnd = win[4]
        img = None
        if settings.get("background_mode") and hwnd:
            img = win32.capture_window(hwnd)   # pure client area (1280x720)
        ox, oy = win32.client_origin(hwnd)     # client top-left in screen coords
        cw, ch = win32.client_rect(hwnd)
        if img is None:
            img = capture.grab((ox, oy, cw, ch))
        return img, (ox, oy), True, hwnd
    mon = capture.primary_monitor()
    return capture.grab(mon), (mon[0], mon[1]), False, None


def load_template(path: str):
    if not path:
        return None
    # Rules may carry absolute paths authored on another machine (e.g.
    # C:\Users\...\templates\x.png). Always prefer the local templates dir
    # (extracted next to the exe) by filename, so the same rules work anywhere.
    name = os.path.basename(str(path).replace("\\", "/"))
    local = paths.TEMPLATE_DIR / name
    target = str(local) if local.is_file() else str(path)
    try:
        mtime = os.path.getmtime(target)
    except OSError:
        return None
    hit = _cache.get(target)
    if hit and hit[0] == mtime:
        return hit[1]
    img = cv2.imread(target, cv2.IMREAD_COLOR)
    if img is None:
        return None
    _cache[target] = (mtime, img)
    return img


def first_dark_slot(full, frame, is_window, slots, thresh: float = 100.0,
                    offset=(0, 0), scale=(1.0, 1.0), region_scale=None):
    """First slot to click (absolute x, y) whose sampled patch is dark.

    Each slot [x, y] is the click point; brightness is sampled at (x+dx, y+dy)
    so the click can land on the card center while judging the plain area.
    Returns (click_abs_x, click_abs_y, report) or None if all bright.
    """
    h, w = full.shape[:2]
    scx, scy = scale
    rsx, rsy = region_scale if region_scale else scale
    rx, ry = max(2, int(round(10 * scx))), max(2, int(round(10 * scy)))
    report = []
    for sx, sy in slots:
        if is_window:
            ix, iy = int(sx * rsx), int(sy * rsy)
        else:
            ix, iy = int(sx) - frame[0], int(sy) - frame[1]
        px, py = ix + int(offset[0] * scx), iy + int(offset[1] * scy)
        if not (rx <= px < w - rx and ry <= py < h - ry):
            report.append("越界")
            continue
        patch = full[py - ry:py + ry, px - rx:px + rx]
        mean = float(patch.mean()) if patch.size else 255.0
        report.append(f"{int(mean)}")
        if mean < thresh:
            return (frame[0] + ix, frame[1] + iy), " ".join(report)
    return None, " ".join(report)


def bright_gate(full, frame, is_window, rule, scale=(1.0, 1.0), region_scale=None):
    """True if enough of the rule's bright_slots sit on a bright horizontal
    line (the bounty cards' top borders): detects the 6-module layout.

    Reverted to the border-line scheme: the per-module color-point variant
    false-positived on battle screens whose tiles read dark/bright.
    """
    slots = rule.get("bright_slots") or []
    thresh = float(rule.get("bright_thresh", 150.0))
    need = int(rule.get("bright_min", 0) or 0) or len(slots)
    rsx, rsy = region_scale if region_scale else scale
    scx, scy = scale
    hy, hx = max(2, int(round(7 * scy))), max(2, int(round(40 * scx)))
    h, w = full.shape[:2]
    count = 0
    for sx, sy in slots:
        ix, iy = (int(sx * rsx), int(sy * rsy)) if is_window else (int(sx) - frame[0], int(sy) - frame[1])
        if not (hx <= ix < w - hx and hy <= iy < h - hy):
            continue
        strip = full[iy - hy:iy + hy + 1, max(0, ix - hx):min(w, ix + hx)]
        if strip.size == 0:
            continue
        row_means = strip.mean(axis=2)
        if float(row_means.max(axis=1).max()) >= thresh:
            count += 1
    return count >= need, f"{count}/{len(slots)}"


def rule_hits(rule: dict, full, frame, is_window, scale=(1.0, 1.0),
              region_scale=None):
    """Match one rule against a grabbed frame. None = template missing.

    `scale` (window x UI render ratio) sizes the template; `region_scale`
    (window ratio only) positions the search box. UI elements are edge/center
    anchored, so the search region must NOT shrink with the UI render ratio —
    only the template image does. No padding: tight regions stay tight so
    nearby battlefield elements are not pulled into the search.
    """
    tpl = load_template(rule.get("template", ""))
    if tpl is None:
        return None
    tpl = _scaled(tpl, scale)
    rsx, rsy = region_scale if region_scale else scale
    h, w = full.shape[:2]
    region = rule.get("region")
    if region:
        if is_window:
            rl, rt = int(region[0] * rsx), int(region[1] * rsy)
        else:
            rl, rt = int(region[0]) - frame[0], int(region[1]) - frame[1]
        rw, rh = int(region[2] * rsx), int(region[3] * rsy)
        x0, y0 = max(0, rl), max(0, rt)
        x1, y1 = min(w, rl + rw), min(h, rt + rh)
        if x1 <= x0 or y1 <= y0:
            return []
        scr = full[y0:y1, x0:x1]
        origin = (frame[0] + x0, frame[1] + y0)
    else:
        scr = full
        origin = frame
    return matcher.find_all(scr, tpl, float(rule.get("threshold", 0.85)),
                            origin=origin, scales=MATCH_SCALES,
                            color=bool(rule.get("match_color", False)))
