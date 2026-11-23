import cv2
import numpy as np


def find_all(screen_bgr: np.ndarray, template_bgr: np.ndarray,
             threshold: float = 0.85, origin=(0, 0), max_results: int = 10,
             scales=(1.0,), color=False):
    """Template match on a screenshot; returns screen-space hits, strongest first.

    origin is the (left, top) of the grabbed region, so coordinates are absolute.
    `scales` are extra multipliers applied to the template size: the game can
    render its UI smaller/larger than the window size alone implies (different
    render-resolution settings), so we search a few scales and keep the best.
    Nearby duplicate peaks are suppressed with NMS sized to the template.
    """
    ox, oy = origin
    sh, sw = screen_bgr.shape[:2]
    # color=True matches in BGR so same-shaped buttons of different colors
    # (red 准备就绪 vs grey 取消准备) are not confused; default grayscale is
    # more tolerant of lighting/tint variation for ordinary templates.
    if color:
        src, t0 = screen_bgr, template_bgr
    else:
        src = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
        t0 = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
    th0, tw0 = t0.shape[:2]

    peaks = []
    for m in scales:
        tw, th = int(round(tw0 * m)), int(round(th0 * m))
        if tw < 8 or th < 8 or tw > sw or th > sh:
            continue
        tpl = cv2.resize(t0, (tw, th), interpolation=cv2.INTER_AREA) if m != 1.0 else t0
        res = cv2.matchTemplate(src, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        for y, x in zip(ys, xs):
            peaks.append((float(res[y, x]), int(x), int(y), tw, th))
    peaks.sort(key=lambda p: p[0], reverse=True)

    hits = []
    for score, x, y, tw, th in peaks:
        suppression = max(tw, th) // 2
        if any(abs(x - hx) < suppression and abs(y - hy) < suppression
               for _s, hx, hy, _w, _h in hits):
            continue
        hits.append((score, x, y, tw, th))
        if len(hits) >= max_results:
            break

    return [
        {
            "x": ox + x, "y": oy + y, "w": tw, "h": th,
            "cx": ox + x + tw / 2.0, "cy": oy + y + th / 2.0,
            "score": round(score, 4),
        }
        for score, x, y, tw, th in hits
    ]
