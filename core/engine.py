import queue
import threading
import time
import traceback

from . import adb, clicker, scanner, win32


class Engine:
    """Background scan-and-click loop over a list of rule dicts.

    Events (queue.Queue of (kind, payload)):
      ("log", text) | ("click", {rule, x, y, score}) | ("done", rule_id)
      ("status", bool running)
    """

    TICK = 0.05

    def __init__(self):
        self.rules: list[dict] = []
        self.settings = {"priority_mode": True, "cycle_interval": 10.0}
        self.events = queue.Queue()
        self._stop = threading.Event()
        self._stop.set()
        self._thread = None
        self._state = {}              # rule id -> {next_due, cooldown_until, clicks}
        self._cycle = 0
        self._pre_frame = None        # window origin while in window mode
        self._hwnd = None

    # ------------------------------------------------------------------ API
    def set_rules(self, rules: list[dict]) -> None:
        self.rules = rules
        if not self.is_running():
            self._state = {}

    def set_settings(self, settings: dict) -> None:
        self.settings = settings

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._cycle = 0
        self._reset_counters()
        target = self._run_priority if self.settings.get("priority_mode", True) else self._run
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()
        self.events.put(("status", True))
        self._log("引擎已启动（F8 暂停/继续，F9 停止）")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        win32.revert_all()
        self.events.put(("status", False))
        self._log("引擎已停止")

    # -------------------------------------------------------------- internals
    def _reset_counters(self) -> None:
        for r in self.rules:
            st = self._state.setdefault(r["id"], {})
            st["clicks"] = 0
            st["next_due"] = 0.0
            st["cooldown_until"] = 0.0

    def _log(self, text: str) -> None:
        self.events.put(("log", text))

    def _grab(self):
        """Frame for this scan; sets _pre_frame/_hwnd. Returns (full, frame, is_win)."""
        full, frame, is_win, hwnd = scanner.grab_frame(self.settings)
        if full is None:
            self._log(f"未找到窗口“{self.settings.get('window_title', '')}”，跳过本轮")
            return None
        self._pre_frame = frame if is_win else None
        self._hwnd = hwnd if is_win else None
        return full, frame, is_win

    def _bg(self) -> bool:
        return bool(self._hwnd and self.settings.get("background_mode")
                    and self.settings.get("use_window"))

    def _act(self, x: int, y: int, kind: str, scroll_amount: int = 5,
             swipe_dist: int = 150) -> None:
        if self.settings.get("emu_mode"):
            exe = self.settings.get("adb_exe", "adb")
            serial = self.settings.get("adb_addr", "")
            if kind == "scroll":
                adb.scroll(x, y, scroll_amount, exe, serial)
            elif kind != "none":
                adb.tap(x, y, kind, exe, serial)
            return
        if self._bg():
            if self.settings.get("bg_click_postmsg", True):
                if kind == "scroll":
                    # drag up to scroll the list down (MAA swipe, not wheel)
                    d = max(20, int(swipe_dist))
                    win32.post_swipe(self._hwnd, x, y + d // 2, x, y - d // 2)
                elif kind != "none":
                    win32.post_click(self._hwnd, x, y, kind)
            else:
                # Unity clients on Raw Input ignore posted messages
                if kind == "scroll":
                    clicker.scroll_at_restore(x, y, scroll_amount)
                elif kind != "none":
                    clicker.click_at_restore(x, y, kind)
            return
        if kind == "scroll":
            clicker.scroll_at(x, y, scroll_amount)
        elif kind != "none":
            clicker.click_at(x, y, kind)

    # ---------------------------------------------------------- priority mode
    def _run_priority(self) -> None:
        """One cycle = one screenshot; rules top-down, first hit acts."""
        while not self._stop.is_set():
            started = time.time()
            interval = max(0.5, float(self.settings.get("cycle_interval", 10.0)))
            rules = [r for r in self.rules
                     if r.get("enabled")
                     and (r.get("template") or r.get("bright_slots"))
                     and not self._exhausted(r)]
            try:
                self._log(f"— 第 {self._cycle + 1} 轮：检查 {len(rules)} 条规则")
                hit = self._scan_once(rules) if rules else None
                if hit is None:
                    self._log("本轮无命中")
            except Exception:
                self._log(f"扫描出错: {traceback.format_exc(limit=1)}")
            self._cycle += 1
            while not self._stop.is_set() and time.time() - started < interval:
                time.sleep(self.TICK)

    def _scan_once(self, rules):
        grabbed = self._grab()
        if grabbed is None:
            return None
        full, frame, is_win = grabbed
        for rule in rules:
            st = self._state.setdefault(rule["id"], {})
            hit = None
            extra = 1
            if rule.get("bright_slots") and not rule.get("template"):
                # structure-only rule: fire on the 6-module layout itself
                ok, _report = scanner.bright_gate(full, frame, is_win, rule)
                if not ok:
                    continue
                hit = {"cx": 0.0, "cy": 0.0, "score": 1.0}
            else:
                hits = scanner.rule_hits(rule, full, frame, is_win)
                if hits is None:
                    if not st.get("warned"):
                        st["warned"] = True
                        self._log(f"[{rule['name']}] 模板图片不存在，已跳过")
                    continue
                if not hits:
                    st["armed"] = True      # screen gone -> rearm once-per-appearance
                    continue
                if rule.get("once_per_appearance") and not st.get("armed", True):
                    continue
                hit = hits[0]
            if rule.get("dark_slots"):
                target, report = scanner.first_dark_slot(
                    full, frame, is_win, rule["dark_slots"],
                    float(rule.get("dark_thresh", 100.0)),
                    rule.get("dark_offset") or [0, 85])
                if target is None:
                    self._log(f"[{rule['name']}] 各格亮度: {report} -> 无暗格")
                    continue               # all rewards already chosen
                hit = {"cx": float(target[0]), "cy": float(target[1]),
                       "score": hit["score"]}
                extra = max(1, int(rule.get("dark_clicks", 1) or 1))
            if rule.get("once_per_appearance"):
                st["armed"] = False
            self._do_click(rule, hit, extra)
            return hit
        return None

    def _exhausted(self, rule) -> bool:
        max_clicks = int(rule.get("max_clicks", 0) or 0)
        st = self._state.get(rule["id"], {})
        return bool(max_clicks and st.get("clicks", 0) >= max_clicks)

    # --------------------------------------------------------- independent mode
    def _run(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            for rule in list(self.rules):
                if self._stop.is_set():
                    return
                if self._due(rule, now):
                    self._process(rule, now)
            time.sleep(self.TICK)

    def _due(self, rule: dict, now: float) -> bool:
        if not rule.get("enabled") or not rule.get("template"):
            return False
        st = self._state.setdefault(rule["id"], {})
        st.setdefault("clicks", 0)
        st.setdefault("cooldown_until", 0.0)
        st.setdefault("next_due", 0.0)
        max_clicks = int(rule.get("max_clicks", 0) or 0)
        if max_clicks and st["clicks"] >= max_clicks:
            return False
        return now >= st["next_due"] and now >= st["cooldown_until"]

    def _process(self, rule: dict, now: float) -> None:
        st = self._state[rule["id"]]
        st["next_due"] = now + max(0.2, float(rule.get("interval", 1.0)))
        try:
            grabbed = self._grab()
            if grabbed is None:
                return
            full, frame, is_win = grabbed
            hits = scanner.rule_hits(rule, full, frame, is_win)
        except Exception:
            self._log(f"[{rule['name']}] 扫描出错: {traceback.format_exc(limit=1)}")
            return
        if hits is None:
            if not st.get("warned"):
                st["warned"] = True
                self._log(f"[{rule['name']}] 模板图片不存在，已跳过")
            return
        if not hits:
            return
        self._do_click(rule, hits[0])
        st["cooldown_until"] = time.time() + max(0.0, float(rule.get("cooldown", 2.0)))

    # ---------------------------------------------------------------- actions
    def _do_click(self, rule: dict, hit: dict, extra_clicks: int = 1) -> None:
        st = self._state.setdefault(rule["id"], {})
        st.setdefault("clicks", 0)
        dx, dy = (rule.get("offset") or [0, 0])[:2]
        x = int(hit["cx"]) + int(dx)
        y = int(hit["cy"]) + int(dy)

        if (self.settings.get("use_window") and not self._bg()
                and not self.settings.get("emu_mode")):
            scanner.activate_window(self.settings.get("window_title", ""))
            time.sleep(0.15)

        pre = rule.get("pre_clicks") or []
        delay = max(0.1, float(rule.get("pre_delay", 0.6)))
        for p in pre:
            px, py = int(p[0]), int(p[1])
            if self._pre_frame:
                px += self._pre_frame[0]
                py += self._pre_frame[1]
            try:
                self._act(px, py, "left")
            except Exception as exc:
                self._log(f"[{rule['name']}] 预点击失败: {exc}")
                return
            time.sleep(delay)
        if pre:
            self._log(f"[{rule['name']}] 已预点击 {len(pre)} 次")

        kind = rule.get("click", "left")
        if kind == "scroll":
            reps = max(1, int(rule.get("scroll_repeat", 1) or 1))
            amt = int(rule.get("scroll", 5) or 5)
            dist = int(rule.get("swipe_dist", 150) or 150)
            try:
                for i in range(reps):
                    self._act(x, y, "scroll", amt, dist)
                    if i + 1 < reps:
                        time.sleep(0.35)
            except Exception as exc:
                self._log(f"[{rule['name']}] 滚动失败: {exc}")
                return
        elif kind != "none":
            try:
                self._act(x, y, kind)
            except Exception as exc:
                self._log(f"[{rule['name']}] 点击失败: {exc}")
                return

        for _ in range(max(0, extra_clicks - 1)):
            time.sleep(1.0)
            try:
                self._act(x, y, kind if kind != "none" else "left",
                          int(rule.get("scroll", 5) or 5),
                          int(rule.get("swipe_dist", 150) or 150))
            except Exception as exc:
                self._log(f"[{rule['name']}] 重复点击失败: {exc}")
                return

        st["clicks"] += 1
        self.events.put(("click", {"rule": rule["name"], "x": x, "y": y,
                                   "score": hit["score"]}))
        max_clicks = int(rule.get("max_clicks", 0) or 0)
        if max_clicks and st["clicks"] >= max_clicks:
            self.events.put(("done", rule["id"]))
