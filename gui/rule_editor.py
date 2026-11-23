import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core import store
from core.paths import TEMPLATE_DIR

from . import snip

CLICK_KINDS = {"左键": "left", "右键": "right", "双击": "double",
               "滚轮下滑": "scroll", "仅提醒": "none"}


class RuleEditor(tk.Toplevel):
    def __init__(self, master, rule: dict | None = None, settings: dict | None = None):
        super().__init__(master)
        self.rule = dict(store.DEFAULTS, **(rule or store.new_rule()))
        self.settings = settings or {}
        self.result = None

        self.title("编辑规则" if rule else "新增规则")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        g = ttk.Frame(self, padding=10)
        g.grid(sticky="nsew")
        row = 0

        ttk.Label(g, text="名称").grid(row=row, column=0, sticky="w")
        self.name_var = tk.StringVar(value=self.rule["name"])
        ttk.Entry(g, textvariable=self.name_var, width=40).grid(
            row=row, column=1, columnspan=3, sticky="we", pady=2)
        row += 1

        ttk.Label(g, text="模板图片").grid(row=row, column=0, sticky="w")
        self.tpl_var = tk.StringVar(value=self.rule["template"])
        ttk.Entry(g, textvariable=self.tpl_var, width=28).grid(
            row=row, column=1, sticky="we", pady=2)
        ttk.Button(g, text="框选截图…", command=self._snip_template).grid(
            row=row, column=2, padx=2)
        ttk.Button(g, text="文件…", command=self._pick_file).grid(
            row=row, column=3)
        row += 1

        ttk.Label(g, text="匹配阈值").grid(row=row, column=0, sticky="w")
        self.thr_var = tk.DoubleVar(value=self.rule["threshold"])
        ttk.Spinbox(g, from_=0.5, to=0.99, increment=0.01, width=8,
                    textvariable=self.thr_var).grid(row=row, column=1, sticky="w")
        ttk.Label(g, text="(越高越严格，推荐 0.85)").grid(row=row, column=2,
                                                        columnspan=2, sticky="w")
        row += 1

        ttk.Label(g, text="搜索区域").grid(row=row, column=0, sticky="w")
        frame = ttk.Frame(g)
        frame.grid(row=row, column=1, columnspan=3, sticky="w")
        self.region_var = tk.StringVar(
            value=self._region_text(self.rule["region"]))
        ttk.Entry(frame, textvariable=self.region_var, width=24,
                  state="readonly").pack(side="left")
        ttk.Button(frame, text="框选…", command=self._snip_region).pack(
            side="left", padx=2)
        ttk.Button(frame, text="全屏", command=lambda: self._set_region(None)).pack(
            side="left")
        row += 1

        ttk.Label(g, text="点击动作").grid(row=row, column=0, sticky="w")
        self.click_var = tk.StringVar(
            value=[k for k, v in CLICK_KINDS.items() if v == self.rule["click"]][0])
        click_cb = ttk.Combobox(g, textvariable=self.click_var,
                                values=list(CLICK_KINDS), state="readonly", width=8)
        click_cb.grid(row=row, column=1, sticky="w")
        ttk.Label(g, text="偏移 X/Y").grid(row=row, column=2, sticky="e")
        offf = ttk.Frame(g)
        offf.grid(row=row, column=3, sticky="w")
        self.dx_var = tk.IntVar(value=int(self.rule["offset"][0]))
        self.dy_var = tk.IntVar(value=int(self.rule["offset"][1]))
        ttk.Spinbox(offf, from_=-500, to=500, width=5,
                    textvariable=self.dx_var).pack(side="left")
        ttk.Spinbox(offf, from_=-500, to=500, width=5,
                    textvariable=self.dy_var).pack(side="left", padx=(2, 0))
        row += 1

        ttk.Label(g, text="滚轮格数").grid(row=row, column=0, sticky="w")
        self.scroll_var = tk.IntVar(value=int(self.rule.get("scroll", 5)))
        ttk.Spinbox(g, from_=1, to=50, width=8,
                    textvariable=self.scroll_var).grid(row=row, column=1, sticky="w")
        ttk.Label(g, text="连滚次数").grid(row=row, column=2, sticky="e")
        self.scroll_rep_var = tk.IntVar(value=int(self.rule.get("scroll_repeat", 1)))
        ttk.Spinbox(g, from_=1, to=10, width=6,
                    textvariable=self.scroll_rep_var).grid(row=row, column=3, sticky="w")
        row += 1
        ttk.Label(g, text="(仅“滚轮下滑”动作用：每次触发连滚 N 段×M 格；偏移=滚动落点)").grid(
            row=row, column=0, columnspan=4, sticky="w")
        row += 1

        ttk.Label(g, text="预点击坐标").grid(row=row, column=0, sticky="w")
        pre_frame = ttk.Frame(g)
        pre_frame.grid(row=row, column=1, columnspan=3, sticky="we")
        self.pre_var = tk.StringVar(value=self._pre_text(
            self.rule.get("pre_clicks") or []))
        ttk.Entry(pre_frame, textvariable=self.pre_var, width=26).pack(side="left")
        ttk.Button(pre_frame, text="抓取鼠标位置…",
                   command=self._grab_pos).pack(side="left", padx=2)
        self.grab_label = ttk.Label(pre_frame, text="", foreground="#0a7")
        self.grab_label.pack(side="left")
        row += 1

        ttk.Label(g, text="预点击间隔(秒)").grid(row=row, column=0, sticky="w")
        self.pre_delay_var = tk.DoubleVar(value=float(self.rule.get("pre_delay", 0.6)))
        ttk.Spinbox(g, from_=0.2, to=5, increment=0.1, width=8,
                    textvariable=self.pre_delay_var).grid(row=row, column=1, sticky="w")
        ttk.Label(g, text="(命中模板后先按坐标依次点击，再执行主动作)").grid(
            row=row, column=2, columnspan=2, sticky="w")
        row += 1

        ttk.Label(g, text="暗格坐标").grid(row=row, column=0, sticky="w")
        self.dark_var = tk.StringVar(value=self._pre_text(
            self.rule.get("dark_slots") or []))
        ttk.Entry(g, textvariable=self.dark_var, width=40).grid(
            row=row, column=1, columnspan=3, sticky="we")
        row += 1
        ttk.Label(g, text="(命中模板后点第一个底色偏暗的格；全亮则不动作)").grid(
            row=row, column=0, columnspan=4, sticky="w")
        row += 1

        self.once_var = tk.BooleanVar(value=bool(self.rule.get("once_per_appearance")))
        ttk.Checkbutton(g, text="出现一次只点一次（界面消失后才重新武装）",
                        variable=self.once_var).grid(
            row=row, column=0, columnspan=4, sticky="w")
        row += 1

        ttk.Label(g, text="扫描间隔(秒)").grid(row=row, column=0, sticky="w")
        self.iv_var = tk.DoubleVar(value=self.rule["interval"])
        ttk.Spinbox(g, from_=0.2, to=600, increment=0.5, width=8,
                    textvariable=self.iv_var).grid(row=row, column=1, sticky="w")
        ttk.Label(g, text="点击后冷却(秒)").grid(row=row, column=2, sticky="e")
        self.cd_var = tk.DoubleVar(value=self.rule["cooldown"])
        ttk.Spinbox(g, from_=0, to=600, increment=0.5, width=8,
                    textvariable=self.cd_var).grid(row=row, column=3, sticky="w")
        row += 1

        ttk.Label(g, text="最大点击次数").grid(row=row, column=0, sticky="w")
        self.mc_var = tk.IntVar(value=int(self.rule["max_clicks"]))
        ttk.Spinbox(g, from_=0, to=99999, width=8,
                    textvariable=self.mc_var).grid(row=row, column=1, sticky="w")
        ttk.Label(g, text="(0 = 无限)").grid(row=row, column=2, columnspan=2,
                                            sticky="w")
        row += 1

        self.enabled_var = tk.BooleanVar(value=bool(self.rule["enabled"]))
        ttk.Checkbutton(g, text="启用", variable=self.enabled_var).grid(
            row=row, column=0, sticky="w")
        ttk.Button(g, text="测试匹配", command=self._test_match).grid(
            row=row, column=1, sticky="w")
        row += 1

        btns = ttk.Frame(g)
        btns.grid(row=row, column=0, columnspan=4, pady=(10, 0))
        ttk.Button(btns, text="保存", command=self._save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left")

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _region_text(region):
        return "全屏" if not region else f"{region[0]},{region[1]} {region[2]}x{region[3]}"

    def _set_region(self, region):
        self.rule["region"] = region
        self.region_var.set(self._region_text(region))

    @staticmethod
    def _pre_text(points):
        return ";".join(f"{p[0]},{p[1]}" for p in points)

    @staticmethod
    def _parse_pre(text):
        pts = []
        for part in text.replace("，", ",").replace("；", ";").split(";"):
            part = part.strip()
            if not part:
                continue
            xs, ys = part.split(",")[:2]
            pts.append([int(xs.strip()), int(ys.strip())])
        return pts

    def _grab_pos(self):
        self.grab_label.configure(text="2.5 秒内把鼠标移到目标位置…")
        self.after(2500, self._grab_pos_now)

    def _grab_pos_now(self):
        import pyautogui
        x, y = pyautogui.position()
        origin = self._window_origin()
        if origin:
            x -= origin[0]
            y -= origin[1]
        cur = self.pre_var.get().strip()
        self.pre_var.set((cur + ";" if cur else "") + f"{x},{y}")
        self.grab_label.configure(text=f"已记录 ({x},{y})")

    def _window_origin(self):
        if self.settings.get("use_window") and self.settings.get("window_title"):
            from core.scanner import find_window
            win = find_window(self.settings["window_title"])
            if win:
                return win[0], win[1]
            messagebox.showwarning("窗口模式",
                                   f"未找到窗口“{self.settings['window_title']}”，"
                                   "坐标将按屏幕绝对值保存", parent=self)
        return None

    def _snip_region(self):
        picked = snip.snip_region(self)
        if not picked:
            return
        box = list(picked[0])
        origin = self._window_origin()
        if origin:
            box = [box[0] - origin[0], box[1] - origin[1], box[2], box[3]]
        self._set_region(box)

    def _snip_template(self):
        import re
        hint = re.sub(r"\W+", "", self.name_var.get()) or "tpl"
        out = snip.snip_template(self, hint[:16])
        if out:
            path, _box = out
            self.tpl_var.set(path)

    def _pick_file(self):
        p = filedialog.askopenfilename(
            parent=self, initialdir=TEMPLATE_DIR,
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp")])
        if p:
            self.tpl_var.set(p)

    def _test_match(self):
        from core import scanner
        path = self.tpl_var.get()
        if not path or scanner.load_template(path) is None:
            messagebox.showwarning("测试", "请先选择模板图片", parent=self)
            return
        full, frame, is_win, _hwnd = scanner.grab_frame(self.settings)
        if full is None:
            messagebox.showwarning(
                "测试", f"未找到窗口“{self.settings.get('window_title', '')}”",
                parent=self)
            return
        rule = dict(self.rule, template=path, threshold=self.thr_var.get())
        hits = scanner.rule_hits(rule, full, frame, is_win)
        if hits is None:
            messagebox.showerror("测试", "无法读取模板图片", parent=self)
            return
        if hits:
            h = hits[0]
            messagebox.showinfo(
                "测试", f"命中 {len(hits)} 处，最佳:\n({int(h['cx'])}, {int(h['cy'])}) "
                f"分数 {h['score']}", parent=self)
        else:
            messagebox.showinfo("测试", "当前屏幕上未找到该图片（可适当降低阈值）",
                                parent=self)

    def _save(self):
        click = CLICK_KINDS[self.click_var.get()]
        # Start from the original rule so advanced fields the editor doesn't
        # expose (upgrade_*, consecutive_restart, bright_*, swipe_dist, ...)
        # are preserved instead of being wiped on every save.
        result = dict(self.rule)
        result.update({
            "name": self.name_var.get().strip() or "未命名",
            "template": self.tpl_var.get().strip(),
            "threshold": round(self.thr_var.get(), 2),
            "region": self.rule["region"],
            "click": click,
            "scroll": self.scroll_var.get(),
            "scroll_repeat": self.scroll_rep_var.get(),
            "offset": [self.dx_var.get(), self.dy_var.get()],
            "pre_clicks": self._parse_pre(self.pre_var.get()),
            "pre_delay": self.pre_delay_var.get(),
            "dark_slots": self._parse_pre(self.dark_var.get()),
            "once_per_appearance": self.once_var.get(),
            "interval": self.iv_var.get(),
            "cooldown": self.cd_var.get(),
            "max_clicks": self.mc_var.get(),
            "enabled": self.enabled_var.get(),
        })
        self.result = result
        self.destroy()
