"""Emulator backend: capture and inject input through ADB.

The Android screen is captured with `screencap` (true background capture,
independent of the emulator window state) and touches are injected with
`input tap/swipe` into the Android input stream — the Windows mouse and
keyboard are never touched.

Works with old bundled adb (no exec-out) via a pull fallback, and always
targets the configured serial explicitly.
"""

import os
import subprocess
import tempfile

import cv2
import numpy as np


def _base(adb: str, serial: str):
    args = [adb]
    if serial:
        args += ["-s", serial]
    return args


def _run(args, timeout: float = 15.0):
    flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
    return subprocess.run(args, capture_output=True, timeout=timeout,
                          creationflags=flags)


def connect(addr: str, adb: str = "adb"):
    try:
        r = _run([adb, "connect", addr], timeout=8)
        out = r.stdout.decode(errors="ignore").strip()
        return ("connected" in out or "already" in out), out
    except Exception as exc:
        return False, str(exc)


def last_error(adb: str, serial: str) -> str:
    try:
        r = _run(_base(adb, serial) + ["get-state"], timeout=8)
        return (r.stdout + r.stderr).decode(errors="ignore").strip() or "ok"
    except Exception as exc:
        return str(exc)


def screencap(adb: str = "adb", serial: str = ""):
    """BGR ndarray of the Android screen, or None."""
    png = None
    try:
        r = _run(_base(adb, serial) + ["exec-out", "screencap", "-p"])
        if r.returncode == 0 and r.stdout[:4] == b"\x89PNG":
            png = r.stdout
    except Exception:
        pass
    if png is None:
        # old adb without exec-out: write on device, pull back
        remote = "/sdcard/screenbot_cap.png"
        try:
            _run(_base(adb, serial) + ["shell", "screencap", "-p", remote],
                 timeout=20)
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            r = _run(_base(adb, serial) + ["pull", remote, tmp.name],
                     timeout=20)
            data = open(tmp.name, "rb").read() if os.path.getsize(tmp.name) else b""
            os.remove(tmp.name)
            _run(_base(adb, serial) + ["shell", "rm", remote])
            if data[:4] == b"\x89PNG":
                png = data
            else:
                png_err = r.stderr.decode(errors="ignore").strip()
        except Exception as exc:
            png_err = str(exc)
    if png is None:
        return None
    return cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)


def tap(x: int, y: int, kind: str = "left", adb: str = "adb",
        serial: str = "") -> None:
    args = _base(adb, serial) + ["shell", "input", "tap", str(int(x)), str(int(y))]
    _run(args)
    if kind == "double":
        _run(args)


def scroll(x: int, y: int, notches: int, adb: str = "adb",
           serial: str = "") -> None:
    """Swipe up on screen = scroll content down."""
    d = max(60, int(abs(notches)) * 15)
    y0 = int(y) + d // 2
    y1 = max(0, int(y) - d // 2)
    _run(_base(adb, serial) + ["shell", "input", "swipe", str(int(x)), str(y0),
                               str(int(x)), str(y1), "300"])
