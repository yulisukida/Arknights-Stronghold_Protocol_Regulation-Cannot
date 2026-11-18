"""Region snipping overlay: screenshot the whole primary monitor, let the user
drag a rectangle, return screen coordinates (and optionally save a template)."""

import time

import numpy as np
import tkinter as tk
from PIL import Image, ImageTk

from core import capture, paths

MIN_SIZE = 4


def _pick_rectangle(img_pil, monitor) -> tuple | None:
    """Show `img_pil` fullscreen; drag to select. Returns (l, t, w, h) or None."""
    left, top, width, height = monitor
    root = tk._default_root
    win = tk.Toplevel(root)
    win.geometry(f"{width}x{height}+{left}+{top}")
    win.attributes("-topmost", True)
    win.overrideredirect(True)
    win.focus_force()

    photo = ImageTk.PhotoImage(img_pil)
    canvas = tk.Canvas(win, width=width, height=height, highlightthickness=0,
                       cursor="crosshair")
    canvas.pack()
    canvas.create_image(0, 0, image=photo, anchor="nw")
    # dim everything except the selection: four grey strips around the rubber band
    dims = [canvas.create_rectangle(0, 0, 0, 0, fill="black", stipple="gray50",
                                    outline="", state="hidden")
            for _ in range(4)]
    band = canvas.create_rectangle(0, 0, 0, 0, outline="#00bfff", width=2)
    info = canvas.create_text(10, 10, anchor="nw", fill="white",
                              font=("Consolas", 12),
                              text="拖框选择区域 · Enter 确认 · Esc 取消")

    result = {"box": None}
    start = {"x": None, "y": None}

    def redraw(x0, y0, x1, y1):
        l, t = min(x0, x1), min(y0, y1)
        r, b = max(x0, x1), max(y0, y1)
        canvas.coords(band, l, t, r, b)
        d_left, d_right, d_top, d_bottom = dims
        canvas.coords(d_left, 0, 0, l, height)
        canvas.coords(d_right, r, 0, width, height)
        canvas.coords(d_top, l, 0, r, t)
        canvas.coords(d_bottom, l, b, r, height)
        for d in dims:
            canvas.itemconfigure(d, state="normal")
        canvas.tag_raise(band)
        canvas.tag_raise(info)
        canvas.itemconfigure(info, text=f"框选 {r-l}x{b-t} · Enter 确认 · Esc 取消")

    def press(e):
        start["x"], start["y"] = e.x, e.y

    def drag(e):
        if start["x"] is not None:
            redraw(start["x"], start["y"], e.x, e.y)

    def release(e):
        if start["x"] is None:
            return
        l, t = min(start["x"], e.x), min(start["y"], e.y)
        w, h = abs(e.x - start["x"]), abs(e.y - start["y"])
        if w >= MIN_SIZE and h >= MIN_SIZE:
            result["box"] = (left + l, top + t, w, h)
            win.destroy()

    def key(e):
        if e.keysym == "Escape":
            win.destroy()
        elif e.keysym in ("Return", "KP_Enter") and result["box"]:
            win.destroy()

    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<ButtonRelease-1>", release)
    win.bind("<Key>", key)
    win.grab_set()
    root.wait_window(win)
    return result["box"]


def snip_region(parent) -> tuple[tuple, np.ndarray] | None:
    """Returns (screen box (l, t, w, h), BGR crop) or None if cancelled.

    The crop comes from the one screenshot taken with all windows hidden,
    so the editor GUI never leaks into templates.
    """
    parent.withdraw()
    parent.update_idletasks()
    time.sleep(0.2)  # let the window get out of the screenshot
    try:
        monitor = capture.primary_monitor()
        left, top, width, height = monitor
        screen = capture.grab(monitor)
        box = _pick_rectangle(
            Image.fromarray(np.ascontiguousarray(screen[:, :, ::-1])), monitor)
        if not box:
            return None
        bl, bt, bw, bh = box
        crop = screen[bt - top: bt - top + bh, bl - left: bl - left + bw]
        return box, crop
    finally:
        parent.deiconify()


def snip_template(parent, name_hint: str = "tpl") -> tuple[str, tuple] | None:
    """Snip and save a PNG into templates/. Returns (path, region) or None."""
    picked = snip_region(parent)
    if not picked:
        return None
    box, crop = picked
    paths.ensure_dirs()
    fname = f"{name_hint}_{time.strftime('%H%M%S')}.png"
    path = paths.TEMPLATE_DIR / fname
    Image.fromarray(np.ascontiguousarray(crop[:, :, ::-1])).save(path)
    return str(path), box
