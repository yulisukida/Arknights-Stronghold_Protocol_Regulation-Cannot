import os

import cv2
import pygetwindow as gw

from . import adb, capture, matcher, win32

_cache = {}


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
        rect, hwnd = win[:4], win[4]
        img = None
        if settings.get("background_mode") and hwnd:
            img = win32.capture_window(hwnd)
        if img is None:
            img = capture.grab(rect)
        return img, (rect[0], rect[1]), True, hwnd
    mon = capture.primary_monitor()
    return capture.grab(mon), (mon[0], mon[1]), False, None


def load_template(path: str):
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None
    _cache[path] = (mtime, img)
    return img


def first_dark_slot(full, frame, is_window, slots, thresh: float = 100.0,
                    offset=(0, 0)):
    """First slot to click (absolute x, y) whose sampled patch is dark.

    Each slot [x, y] is the click point; brightness is sampled at (x+dx, y+dy)
    so the click can land on the card center while judging the plain area.
    Returns (click_abs_x, click_abs_y, report) or None if all bright.
    """
    h, w = full.shape[:2]
    report = []
    for sx, sy in slots:
        if is_window:
            ix, iy = int(sx), int(sy)
        else:
            ix, iy = int(sx) - frame[0], int(sy) - frame[1]
        px, py = ix + int(offset[0]), iy + int(offset[1])
        if not (10 <= px < w - 10 and 10 <= py < h - 10):
            report.append("越界")
            continue
        patch = full[py - 10:py + 10, px - 10:px + 10]
        mean = float(patch.mean()) if patch.size else 255.0
        report.append(f"{int(mean)}")
        if mean < thresh:
            return (frame[0] + ix, frame[1] + iy), " ".join(report)
    return None, " ".join(report)


def bright_gate(full, frame, is_window, rule):
    """True if enough of the rule's bright_slots sit on a bright horizontal
    line (card top borders): detects the 6-module layout regardless of text."""
    slots = rule.get("bright_slots") or []
    thresh = float(rule.get("bright_thresh", 150.0))
    need = int(rule.get("bright_min", 0) or 0) or len(slots)
    h, w = full.shape[:2]
    count = 0
    for sx, sy in slots:
        ix, iy = (int(sx), int(sy)) if is_window else (int(sx) - frame[0], int(sy) - frame[1])
        if not (5 <= ix < w - 5 and 8 <= iy < h - 8):
            continue
        strip = full[iy - 7:iy + 8, max(0, ix - 40):min(w, ix + 40)]
        if strip.size == 0:
            continue
        row_means = strip.mean(axis=2)
        if float(row_means.max(axis=1).max()) >= thresh:
            count += 1
    return count >= need, f"{count}/{len(slots)}"


def rule_hits(rule: dict, full, frame, is_window):
    """Match one rule against a grabbed frame. None = template missing."""
    tpl = load_template(rule.get("template", ""))
    if tpl is None:
        return None
    h, w = full.shape[:2]
    region = rule.get("region")
    if region:
        if is_window:
            rl, rt = int(region[0]), int(region[1])
        else:
            rl, rt = int(region[0]) - frame[0], int(region[1]) - frame[1]
        rw, rh = int(region[2]), int(region[3])
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
                            origin=origin)
