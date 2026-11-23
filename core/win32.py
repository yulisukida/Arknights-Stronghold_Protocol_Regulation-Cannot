"""Background interaction with a window: PrintWindow capture + PostMessage input.

No physical mouse movement, no focus stealing; works while the game is in the
background (usually even minimized). Requires the same or lower integrity level
than the target window (hence admin for an elevated game client).
"""

import ctypes
import time
from ctypes import wintypes

import cv2
import numpy as np

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002
PW_CLIENTONLY = 0x00000001

WM_ACTIVATE = 0x0006
WA_ACTIVE = 1
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002

SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_ASYNCWINDOWPOS = 0x4000

_POST = user32.PostMessageW
_POST.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_POST.restype = wintypes.BOOL

_SETWINPOS = user32.SetWindowPos
_SETWINPOS.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                       ctypes.c_int, ctypes.c_int, wintypes.UINT]
_SETWINPOS.restype = wintypes.BOOL

_GETCURSOR = user32.GetCursorPos
_GETCURSOR.argtypes = [ctypes.POINTER(wintypes.POINT)]
_GETCURSOR.restype = wintypes.BOOL

_CLIENTTOSCREEN = user32.ClientToScreen
_CLIENTTOSCREEN.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_CLIENTTOSCREEN.restype = wintypes.BOOL

_SCREENTOCLIENT = user32.ScreenToClient
_SCREENTOCLIENT.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
_SCREENTOCLIENT.restype = wintypes.BOOL

# --- pseudo-minimize (MAA PseudoMinimizeHelper): a minimized window prints
# black, so restore it invisibly (layered + alpha 0 + click-through) instead.
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
LWA_ALPHA = 0x00000002
SW_SHOWNOACTIVATE = 4
SW_MINIMIZE = 6

_kernel32 = ctypes.windll.kernel32
_LONGPTR = ctypes.c_ssize_t
_GETEX = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
_GETEX.argtypes = [wintypes.HWND, ctypes.c_int]
_GETEX.restype = _LONGPTR
_SETEX = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
_SETEX.argtypes = [wintypes.HWND, ctypes.c_int, _LONGPTR]
_SETEX.restype = _LONGPTR
_SETLWA = user32.SetLayeredWindowAttributes
_SETLWA.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
_SETLWA.restype = wintypes.BOOL
_GETLWA = user32.GetLayeredWindowAttributes
_GETLWA.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.COLORREF),
                    ctypes.POINTER(wintypes.BYTE), ctypes.POINTER(wintypes.DWORD)]
_GETLWA.restype = wintypes.BOOL
_SHOW = user32.ShowWindow
_SHOW.argtypes = [wintypes.HWND, ctypes.c_int]
_SHOW.restype = wintypes.BOOL
_GETFG = user32.GetForegroundWindow
_GETFG.argtypes = []
_GETFG.restype = wintypes.HWND

_pseudo = {}   # hwnd -> (original_ex_style, had_layered, original_alpha)


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER),
                ("bmiColors", wintypes.DWORD * 3)]


# --- GDI / client-DC bindings for client-only capture (64-bit handle safe) ---
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [wintypes.HDC, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                            wintypes.UINT, ctypes.c_void_p,
                            ctypes.POINTER(_BITMAPINFO), wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int


def _normalize_content(img):
    """If the rendered content sits inside a black margin (DWM invisible
    borders, DPI-scaled rendering), crop to its bbox and stretch back to the
    full frame so window-relative template coordinates stay valid."""
    h, w = img.shape[:2]
    lum = img.mean(axis=2)
    rows = np.where(lum.max(axis=1) > 24)[0]
    cols = np.where(lum.max(axis=0) > 24)[0]
    if len(rows) == 0 or len(cols) == 0:
        return img
    r0, r1 = int(rows[0]), int(rows[-1]) + 1
    c0, c1 = int(cols[0]), int(cols[-1]) + 1
    if r0 <= 1 and c0 <= 1 and r1 >= h - 1 and c1 >= w - 1:
        return img                      # content already fills the frame
    sub = img[r0:r1, c0:c1]
    return cv2.resize(sub, (w, h), interpolation=cv2.INTER_LINEAR)


def window_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def client_rect(hwnd):
    """Client-area size (pure game, no title bar/borders), e.g. 1280x720."""
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return r.right - r.left, r.bottom - r.top


def client_origin(hwnd):
    """Screen coords of the client-area top-left (for client->screen mapping)."""
    pt = wintypes.POINT(0, 0)
    _CLIENTTOSCREEN(hwnd, ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def is_minimized(hwnd) -> bool:
    return bool(user32.IsIconic(hwnd))


def pseudo_minimize(hwnd) -> bool:
    """If minimized, restore the window invisibly so PrintWindow can render it.

    Adds WS_EX_LAYERED|WS_EX_TRANSPARENT, sets alpha 0, then SW_SHOWNOACTIVATE:
    the window is restored (capture/click math work) but invisible and
    click-through. State is kept until revert_pseudo_minimize/revert_all.
    """
    if hwnd in _pseudo:
        return True
    if not user32.IsIconic(hwnd):
        return False
    _kernel32.SetLastError(0)
    ex = _GETEX(hwnd, GWL_EXSTYLE)
    if ex == 0 and _kernel32.GetLastError() != 0:
        return False
    had_layered = bool(ex & WS_EX_LAYERED)
    alpha = 255
    if had_layered:
        key, a, flags = wintypes.COLORREF(), wintypes.BYTE(), wintypes.DWORD()
        if _GETLWA(hwnd, ctypes.byref(key), ctypes.byref(a), ctypes.byref(flags)):
            alpha = a.value
    _kernel32.SetLastError(0)
    if _SETEX(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TRANSPARENT) == 0 \
            and _kernel32.GetLastError() != 0:
        return False
    if not _SETLWA(hwnd, 0, 0, LWA_ALPHA):
        _SETEX(hwnd, GWL_EXSTYLE, ex)
        return False
    _SHOW(hwnd, SW_SHOWNOACTIVATE)
    _pseudo[hwnd] = (ex, had_layered, alpha)
    return True


def revert_pseudo_minimize(hwnd, reminimize: bool = True) -> None:
    st = _pseudo.pop(hwnd, None)
    if st is None:
        return
    ex, had_layered, alpha = st
    _kernel32.SetLastError(0)
    _SETEX(hwnd, GWL_EXSTYLE, ex)
    if had_layered:
        _SETLWA(hwnd, 0, alpha, LWA_ALPHA)
    if reminimize:
        _SHOW(hwnd, SW_MINIMIZE)


def revert_all(reminimize: bool = True) -> None:
    for hwnd in list(_pseudo):
        revert_pseudo_minimize(hwnd, reminimize)


def pseudo_check_foreground(hwnd) -> None:
    # user brought the window back to the front -> make it visible again
    if hwnd in _pseudo and _GETFG() == hwnd:
        revert_pseudo_minimize(hwnd, reminimize=False)


def capture_window(hwnd):
    """BGR ndarray of the CLIENT area only (pure game, no Windows title bar),
    matching MAA's 1280x720 basis. Replicates MAA PrintWindowScreencap:
    GetDC (client DC) + CreateCompatibleBitmap + PrintWindow(PW_CLIENTONLY |
    PW_RENDERFULLCONTENT) + GetDIBits. None on failure."""
    pseudo_minimize(hwnd)
    pseudo_check_foreground(hwnd)
    w, h = client_rect(hwnd)
    if w <= 1 or h <= 1:
        return None
    hdc = user32.GetDC(hwnd)
    if not hdc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(hdc)
    bitmap = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem_dc, bitmap)
    ok = user32.PrintWindow(hwnd, mem_dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
    img = None
    if ok:
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h   # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0   # BI_RGB
        buf = (ctypes.c_ubyte * (w * h * 4))()
        got = gdi32.GetDIBits(mem_dc, bitmap, 0, h, buf, ctypes.byref(bmi), 0)
        if got:
            arr = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
            img = np.ascontiguousarray(arr[:, :, :3])
            center = img[h // 4:3 * h // 4, w // 4:3 * w // 4]
            if center.size == 0 or float(center.mean()) < 8.0:
                img = None
    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hdc)
    return img


def _mkparam(x: int, y: int) -> int:
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def _client_point(hwnd, sx: int, sy: int):
    pt = wintypes.POINT(sx, sy)
    _SCREENTOCLIENT(hwnd, ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def _align_window(hwnd, cx: int, cy: int) -> None:
    """Move the window so client point (cx, cy) sits under the real cursor.

    The Arknights PC client reads the physical cursor position, not the
    message lParam (MAA "PostMessageWithWindowPos"): the window jumps to the
    mouse, the mouse itself never moves.
    """
    cur = wintypes.POINT()
    _GETCURSOR(ctypes.byref(cur))
    org = wintypes.POINT(0, 0)
    _CLIENTTOSCREEN(hwnd, ctypes.byref(org))
    wl, wt, _w, _h = window_rect(hwnd)
    _SETWINPOS(hwnd, None,
               cur.x - cx - (org.x - wl), cur.y - cy - (org.y - wt),
               0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS)


def _restore_window(hwnd, left: int, top: int) -> None:
    # let the game pump the posted messages while the window is still aligned
    time.sleep(0.1)
    _SETWINPOS(hwnd, None, left, top, 0, 0,
               SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def post_click(hwnd, sx: int, sy: int, kind: str = "left") -> None:
    """Background click at screen coords, MAA PostMessageWithWindowPos style.

    WM_ACTIVATE makes the client think it is focused; the window is moved to
    put the target under the stationary cursor; mouse messages carry CLIENT
    coords; afterwards the window is moved back.
    """
    pseudo_minimize(hwnd)
    cx, cy = _client_point(hwnd, int(sx), int(sy))
    wl, wt, _w, _h = window_rect(hwnd)
    _POST(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
    time.sleep(0.01)
    _align_window(hwnd, cx, cy)
    time.sleep(0.01)
    lp = _mkparam(cx, cy)
    if kind == "right":
        down, up, mk = WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON
    else:
        down, up, mk = WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON
    _POST(hwnd, WM_MOUSEMOVE, mk, lp)
    time.sleep(0.01)
    _POST(hwnd, down, mk, lp)
    time.sleep(0.06)
    _POST(hwnd, up, 0, lp)
    if kind == "double":
        time.sleep(0.06)
        _POST(hwnd, down, mk, lp)
        time.sleep(0.06)
        _POST(hwnd, up, 0, lp)
    _restore_window(hwnd, wl, wt)


def post_scroll(hwnd, sx: int, sy: int, notches: int) -> None:
    """Wheel down `notches`; same align-window mechanism as post_click."""
    pseudo_minimize(hwnd)
    cx, cy = _client_point(hwnd, int(sx), int(sy))
    wl, wt, _w, _h = window_rect(hwnd)
    _POST(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
    time.sleep(0.01)
    _align_window(hwnd, cx, cy)
    time.sleep(0.01)
    # establish the hover point (client coords), like the working click path
    _POST(hwnd, WM_MOUSEMOVE, 0, _mkparam(cx, cy))
    # WM_MOUSEWHEEL lParam is SCREEN coords, recomputed AFTER the window moved
    # (MAA client_to_screen(target_pos) post-alignment); stale coords miss.
    pt = wintypes.POINT(cx, cy)
    _CLIENTTOSCREEN(hwnd, ctypes.byref(pt))
    delta = (-120 * abs(int(notches))) & 0xFFFF
    _POST(hwnd, WM_MOUSEWHEEL, delta << 16, _mkparam(pt.x, pt.y))
    _restore_window(hwnd, wl, wt)


class Drag:
    """Hold-the-button drag in pieces, so the screen can be captured while
    the finger is still down (e.g. to see green deployable tiles). Uses the
    same window-follows-cursor trick as post_swipe. Coordinates are CLIENT
    (game 1280x720) coords, so they stay valid while the window is moved;
    capture_window() also returns client pixels, independent of position."""

    def __init__(self, hwnd, cx: int, cy: int):
        self.hwnd = hwnd
        pseudo_minimize(hwnd)
        self.wl, self.wt, _w, _h = window_rect(hwnd)
        self.x, self.y = int(cx), int(cy)
        _POST(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
        time.sleep(0.01)
        _align_window(hwnd, self.x, self.y)
        time.sleep(0.01)
        lp = _mkparam(self.x, self.y)
        _POST(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lp)
        time.sleep(0.01)
        _POST(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(0.03)

    def move(self, cx: int, cy: int, steps: int = 10, duration: float = 0.25):
        x2, y2 = int(cx), int(cy)
        x1, y1 = self.x, self.y
        delay = max(0.005, duration / max(1, steps))
        for i in range(1, steps + 1):
            t = i / steps
            mx = int(round(x1 + (x2 - x1) * t))
            my = int(round(y1 + (y2 - y1) * t))
            _align_window(self.hwnd, mx, my)
            _POST(self.hwnd, WM_MOUSEMOVE, MK_LBUTTON, _mkparam(mx, my))
            time.sleep(delay)
        self.x, self.y = x2, y2

    def hold(self, seconds: float):
        lp = _mkparam(self.x, self.y)
        n = max(1, int(seconds / 0.04))
        for _ in range(n):
            _POST(self.hwnd, WM_MOUSEMOVE, MK_LBUTTON, lp)
            time.sleep(seconds / n)

    def release(self, hold: float = 0.3):
        self.hold(hold)
        _POST(self.hwnd, WM_LBUTTONUP, 0, _mkparam(self.x, self.y))
        _restore_window(self.hwnd, self.wl, self.wt)


def post_swipe(hwnd, sx1: int, sy1: int, sx2: int, sy2: int,
               steps: int = 12, duration: float = 0.25,
               hold: float = 0.3) -> None:
    """Drag from screen (sx1,sy1) to (sx2,sy2), MAA touch_down/move/up style.

    The cursor stays fixed; the window is moved so that, relative to the
    client, the cursor traces the drag path. Used instead of the wheel for
    scrolling lists (the PC client ignores posted WM_MOUSEWHEEL in background).

    `hold`: after reaching the end point the finger stays still (stationary
    move samples) for this long before lifting, so the client samples zero
    release velocity and does not fling — the list stops without inertia.
    """
    pseudo_minimize(hwnd)
    x1, y1 = _client_point(hwnd, int(sx1), int(sy1))
    x2, y2 = _client_point(hwnd, int(sx2), int(sy2))
    wl, wt, _w, _h = window_rect(hwnd)
    _POST(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
    time.sleep(0.01)
    # touch_down at the start point
    _align_window(hwnd, x1, y1)
    time.sleep(0.01)
    lp1 = _mkparam(x1, y1)
    _POST(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lp1)
    time.sleep(0.01)
    _POST(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp1)
    time.sleep(0.02)
    # touch_move: interpolate the drag, realigning the window each step
    delay = max(0.005, duration / max(1, steps))
    for i in range(1, steps + 1):
        t = i / steps
        mx = int(round(x1 + (x2 - x1) * t))
        my = int(round(y1 + (y2 - y1) * t))
        _align_window(hwnd, mx, my)
        _POST(hwnd, WM_MOUSEMOVE, MK_LBUTTON, _mkparam(mx, my))
        time.sleep(delay)
    # settle at the end point: stationary samples + a still hold so the
    # client reads zero velocity at release (no fling / inertia)
    lp2 = _mkparam(x2, y2)
    settle = 8
    for _ in range(settle):
        _POST(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lp2)
        time.sleep(max(0.005, hold / settle))
    # touch_up at the end point
    _POST(hwnd, WM_LBUTTONUP, 0, lp2)
    _restore_window(hwnd, wl, wt)
