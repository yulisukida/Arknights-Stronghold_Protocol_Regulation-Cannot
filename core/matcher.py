import cv2
import numpy as np


def find_all(screen_bgr: np.ndarray, template_bgr: np.ndarray,
             threshold: float = 0.85, origin=(0, 0), max_results: int = 10):
    """Template match on a screenshot; returns screen-space hits, strongest first.

    origin is the (left, top) of the grabbed region, so coordinates are absolute.
    Nearby duplicate peaks are suppressed with NMS sized to the template.
    """
    ox, oy = origin
    th, tw = template_bgr.shape[:2]
    sh, sw = screen_bgr.shape[:2]
    if th > sh or tw > sw:
        return []

    src = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
    tpl = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
    res = cv2.matchTemplate(src, tpl, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    order = np.argsort(res[ys, xs])[::-1]

    hits = []
    suppression = max(tw, th) // 2
    for i in order:
        x, y = int(xs[i]), int(ys[i])
        if any(abs(x - hx) < suppression and abs(y - hy) < suppression for hx, hy, *_ in hits):
            continue
        score = float(res[y, x])
        hits.append((x, y, score))
        if len(hits) >= max_results:
            break

    return [
        {
            "x": ox + x, "y": oy + y, "w": tw, "h": th,
            "cx": ox + x + tw / 2.0, "cy": oy + y + th / 2.0,
            "score": round(score, 4),
        }
        for x, y, score in hits
    ]
