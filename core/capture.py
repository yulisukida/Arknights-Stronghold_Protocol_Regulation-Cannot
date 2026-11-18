import ctypes

import mss
import numpy as np


def set_dpi_awareness() -> None:
    """Match screen pixel coordinates with mouse coordinates on scaled displays."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def primary_monitor() -> tuple[int, int, int, int]:
    with mss.mss() as sct:
        m = sct.monitors[1]
        return m["left"], m["top"], m["width"], m["height"]


def clamp_region(region) -> tuple[int, int, int, int]:
    """Keep a (left, top, width, height) region inside the primary monitor."""
    left, top, w, h = primary_monitor()
    rl, rt, rw, rh = (int(v) for v in region)
    rl = max(left, rl)
    rt = max(top, rt)
    rw = max(1, min(rw, left + w - rl))
    rh = max(1, min(rh, top + h - rt))
    return rl, rt, rw, rh


def grab(region=None) -> np.ndarray:
    """Screenshot (BGR ndarray). region=None grabs the full primary monitor."""
    with mss.mss() as sct:
        if region is None:
            box = sct.monitors[1]
        else:
            rl, rt, rw, rh = clamp_region(region)
            box = {"left": rl, "top": rt, "width": rw, "height": rh}
        img = np.array(sct.grab(box))
    return img[:, :, :3]
