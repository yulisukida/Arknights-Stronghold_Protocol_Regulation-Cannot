"""Background click diagnostics for the Arknights PC client.

Usage:
    python test_bgclick.py [win_x win_y]          # 单击+双击+滚动+截图
    python test_bgclick.py 870 420 scroll         # 只测滚动（站在选择盟约界面）
    default target = 大厅“搜寻队友”按钮中心 (1123, 657)

Keep the game in the BACKGROUND (defocused), run this, and watch which
step makes the game react.

机制（MAA PostMessageWithWindowPos 同款）：点击瞬间游戏窗口会跳到鼠标
指针下方、点完再跳回原位——鼠标本身不动。看到窗口跳动才说明对齐成功。
"""

import ctypes
import sys
import time
from ctypes import wintypes

import pygetwindow as gw

from core import win32


def main() -> None:
    wx = int(sys.argv[1]) if len(sys.argv) > 1 else 1123
    wy = int(sys.argv[2]) if len(sys.argv) > 2 else 657

    admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    print("管理员权限:", admin, "(False 时所有消息都会被 UIPI 拦截，请用管理员终端重跑)")
    wins = gw.getWindowsWithTitle("明日方舟")
    if not wins:
        print("未找到窗口“明日方舟”")
        return
    w = wins[0]
    hwnd = w._hWnd
    was_min = win32.is_minimized(hwnd)
    win32.pseudo_minimize(hwnd)   # 最小化时先透明还原，PrintWindow/点击才有效
    wl, wt, ww, wh = win32.window_rect(hwnd)
    sx, sy = wl + wx, wt + wy
    cur = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(cur))
    print(f"原最小化={was_min}  现窗口 rect=({wl},{wt},{ww},{wh}) hwnd={hwnd}")
    print(f"鼠标现在屏幕位置=({cur.x},{cur.y})（全程不会动）")
    print(f"目标: 窗口相对({wx},{wy}) -> 屏幕({sx},{sy})")
    print("点击时窗口应瞬间跳到鼠标下方再跳回。若窗口没跳=SetWindowPos 被拦截。")

    def step(label, delay=3.0, dbl=False):
        print(f"[{label}] {delay:.0f} 秒内请盯着游戏画面…")
        time.sleep(delay)
        before = win32.window_rect(hwnd)
        win32.post_click(hwnd, sx, sy, "double" if dbl else "left")
        after = win32.window_rect(hwnd)
        print(f"[{label}] 已发送。窗口位置 前{before[:2]} 后{after[:2]}（应回到原位）。游戏有反应吗？")
        time.sleep(2)

    scroll_only = len(sys.argv) > 3 and sys.argv[3] == "scroll"
    if not scroll_only:
        step("A 单击")
        step("B 双击", dbl=True)

    print("[C 拖拽] 3 秒内盯着画面（站在选择盟约界面，坐标用策略网格中心）…")
    time.sleep(3)
    win32.post_swipe(hwnd, sx, sy + 75, sx, sy - 75)   # 向上拖=列表下滑
    print("[C 拖拽] 已发送一次上拖（列表应下滑）。画面滚动了吗？")
    time.sleep(2)

    img = win32.capture_window(hwnd)
    if img is None:
        print("[C 截图] PrintWindow 失败（最小化伪还原也没救回来）")
    else:
        import cv2
        cv2.imwrite("config/debug_bgclick.png", img)
        print(f"[C 截图] 成功 {img.shape[1]}x{img.shape[0]}，已存 config/debug_bgclick.png")

    if was_min:
        win32.revert_pseudo_minimize(hwnd)   # 测完收回最小化
    print("结束。把哪一步有反应告诉我；全无反应也要说，并附‘管理员权限’那行的值。")


if __name__ == "__main__":
    main()
