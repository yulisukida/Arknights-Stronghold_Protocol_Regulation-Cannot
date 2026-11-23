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
        self._last_daily_restart = None   # date string of last scheduled restart
        self._scale = (1.0, 1.0)          # template scale (window x UI ratio)
        self._rscale = (1.0, 1.0)         # region/position scale (window only)
        self._last_hit_time = None        # last successful rule action (stuck watchdog)
        self._missing_since = None        # when the game window first went missing
        self._last_recovery = 0.0         # last missing-window relaunch attempt
        self._ui_scale = None             # calibrated UI render ratio (1.0 or 0.9)

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
        self._last_hit_time = time.time()
        self._missing_since = None
        self._last_recovery = 0.0
        self._ui_scale = None
        self._reset_counters()
        target = self._run_priority if self.settings.get("priority_mode", True) else self._run
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()
        self.events.put(("status", True))
        self._log("引擎已启动（F8 暂停/继续，F9 停止）")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=4.0)   # let the current OCR/click step finish
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
            if self._missing_since is None:
                self._missing_since = time.time()
            self._log(f"未找到窗口“{self.settings.get('window_title', '')}”，跳过本轮")
            return None
        self._missing_since = None
        self._pre_frame = frame if is_win else None
        self._hwnd = hwnd if is_win else None
        win_mode = (is_win and self.settings.get("use_window")
                    and not self.settings.get("emu_mode"))
        if win_mode:
            fh, fw = full.shape[:2]
            base = (fw / scanner.REF_W, fh / scanner.REF_H)
            if self._ui_scale is None:
                self._ui_scale = self._calibrate_ui_scale(full, frame, is_win, base)
        else:
            base = (1.0, 1.0)
        ui = self._ui_scale or 1.0
        self._scale = (base[0] * ui, base[1] * ui)   # template / pixel-offset scale
        self._rscale = base                          # region / position scale (window only)
        return full, frame, is_win

    def _calibrate_ui_scale(self, full, frame, is_win, base):
        """One-time UI render-ratio calibration (1.0 or 0.9).

        Matches every enabled template at both ratios on the startup screenshot;
        the ratio with the strongest confident match wins. Returns None until a
        recognizable screen appears, so it retries on later cycles.
        """
        best = {1.0: 0.0, 0.9: 0.0}
        for rule in self.rules:
            if not rule.get("enabled") or not rule.get("template"):
                continue
            for ui in (1.0, 0.9):
                sc = (base[0] * ui, base[1] * ui)
                hits = scanner.rule_hits(rule, full, frame, is_win, sc)
                if hits and hits[0]["score"] > best[ui]:
                    best[ui] = hits[0]["score"]
        if max(best.values()) < 0.75:
            return None
        # Bias to 1.0 (the common case). Only pick 0.9 when it is clearly and
        # confidently better, so a 1.0 machine is never mis-calibrated to 0.9
        # by a single noisy template (which would break scroll/Kannote matching).
        chosen = 0.9 if (best[0.9] >= 0.8 and best[0.9] > best[1.0] + 0.05) else 1.0
        self._log(f"倍率校准：{chosen}（1.0={best[1.0]:.2f} / 0.9={best[0.9]:.2f}）")
        return chosen

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
            self._maybe_daily_restart()
            self._maybe_stuck_restart()
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
        found = self._find_hit(rules, full, frame, is_win)
        if found is None:
            return None
        rule, hit, extra = found
        self._do_click(rule, hit, extra)
        return hit

    def _find_hit(self, rules, full, frame, is_win):
        """First matching rule in priority order -> (rule, hit, extra) or None."""
        for rule in rules:
            st = self._state.setdefault(rule["id"], {})
            hit = None
            extra = 1
            if rule.get("bright_slots") and not rule.get("template"):
                # structure-only rule: fire on the 6-module layout itself
                ok, _report = scanner.bright_gate(full, frame, is_win, rule, self._scale,
                                                  region_scale=self._rscale)
                if not ok:
                    continue
                hit = {"cx": 0.0, "cy": 0.0, "score": 1.0}
            else:
                hits = scanner.rule_hits(rule, full, frame, is_win, self._scale,
                                         region_scale=self._rscale)
                if hits is None:
                    if not st.get("warned"):
                        st["warned"] = True
                        self._log(f"[{rule['name']}] 模板图片不存在，已跳过")
                    continue
                if not hits:
                    st["armed"] = True      # screen gone -> rearm once-per-appearance
                    st["consec"] = 0        # banner gone -> reset watchdog streak
                    continue
                if rule.get("once_per_appearance") and not st.get("armed", True):
                    continue
                hit = hits[0]
            if rule.get("dark_slots"):
                target, report = scanner.first_dark_slot(
                    full, frame, is_win, rule["dark_slots"],
                    float(rule.get("dark_thresh", 100.0)),
                    rule.get("dark_offset") or [0, 85], self._scale,
                    region_scale=self._rscale)
                if target is None:
                    self._log(f"[{rule['name']}] 各格亮度: {report} -> 无暗格")
                    continue               # all rewards already chosen
                hit = {"cx": float(target[0]), "cy": float(target[1]),
                       "score": hit["score"]}
                extra = max(1, int(rule.get("dark_clicks", 1) or 1))
            if rule.get("once_per_appearance"):
                st["armed"] = False
            return rule, hit, extra
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
    def _maybe_daily_restart(self) -> None:
        """Scheduled daily restart (default 04:01, after the server reset).

        Fires once per day within a 14-minute grace window so a long cycle
        interval cannot skip the trigger minute; the date latch stops it from
        repeating every cycle inside that window.
        """
        hhmm = str(self.settings.get("daily_restart_hhmm", "04:01") or "")
        if ":" not in hhmm:
            return
        try:
            hh, mm = (int(x) for x in hhmm.split(":")[:2])
        except ValueError:
            return
        now = time.localtime()
        mins = now.tm_hour * 60 + now.tm_min
        target = hh * 60 + mm
        if not (target <= mins < target + 14):
            return
        today = time.strftime("%Y-%m-%d", now)
        if self._last_daily_restart == today:
            return
        self._last_daily_restart = today
        self._log(f"每日定时重启（{hhmm}）")
        self._restart_game()

    def _maybe_stuck_restart(self) -> None:
        """Global recovery: relaunch via the launcher when the game is gone,
        and restart when nothing has matched for a long time (stuck).

        - Window missing > grace (crash/exit): relaunch from the launcher. This
          is the same launcher-start used by active restarts, available any time
          the game disappears, not only on a deliberate restart.
        - No successful rule action for stuck_restart_minutes (default 20):
          restart. Covers both a frozen game and a long run of no hits.
        """
        now = time.time()
        grace = 30.0
        if self._missing_since is not None:
            if (now - self._missing_since >= grace
                    and now - self._last_recovery >= 60.0):
                self._last_recovery = now
                self._log("游戏窗口消失超 30s，从启动器拉起游戏")
                self._restart_game()
                return
        stuck_min = float(self.settings.get("stuck_restart_minutes", 20) or 0)
        if stuck_min > 0 and self._last_hit_time is not None:
            if now - self._last_hit_time >= stuck_min * 60.0:
                self._log(f"连续 {stuck_min:.0f} 分钟未命中，触发自动重启")
                self._restart_game()

    def _restart_game(self) -> None:
        from core import restart
        self._last_hit_time = time.time()   # grace period after any restart
        self._missing_since = None
        ok, msg = restart.restart_game(
            self.settings.get("window_title", ""),
            self.settings.get("game_exe", ""))
        self._log(f"重启游戏: {msg}")
        self._hwnd = None
        self._pre_frame = None

    def _do_upgrade(self, rule: dict) -> None:
        """Locate the (horizontally shifting) 升级 button once, then click it
        N times at that spot with a short 0.5s gap between clicks."""
        up_rule = {"template": rule["upgrade_template"],
                   "threshold": float(rule.get("upgrade_threshold", 0.8)),
                   "region": rule.get("upgrade_region")}
        n = int(rule.get("upgrade_clicks", 2))
        g = self._grab()
        if not g:
            self._log(f"[{rule['name']}] 未找到升级按钮，跳过升级")
            return
        f, fr, iw = g
        hits = scanner.rule_hits(up_rule, f, fr, iw, self._scale)
        if not hits:
            self._log(f"[{rule['name']}] 未找到升级按钮，跳过升级")
            return
        ux, uy = int(hits[0]["cx"]), int(hits[0]["cy"])
        for i in range(n):
            try:
                self._act(ux, uy, "left")
            except Exception as exc:
                self._log(f"[{rule['name']}] 升级点击失败: {exc}")
                break
            if i + 1 < n:
                time.sleep(0.5)
        self._log(f"[{rule['name']}] 已点击升级 {n} 次")

    def _do_click(self, rule: dict, hit: dict, extra_clicks: int = 1) -> None:
        st = self._state.setdefault(rule["id"], {})
        st.setdefault("clicks", 0)
        # watchdog: N consecutive matches -> kill & relaunch the game
        need = int(rule.get("consecutive_restart", 0) or 0)
        if need:
            st["consec"] = st.get("consec", 0) + 1
            if st["consec"] < need:
                self._log(f"[{rule['name']}] 等待重连 {st['consec']}/{need}")
                return
            st["consec"] = 0
            self._log(f"[{rule['name']}] 连续 {need} 次等待重连，重启游戏")
            self._restart_game()
            return
        if rule.get("battle_flow"):
            from core import battle
            battle.prep_phase(self)
            st["clicks"] += 1
            self._last_hit_time = time.time()
            self.events.put(("click", {"rule": rule["name"], "x": int(hit["cx"]),
                                       "y": int(hit["cy"]), "score": hit["score"]}))
            return
        scx, scy = self._scale
        dx, dy = (rule.get("offset") or [0, 0])[:2]
        x = int(hit["cx"]) + int(dx * scx)
        y = int(hit["cy"]) + int(dy * scy)

        if (self.settings.get("use_window") and not self._bg()
                and not self.settings.get("emu_mode")):
            scanner.activate_window(self.settings.get("window_title", ""))
            time.sleep(0.15)

        # upgrade-aware buy: read current gold (before buying) to decide upgrade
        upgrade_needed = False
        up_tpl = rule.get("upgrade_template")
        gold_gt = rule.get("upgrade_if_gold_gt")
        if up_tpl and gold_gt is not None:
            from core import ocr
            g0 = self._grab()
            if g0:
                f0, fr0, iw0 = g0
                gold = ocr.read_gold(f0, fr0, iw0, self._scale, rule.get("gold_region"))
                if gold is not None and gold > float(gold_gt):
                    upgrade_needed = True
                    self._log(f"[{rule['name']}] 金币 {gold} > {gold_gt}，买人后升级")
                else:
                    self._log(f"[{rule['name']}] 金币 {gold}，本次不升级")

        pre = rule.get("pre_clicks") or []
        delay = max(0.1, float(rule.get("pre_delay", 0.6)))
        for p in pre:
            px, py = int(p[0] * self._rscale[0]), int(p[1] * self._rscale[1])
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

        if upgrade_needed:
            self._do_upgrade(rule)

        kind = rule.get("click", "left")
        if kind == "scroll":
            reps = max(1, int(rule.get("scroll_repeat", 1) or 1))
            amt = int(rule.get("scroll", 5) or 5)
            dist = int((rule.get("swipe_dist", 150) or 150) * scy)
            settle = max(0.2, float(rule.get("scroll_settle", 0.5) or 0.5))
            # clickable (non-scroll) rules, priority order: re-check after each
            # swipe so a target (e.g. 坎诺特) is caught the moment it appears
            # instead of being scrolled past during a blind burst.
            click_rules = [r for r in self.rules
                           if r.get("enabled") and r.get("click") != "scroll"
                           and (r.get("template") or r.get("bright_slots"))
                           and not self._exhausted(r)]
            try:
                for i in range(reps):
                    self._act(x, y, "scroll", amt, dist)
                    time.sleep(settle)   # let residual inertia die before looking
                    if self._stop.is_set():
                        return
                    grabbed = self._grab()
                    if grabbed:
                        full, frame, is_win = grabbed
                        found = self._find_hit(click_rules, full, frame, is_win)
                        if found:
                            r2, hit2, extra2 = found
                            self._do_click(r2, hit2, extra2)
                            return       # target found & clicked -> stop scrolling
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
        self._last_hit_time = time.time()   # progress: resets the stuck watchdog
        self.events.put(("click", {"rule": rule["name"], "x": x, "y": y,
                                   "score": hit["score"]}))
        max_clicks = int(rule.get("max_clicks", 0) or 0)
        if max_clicks and st["clicks"] >= max_clicks:
            self.events.put(("done", rule["id"]))
