import ctypes
import queue
import sys
import time

import tkinter as tk
from tkinter import messagebox, ttk

from core import paths, store
from core.engine import Engine
from core.hotkey import Hotkeys

from .rule_editor import RuleEditor

CLICK_NAMES = {"left": "左键", "right": "右键", "double": "双击",
               "scroll": "滚轮↓", "none": "仅提醒"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("卫戍协议坎诺特挂机工具")
        try:
            self.iconbitmap(default=str(paths.ICON_FILE))
        except Exception:
            pass
        self.geometry("860x640")
        self.minsize(720, 520)

        self.settings = store.load_settings()
        self.rules = store.load_rules(bool(self.settings.get("emu_mode")))
        self.engine = Engine()
        self.engine.set_rules(self.rules)
        self.engine.set_settings(self.settings)
        self.hotkeys = Hotkeys(lambda: self._on_hotkey("toggle"),
                               lambda: self._on_hotkey("stop"))
        self._control_q = queue.Queue()

        self._build_widgets()
        self._refresh_tree()
        self.hotkeys.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)
        self._log(f"已加载 {len(self.rules)} 条规则。热键：F8 启动/暂停 · F9 停止。")
        if sys.platform == "win32":
            try:
                is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            except Exception:
                is_admin = True
            if not is_admin:
                self._log("⚠ 当前非管理员权限：若游戏客户端以管理员运行，"
                          "点击和 F8 热键会被系统拦截。请用管理员终端启动本程序。")

    # ------------------------------------------------------------------ layout
    def _build_widgets(self):
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")

        self.run_btn = ttk.Button(bar, text="▶ 启动 (F8)", command=self._start)
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text="■ 停止 (F9)", command=self._stop,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=(4, 4))
        self.test_restart_btn = ttk.Button(bar, text="测试重启(锁屏)",
                                           command=self._test_restart)
        self.test_restart_btn.pack(side="left", padx=(0, 12))

        opt = ttk.Frame(bar)
        opt.pack(side="right")
        self.win_var = tk.BooleanVar(value=True)   # 窗口模式常开，界面不再提供开关
        self.bg_var = tk.BooleanVar(value=bool(self.settings.get("background_mode")))
        ttk.Checkbutton(opt, text="后台模式", variable=self.bg_var,
                        command=self._on_bg_toggle).pack(side="left", padx=(0, 2))
        self.bgc_var = tk.BooleanVar(value=bool(self.settings.get("bg_click_postmsg", True)))
        ttk.Checkbutton(opt, text="postmsg点击", variable=self.bgc_var,
                        command=self._save_settings).pack(side="left", padx=(0, 2))
        self.title_var = tk.StringVar(
            value=self.settings.get("window_title", ""))
        ttk.Entry(opt, textvariable=self.title_var, width=10).pack(side="left")
        ttk.Separator(opt, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(opt, text="周期(s)").pack(side="left", padx=(8, 0))
        self.cycle_var = tk.DoubleVar(value=float(self.settings["cycle_interval"]))
        ttk.Spinbox(opt, from_=1, to=600, increment=1, width=5,
                    textvariable=self.cycle_var,
                    command=self._save_settings).pack(side="left", padx=2)
        ttk.Label(opt, text="热键 F8=启停  F9=停止").pack(side="left", padx=8)

        cols = ("on", "name", "tpl", "thr", "act", "region", "iv", "cd", "max",
                "hits", "score")
        heads = ("启用", "名称", "模板", "阈值", "动作", "区域", "间隔s",
                 "冷却s", "上限", "已点", "最近分")
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=10)
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text="#")
        self.tree.column("#0", width=30, anchor="center")
        widths = (46, 130, 130, 44, 52, 70, 50, 50, 44, 44, 60)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="center")
        self.tree.column("name", anchor="w")
        self.tree.column("tpl", anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._edit())

        log_frame = ttk.LabelFrame(self, text="日志（仅命中）", padding=4)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        self.logbox = tk.Text(log_frame, height=12, state="disabled",
                              font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
        self.logbox.pack(fill="both", expand=True)

        self.status = tk.StringVar(value="● 已停止")
        ttk.Label(self, textvariable=self.status, padding=(10, 2)).pack(fill="x")

    # ------------------------------------------------------------------ rules
    def _persist(self):
        store.save_rules(self.rules, bool(self.settings.get("emu_mode")))

    def _reload_rules(self):
        self.rules = store.load_rules(bool(self.settings.get("emu_mode")))
        self.engine.set_rules(self.rules)
        self._refresh_tree()

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def _edit(self):
        i = self._selected()
        if i is None:
            return
        ed = RuleEditor(self, self.rules[i], settings=self.settings)
        self.wait_window(ed)
        if ed.result:
            self.rules[i] = ed.result
            self._after_rule_change()

    def _on_bg_toggle(self):
        self._save_settings()
        if not (self.bg_var.get() and self.win_var.get()):
            from core import win32
            win32.revert_all()
            return
        from core import scanner, win32
        win = scanner.find_window(self.title_var.get().strip())
        if not win or not win[4]:
            self._log("后台模式自检：未找到游戏窗口或句柄")
            return
        img = win32.capture_window(win[4])
        if img is None:
            self._log("后台模式自检：PrintWindow 取不到游戏画面（Unity 常见），"
                      "将回退屏幕截取——游戏须保持可见，但点击仍走后台投递")
        else:
            import cv2
            from core import paths
            dbg = paths.CONFIG_DIR / "debug_bg.png"
            cv2.imwrite(str(dbg), img)
            self._log(f"后台模式自检：PrintWindow 正常，画面 {img.shape[1]}x{img.shape[0]}，"
                      f"已存 {dbg}（请把这张图发给开发者核对）")

    def _save_settings(self):
        self.settings = {
            "priority_mode": True,
            "cycle_interval": float(self.cycle_var.get()),
            "use_window": self.win_var.get(),
            "window_title": self.title_var.get().strip(),
            "background_mode": self.bg_var.get(),
            "bg_click_postmsg": self.bgc_var.get(),
        }
        store.save_settings(self.settings)
        self.engine.set_settings(self.settings)

    def _after_rule_change(self):
        self._persist()
        self.engine.set_rules(self.rules)
        self._refresh_tree()

    def _refresh_tree(self):
        runs = getattr(self.engine, "_state", {})
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.rules):
            st = runs.get(r["id"], {})
            region = "全屏" if not r.get("region") else \
                f"{r['region'][0]},{r['region'][1]}"
            self.tree.insert("", "end", iid=str(i), text=str(i + 1), values=(
                "☑" if r["enabled"] else "☐", r["name"],
                r["template"].replace("\\", "/").rsplit("/", 1)[-1],
                r["threshold"], CLICK_NAMES.get(r["click"], r["click"]),
                region, r["interval"], r["cooldown"], r["max_clicks"],
                st.get("clicks", 0), st.get("last_score", "-"),
            ))

    # ------------------------------------------------------------------ control
    def _start(self):
        if not any(r["enabled"] and r["template"] for r in self.rules):
            messagebox.showwarning("启动", "没有启用且带模板的规则")
            return
        self._save_settings()
        self._refresh_tree()
        self.engine.start()
        self.run_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        self.status.set("● 运行中")

    def _stop(self):
        self.engine.stop()
        self.run_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])
        self.status.set("● 已停止")
        self._refresh_tree()

    def _test_restart(self):
        """Lock the PC, then kill + relaunch the game through the launcher
        while locked. Unlock later and check the log / whether the game is up.
        The engine is paused during the test and resumed afterwards."""
        if not messagebox.askyesno(
                "测试重启",
                "将立即锁屏，然后在锁屏状态下关闭游戏并通过启动器重新启动。\n"
                "游戏当前进度会丢失。继续？"):
            return
        import ctypes
        import threading
        from core import restart
        was_running = self.engine.is_running()
        if was_running:
            self._stop()
        self.test_restart_btn.state(["disabled"])
        title = self.title_var.get().strip() or self.settings.get("window_title", "")
        exe = self.settings.get("game_exe", "")

        def work():
            q = self.engine.events
            q.put(("log", "[测试重启] 锁屏，5 秒后开始重启"))
            ctypes.windll.user32.LockWorkStation()
            time.sleep(5)
            t0 = time.strftime("%H:%M:%S")
            try:
                ok, msg = restart.restart_game(title, exe)
            except Exception as exc:
                ok, msg = False, f"异常: {exc}"
            q.put(("log", f"[测试重启] {t0} 开始 -> {time.strftime('%H:%M:%S')} "
                          f"{'成功' if ok else '失败'}: {msg}"))
            self.after(0, lambda: self._test_restart_done(was_running))

        threading.Thread(target=work, daemon=True).start()

    def _test_restart_done(self, resume):
        self.test_restart_btn.state(["!disabled"])
        if resume:
            self._start()

    def _toggle(self):
        if self.engine.is_running():
            self._stop()
        else:
            self._start()

    def _on_hotkey(self, kind):
        self._control_q.put(kind)

    def _poll(self):
        try:
            while True:
                cmd = self._control_q.get_nowait()
                if cmd == "toggle":
                    self._toggle()
                elif cmd == "stop":
                    if self.engine.is_running():
                        self._stop()
        except queue.Empty:
            pass
        self._drain_engine_events()
        if self.engine.is_running():
            self._refresh_tree()  # live click counters
        self.after(400, self._poll)

    def _drain_engine_events(self):
        n = 0
        while n < 50:
            try:
                kind, payload = self.engine.events.get_nowait()
            except queue.Empty:
                break
            n += 1
            if kind == "click":
                self._log(f"✔ 命中 [{payload['rule']}] "
                          f"({payload['x']},{payload['y']}) 分数 {payload['score']}")
                for r in self.rules:
                    if r["name"] == payload["rule"]:
                        st = self.engine._state.get(r["id"])
                        if st is not None:
                            st["last_score"] = payload["score"]
            elif kind == "done":
                self._log(f"■ 规则完成（达到点击上限）id={payload}")
            elif kind == "log":
                # 只显示命中相关的日志，隐藏每轮无命中的刷屏
                if (payload == "本轮无命中" or payload.startswith("— 第")
                        or "无暗格" in payload):
                    continue
                self._log(payload)

    # -------------------------------------------------------------------- misc
    def _log(self, text):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", time.strftime("[%H:%M:%S] ") + text + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _on_close(self):
        self.engine.stop()
        self.hotkeys.stop()
        self.destroy()
