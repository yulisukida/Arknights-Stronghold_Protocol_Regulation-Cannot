"""Watchdog recovery: kill the game and relaunch it through the Hypergryph launcher.

Double-clicking Arknights.exe does not start the game — it must be launched
from the 鹰角启动器 (Qt WebEngine). So the flow is:
  1. kill Arknights.exe (+ PlatformProcess.exe helper)
  2. restore the launcher window (it hides in the tray; WM_SYSCOMMAND SC_RESTORE
     is what actually un-minimizes it) and bring it to the foreground
  3. screen-grab it (WebEngine prints black via PrintWindow) and template-match
     the ▶ play-icon on the start pill, then foreground-click the pill
  4. wait for the game window to reappear

Navigating from the startup screens back to the main menu is left to the normal
rule loop (startup rules), not done here.
"""
import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from . import capture, clicker, matcher, paths, scanner, win32

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

WM_SYSCOMMAND = 0x0112
SC_RESTORE = 0xF120
SC_MINIMIZE = 0xF020
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040

LAUNCHER_TITLE = "鹰角启动器"
START_TEMPLATE = "launcher_start.png"
START_OFFSET_X = 40          # click right of the play-icon, clear of the ≡ submenu

# --- proper 64-bit bindings for the force-foreground dance ---
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.AttachThreadInput.restype = wintypes.BOOL
_user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
_user32.SetFocus.argtypes = [wintypes.HWND]
_user32.SetFocus.restype = wintypes.HWND
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.BringWindowToTop.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.SendMessageW.restype = ctypes.c_ssize_t
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD

VK_MENU = 0x12               # Alt
KEYEVENTF_KEYUP = 0x0002


def _pid(hwnd) -> int:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _exe_path(pid: int):
    hp = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not hp:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        sz = wintypes.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(sz)):
            return buf.value
        return None
    finally:
        _kernel32.CloseHandle(hp)


def _terminate(pid: int) -> bool:
    hp = _kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not hp:
        return False
    try:
        return bool(_kernel32.TerminateProcess(hp, 0))
    finally:
        _kernel32.CloseHandle(hp)


def _taskkill(image: str) -> None:
    subprocess.call(["taskkill", "/F", "/IM", image],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _launcher_exe(game_exe: str) -> str:
    """Walk up from the game exe to find the launcher's Launcher.exe."""
    if game_exe:
        for anc in Path(game_exe).parents:
            cand = anc / "Launcher.exe"
            if cand.is_file():
                return str(cand)
    return ""


def _force_foreground(hwnd) -> bool:
    """Actually activate a window from a background process.

    Plain SetForegroundWindow fails under Windows' foreground lock (the click
    then lands on whatever IS foreground). AttachThreadInput to the current
    foreground thread + a momentary Alt press unlocks it so the launcher truly
    comes to the front, even above a fullscreen browser/video.
    """
    _user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
    time.sleep(0.4)
    fg = _user32.GetForegroundWindow()
    fg_tid = _user32.GetWindowThreadProcessId(fg, None)
    my_tid = _kernel32.GetCurrentThreadId()
    _user32.keybd_event(VK_MENU, 0, 0, 0)
    _user32.AttachThreadInput(my_tid, fg_tid, True)
    _user32.ShowWindow(hwnd, 5)                 # SW_SHOW
    _user32.SetForegroundWindow(hwnd)
    _user32.BringWindowToTop(hwnd)
    _user32.SetFocus(hwnd)
    _user32.AttachThreadInput(my_tid, fg_tid, False)
    _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.6)
    return _user32.GetForegroundWindow() == hwnd


def _show_launcher(launcher_exe: str):
    w = scanner.find_window(LAUNCHER_TITLE)
    if (not w or not w[4]) and launcher_exe and os.path.isfile(launcher_exe):
        subprocess.Popen([launcher_exe], cwd=os.path.dirname(launcher_exe))
        for _ in range(60):
            w = scanner.find_window(LAUNCHER_TITLE)
            if w and w[4]:
                break
            time.sleep(0.5)
    if not w or not w[4]:
        return None
    hwnd = w[4]
    for _ in range(3):                          # foreground can need a retry
        if _force_foreground(hwnd):
            break
        time.sleep(0.4)
    return hwnd


# 开始游戏 pill position as a fraction of the launcher client area
# (measured on the 1278x717 launcher); used when the launcher can't be captured.
START_REL = (0.84, 0.885)
SW_SHOWNOACTIVATE = 4
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
MK_LBUTTON = 0x0001
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL


def _show_launcher_bg(launcher_exe: str):
    """Bring the launcher window up WITHOUT activating it (works with the
    screen off / session locked: no foreground or SendInput needed)."""
    w = scanner.find_window(LAUNCHER_TITLE)
    if (not w or not w[4]) and launcher_exe and os.path.isfile(launcher_exe):
        subprocess.Popen([launcher_exe], cwd=os.path.dirname(launcher_exe))
        for _ in range(60):
            w = scanner.find_window(LAUNCHER_TITLE)
            if w and w[4]:
                break
            time.sleep(0.5)
    if not w or not w[4]:
        return None
    hwnd = w[4]
    _user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
    _user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    time.sleep(1.5)                     # let WebEngine repaint after restore
    return hwnd


def _click_start_bg(hwnd) -> tuple[bool, str]:
    """Locate 开始游戏 in a PrintWindow capture (fixed relative position if the
    WebEngine content prints black) and click it with posted messages. Qt
    takes the click position from lParam, so the cursor is never touched."""
    cw, ch = win32.client_rect(hwnd)
    if cw <= 1 or ch <= 1:
        return False, "启动器窗口仍未还原"
    x = y = None
    how = "固定位置"
    img = win32.capture_window(hwnd)
    tpl = scanner.load_template(str(paths.TEMPLATE_DIR / START_TEMPLATE))
    if img is not None and tpl is not None:
        hits = matcher.find_all(img, tpl, 0.8, origin=(0, 0))
        if hits:
            x = int(hits[0]["cx"]) + START_OFFSET_X
            y = int(hits[0]["cy"])
            how = "识别"
    if x is None:
        x, y = int(cw * START_REL[0]), int(ch * START_REL[1])
    lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    _user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.1)
    _user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(0.08)
    _user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)
    return True, f"后台点击启动器开始游戏({how}) ({x},{y})"


def _wait_game(title: str, seconds: float) -> bool:
    for _ in range(int(seconds / 0.25)):
        nw = scanner.find_window(title)
        if nw and nw[4]:
            return True
        time.sleep(0.25)
    return False


def _click_start(hwnd) -> tuple[bool, str]:
    left, top, w, h = win32.window_rect(hwnd)
    if w <= 1 or h <= 1:
        return False, "启动器窗口仍未还原"
    img = capture.grab((left, top, w, h))
    tpl = scanner.load_template(str(paths.TEMPLATE_DIR / START_TEMPLATE))
    if tpl is None:
        return False, f"缺少模板 {START_TEMPLATE}"
    hits = matcher.find_all(img, tpl, 0.8, origin=(left, top))
    if not hits:
        return False, "启动器里找不到开始按钮（▶）"
    x = int(hits[0]["cx"]) + START_OFFSET_X
    y = int(hits[0]["cy"])
    clicker.click_at_restore(x, y, "left")
    return True, f"已点击启动器开始按钮 ({x},{y})"


def restart_game(title: str, fallback_exe: str = ""):
    """Kill the game and relaunch via the launcher. Returns (ok, message)."""
    win32.revert_all()                      # undo any invisible pseudo-minimize
    w = scanner.find_window(title)
    exe = fallback_exe
    pid = None
    if w and w[4]:
        pid = _pid(w[4])
        exe = _exe_path(pid) or exe
    if pid:
        _terminate(pid)
    else:
        _taskkill("Arknights.exe")
    _taskkill("PlatformProcess.exe")
    for _ in range(40):                     # wait for the old window to disappear
        if scanner.find_window(title) is None:
            break
        time.sleep(0.25)
    time.sleep(3.0)                         # let the launcher notice the game exited

    launcher = _launcher_exe(exe)
    # 1) background: no foreground/mouse needed, works with the screen off
    hwnd = _show_launcher_bg(launcher)
    if not hwnd:
        return False, "找不到或无法打开鹰角启动器"
    ok, msg = _click_start_bg(hwnd)
    if ok and _wait_game(title, 30):
        _user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_MINIMIZE, 0)
        return True, msg + "，游戏已启动，等待进入主界面"
    # 2) fallback: foreground activate + real click (needs an unlocked desktop)
    hwnd = _show_launcher(launcher)
    if not hwnd:
        return False, "后台点击无效，且无法前台打开鹰角启动器"
    ok, msg = _click_start(hwnd)
    _user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_MINIMIZE, 0)   # tuck launcher away
    if not ok:
        return False, "后台点击无效；前台：" + msg
    if _wait_game(title, 60):
        return True, "后台点击无效，已前台点击启动器重启游戏"
    return False, "已点开始，但 60s 内未出现游戏窗口"