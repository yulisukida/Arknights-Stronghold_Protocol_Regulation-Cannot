"""Small offline OCR module (RapidOCR) used to read the gold counter.

The gold number sits at a fixed window-relative position (a yellow hexagon
badge, bottom-right). We crop just the number area, turn the yellow-on-dark
digits into dark-on-white, upscale, and OCR. Only digits are kept.
"""
import cv2

_ocr = None


def _engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


# Native 1280x720 client box around the gold NUMBER (MAA ShopGoldOcr basis).
DEFAULT_GOLD_REGION = [1190, 512, 43, 32]


def _crop(full, region, scale):
    scx, scy = scale
    h, w = full.shape[:2]
    rl, rt = int(region[0] * scx), int(region[1] * scy)
    rw, rh = int(region[2] * scx), int(region[3] * scy)
    x0, y0 = max(0, rl), max(0, rt)
    x1, y1 = min(w, rl + rw), min(h, rt + rh)
    if x1 <= x0 or y1 <= y0:
        return None
    return full[y0:y1, x0:x1]


def read_text(full, region, scale=(1.0, 1.0), invert=False, zoom=2, pad=0):
    """OCR a region; return list of (text, center_x, center_y) in capture coords.
    pad: border (px, after zoom) added around the crop; tiny isolated glyphs
    are often missed by the text detector without some margin."""
    crop = _crop(full, region, scale)
    if crop is None:
        return []
    img = crop
    if invert:
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, bw = cv2.threshold(g, 120, 255, cv2.THRESH_BINARY_INV)
        img = cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR)
    big = cv2.resize(img, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
    if pad:
        big = cv2.copyMakeBorder(big, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    try:
        res, _ = _engine()(big)
    except Exception:
        return []
    out = []
    scx, scy = scale
    ox, oy = region[0] * scx, region[1] * scy
    for box, text, _conf in (res or []):
        xs = [p[0] - pad for p in box]
        ys = [p[1] - pad for p in box]
        cx = ox + (sum(xs) / len(xs)) / zoom
        cy = oy + (sum(ys) / len(ys)) / zoom
        out.append((text, cx, cy))
    return out


def read_number(full, region, scale=(1.0, 1.0)):
    crop = _crop(full, region, scale)
    if crop is None:
        return None
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(g, 120, 255, cv2.THRESH_BINARY_INV)
    big = cv2.resize(bw, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    try:
        res, _ = _engine()(big)
    except Exception:
        return None
    if not res:
        return None
    txt = "".join(r[1] for r in res)
    digits = "".join(c for c in txt if c.isdigit())
    return int(digits) if digits else None


def read_gold(full, frame, is_win, scale=(1.0, 1.0), region=None):
    """Return the gold amount as int, or None if unreadable."""
    region = region or DEFAULT_GOLD_REGION
    scx, scy = scale
    h, w = full.shape[:2]
    if is_win:
        rl, rt = int(region[0] * scx), int(region[1] * scy)
    else:
        rl, rt = int(region[0]) - frame[0], int(region[1]) - frame[1]
    rw, rh = int(region[2] * scx), int(region[3] * scy)
    x0, y0 = max(0, rl), max(0, rt)
    x1, y1 = min(w, rl + rw), min(h, rt + rh)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = full[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY_INV)
    big = cv2.resize(bw, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    try:
        res, _ = _engine()(big)
    except Exception:
        return None
    if not res:
        return None
    txt = "".join(r[1] for r in res)
    digits = "".join(c for c in txt if c.isdigit())
    return int(digits) if digits else None