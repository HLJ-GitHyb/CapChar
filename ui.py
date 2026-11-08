"""CapChar 深色主题 UI 界面"""
import tkinter as tk
from tkinter import ttk
import time

from config import (
    APP_NAME, APP_VERSION, THEME, FONTS, STATE_COLORS,
    WINDOW_WIDTH, WINDOW_HEIGHT, SIDEBAR_WIDTH,
    PERFORMANCE_PRESET_NAMES, DEFAULT_PERFORMANCE,
)


class DarkTheme:
    """深色主题样式配置器"""

    @staticmethod
    def apply(root):
        style = ttk.Style()
        style.theme_use("clam")
        T = THEME

        # 全局
        root.configure(bg=T["bg"])
        root.option_add("*Font", FONTS["label"])
        root.option_add("*Foreground", T["text"])
        root.option_add("*Background", T["bg"])

        # Frame
        style.configure("TFrame", background=T["bg"])
        style.configure("Card.TFrame", background=T["card"])
        style.configure("Panel.TFrame", background=T["panel"])

        # Label
        style.configure("TLabel", background=T["bg"], foreground=T["text"])
        style.configure("Title.TLabel", font=FONTS["title"], foreground=T["accent"],
                        background=T["bg"])
        style.configure("Subtitle.TLabel", font=FONTS["subtitle"],
                        foreground=T["text_dim"], background=T["bg"])
        style.configure("Value.TLabel", font=FONTS["value"], foreground=T["text"],
                        background=T["card"])
        style.configure("Card.TLabel", font=FONTS["label"], foreground=T["text"],
                        background=T["card"])
        style.configure("FPS.TLabel", font=FONTS["fps"], foreground=T["success"],
                        background=T["panel"])

        # Button
        style.configure(
            "Accent.TButton",
            font=FONTS["button"],
            foreground=T["bg"],
            background=T["accent"],
            borderwidth=0,
            focuscolor=T["accent"],
        )
        style.map("Accent.TButton",
                  background=[("active", "#79B8FF"), ("pressed", "#1F6FEB")])

        style.configure(
            "Danger.TButton",
            font=FONTS["button"],
            foreground="#FFFFFF",
            background=T["danger"],
            borderwidth=0,
        )
        style.map("Danger.TButton",
                  background=[("active", "#FF6B6B"), ("pressed", "#DA3633")])

        # Combobox
        style.configure(
            "Dark.TCombobox",
            fieldbackground=T["card"],
            background=T["card"],
            foreground=T["text"],
            arrowcolor=T["accent"],
            bordercolor=T["border"],
        )
        # clam 主题默认把只读下拉框刷成浅灰底，深色主题下文字会看不见，这里显式覆盖
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", T["card"]), ("disabled", T["panel"])],
            foreground=[("readonly", T["text"]), ("disabled", T["text_dim"])],
            selectbackground=[("readonly", T["card"])],
            selectforeground=[("readonly", T["text"])],
        )

        # Checkbutton
        style.configure(
            "Dark.TCheckbutton",
            background=T["bg"],
            foreground=T["text"],
            indicatorcolor=T["accent"],
        )

        # Separator
        style.configure("Dark.TSeparator", background=T["border"])

        # LabelFrame
        style.configure(
            "Dark.TLabelframe",
            background=T["bg"],
            foreground=T["accent"],
            bordercolor=T["border"],
        )
        style.configure(
            "Dark.TLabelframe.Label",
            background=T["bg"],
            foreground=T["accent"],
            font=FONTS["subtitle"],
        )


class CapCharUI:
    """主界面"""

    # 输入方式：界面显示中文，内部仍用 camera / screen 标识
    SOURCE_TYPE_LABELS = {"camera": "摄像头", "screen": "屏幕"}

    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(1000, 600)

        DarkTheme.apply(root)

        # 状态变量
        self._vars = {
            "source_type": tk.StringVar(value="camera"),
            "camera_index": tk.IntVar(value=0),
            "monitor_index": tk.IntVar(value=0),
            "show_skeleton": tk.BooleanVar(value=True),
            "show_trails": tk.BooleanVar(value=True),
            "detection_conf": tk.DoubleVar(value=0.5),
            "performance": tk.StringVar(value=DEFAULT_PERFORMANCE),
        }
        self._callbacks = {}

        # 统计
        self._fps = 0
        self._person_count = 0
        self._state_counts = {}

        # 设备真实索引映射（下拉位置 -> 摄像头/显示器索引）
        self._device_indices = []
        self._scanning = False
        self._is_running = False
        # 画面复用：只创建一个 Canvas 图像项，逐帧替换内容
        self._canvas_image_id = None
        self._photo_ref = None
        # 统计标签缓存，避免每帧重复设置相同文本
        self._stat_texts = {}

        self._build_ui()

    def _build_ui(self):
        T = THEME
        # ─── 主容器 ───────────────────────
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # ─── 侧边栏 ───────────────────────
        sidebar = ttk.Frame(main, width=SIDEBAR_WIDTH, style="Panel.TFrame")
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=0, pady=0)
        sidebar.pack_propagate(False)

        self._build_sidebar(sidebar)

        # ─── 分隔线 ───────────────────────
        sep = tk.Frame(main, width=1, bg=T["border"])
        sep.pack(side=tk.LEFT, fill=tk.Y)

        # ─── 右侧主区域 ───────────────────────
        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_main_area(right)

    def _build_sidebar(self, parent):
        T = THEME

        # ─── Logo / 标题 ─────────────────
        header = ttk.Frame(parent, style="Panel.TFrame")
        header.pack(fill=tk.X, padx=16, pady=(20, 10))

        title_frame = ttk.Frame(header, style="Panel.TFrame")
        title_frame.pack(fill=tk.X)

        ttk.Label(title_frame, text=f"  {APP_NAME}", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(title_frame, text=f"v{APP_VERSION}", style="Subtitle.TLabel").pack(
            side=tk.LEFT, padx=(8, 0), pady=(6, 0))

        ttk.Label(header, text="实时人体姿态捕捉与状态分析",
                  style="Subtitle.TLabel").pack(anchor=tk.W, pady=(2, 0))

        ttk.Separator(parent, orient=tk.HORIZONTAL, style="Dark.TSeparator").pack(
            fill=tk.X, padx=16, pady=10)

        # ─── 视频源选择 ─────────────────
        src_frame = ttk.LabelFrame(parent, text="  视频源  ", style="Dark.TLabelframe")
        src_frame.pack(fill=tk.X, padx=16, pady=(0, 8))

        inner = ttk.Frame(src_frame, style="Panel.TFrame")
        inner.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(inner, text="输入方式", style="Card.TLabel").pack(anchor=tk.W)
        self._source_display = tk.StringVar(
            value=self.SOURCE_TYPE_LABELS[self._vars["source_type"].get()]
        )
        type_combo = ttk.Combobox(
            inner, textvariable=self._source_display,
            values=list(self.SOURCE_TYPE_LABELS.values()), state="readonly",
            style="Dark.TCombobox", width=20,
        )
        type_combo.pack(fill=tk.X, pady=(2, 8))
        type_combo.bind("<<ComboboxSelected>>", lambda e: self._on_source_type_selected())

        ttk.Label(inner, text="设备选择", style="Card.TLabel").pack(anchor=tk.W)
        self._device_combo = ttk.Combobox(
            inner, state="readonly", style="Dark.TCombobox", width=20,
        )
        self._device_combo.pack(fill=tk.X, pady=(2, 8))

        btn_row = ttk.Frame(inner, style="Panel.TFrame")
        btn_row.pack(fill=tk.X, pady=(4, 0))

        self._open_btn = ttk.Button(btn_row, text="开启", style="Accent.TButton",
                                    command=lambda: self._fire("on_open"))
        self._open_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))

        self._close_btn = ttk.Button(btn_row, text="关闭", style="Danger.TButton",
                                     command=lambda: self._fire("on_close"), state=tk.DISABLED)
        self._close_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        ttk.Separator(parent, orient=tk.HORIZONTAL, style="Dark.TSeparator").pack(
            fill=tk.X, padx=16, pady=8)

        # ─── 显示选项 ─────────────────
        opt_frame = ttk.LabelFrame(parent, text="  显示选项  ", style="Dark.TLabelframe")
        opt_frame.pack(fill=tk.X, padx=16, pady=(0, 8))

        opt_inner = ttk.Frame(opt_frame, style="Panel.TFrame")
        opt_inner.pack(fill=tk.X, padx=10, pady=10)

        ttk.Checkbutton(opt_inner, text="显示骨架", variable=self._vars["show_skeleton"],
                        style="Dark.TCheckbutton",
                        command=lambda: self._fire("on_option_change")).pack(anchor=tk.W, pady=2)
        ttk.Checkbutton(opt_inner, text="显示轨迹", variable=self._vars["show_trails"],
                        style="Dark.TCheckbutton",
                        command=lambda: self._fire("on_option_change")).pack(anchor=tk.W, pady=2)

        # 置信度滑块
        self._conf_label = ttk.Label(
            opt_inner, text=f"检测置信度: {self._vars['detection_conf'].get():.1f}",
            style="Card.TLabel"
        )
        self._conf_label.pack(anchor=tk.W, pady=(8, 0))
        conf_scale = ttk.Scale(
            opt_inner, from_=0.1, to=1.0,
            variable=self._vars["detection_conf"],
            orient=tk.HORIZONTAL,
            command=lambda v: self._on_conf_change(v),
        )
        conf_scale.pack(fill=tk.X, pady=(2, 0))

        # 流畅度档位
        ttk.Label(opt_inner, text="流畅度", style="Card.TLabel").pack(anchor=tk.W, pady=(10, 0))
        self._perf_combo = ttk.Combobox(
            opt_inner, textvariable=self._vars["performance"],
            values=PERFORMANCE_PRESET_NAMES, state="readonly",
            style="Dark.TCombobox", width=20,
        )
        self._perf_combo.pack(fill=tk.X, pady=(2, 4))
        self._perf_combo.bind("<<ComboboxSelected>>", lambda e: self._fire("on_option_change"))

        self._perf_info = ttk.Label(opt_inner, text="", style="Subtitle.TLabel",
                                    font=FONTS["small"])
        self._perf_info.pack(anchor=tk.W)
        self._update_perf_info()

        ttk.Separator(parent, orient=tk.HORIZONTAL, style="Dark.TSeparator").pack(
            fill=tk.X, padx=16, pady=8)

        # ─── 实时统计 ─────────────────
        stats_frame = ttk.LabelFrame(parent, text="  实时统计  ", style="Dark.TLabelframe")
        stats_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        stats_inner = ttk.Frame(stats_frame, style="Panel.TFrame")
        stats_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # FPS
        fps_row = ttk.Frame(stats_inner, style="Panel.TFrame")
        fps_row.pack(fill=tk.X, pady=2)
        ttk.Label(fps_row, text="FPS", style="Card.TLabel").pack(side=tk.LEFT)
        self._fps_label = ttk.Label(fps_row, text="--", style="FPS.TLabel")
        self._fps_label.pack(side=tk.RIGHT)

        # 检测人数
        count_row = ttk.Frame(stats_inner, style="Panel.TFrame")
        count_row.pack(fill=tk.X, pady=2)
        ttk.Label(count_row, text="检测人数", style="Card.TLabel").pack(side=tk.LEFT)
        self._count_label = ttk.Label(count_row, text="0", style="Value.TLabel")
        self._count_label.pack(side=tk.RIGHT)

        ttk.Separator(stats_inner, orient=tk.HORIZONTAL, style="Dark.TSeparator").pack(
            fill=tk.X, pady=8)

        # 状态分布
        ttk.Label(stats_inner, text="状态分布", style="Card.TLabel").pack(anchor=tk.W)
        self._state_labels = {}
        for state, color in STATE_COLORS.items():
            if state == "未知":
                continue
            row = ttk.Frame(stats_inner, style="Panel.TFrame")
            row.pack(fill=tk.X, pady=1)

            dot = tk.Canvas(row, width=10, height=10, bg=T["card"], highlightthickness=0)
            dot.pack(side=tk.LEFT, padx=(0, 6))
            dot.create_oval(1, 1, 9, 9, fill=color, outline="")

            ttk.Label(row, text=state, style="Card.TLabel").pack(side=tk.LEFT)
            cnt_lbl = ttk.Label(row, text="0", style="Value.TLabel")
            cnt_lbl.pack(side=tk.RIGHT)
            self._state_labels[state] = cnt_lbl

        # ─── 底部色图例 ─────────────────
        ttk.Separator(parent, orient=tk.HORIZONTAL, style="Dark.TSeparator").pack(
            fill=tk.X, padx=16, pady=8)

        legend_frame = ttk.Frame(parent, style="Panel.TFrame")
        legend_frame.pack(fill=tk.X, padx=16, pady=(0, 12))
        ttk.Label(legend_frame, text="状态颜色图例", style="Card.TLabel").pack(anchor=tk.W, pady=(0, 4))

        legend_grid = ttk.Frame(legend_frame, style="Panel.TFrame")
        legend_grid.pack(fill=tk.X)

        col = 0
        for state, color in STATE_COLORS.items():
            if state == "未知":
                continue
            cell = ttk.Frame(legend_grid, style="Panel.TFrame")
            cell.grid(row=0, column=col, padx=2, pady=1, sticky=tk.W)
            swatch = tk.Canvas(cell, width=12, height=12, bg=T["panel"], highlightthickness=0)
            swatch.pack(side=tk.LEFT)
            swatch.create_rectangle(0, 0, 12, 12, fill=color, outline="")
            ttk.Label(cell, text=state, style="Card.TLabel",
                     font=FONTS["small"]).pack(side=tk.LEFT, padx=(3, 0))
            col += 1
            if col >= 4:
                col = 0

    def _build_main_area(self, parent):
        T = THEME
        # ─── 顶部状态栏 ─────────────────
        topbar = ttk.Frame(parent, style="Panel.TFrame")
        topbar.pack(fill=tk.X, padx=0, pady=0)

        self._status_label = ttk.Label(topbar, text="  等待启动...", style="Subtitle.TLabel")
        self._status_label.pack(side=tk.LEFT, padx=12, pady=6)

        self._time_label = ttk.Label(topbar, text="", style="Subtitle.TLabel")
        self._time_label.pack(side=tk.RIGHT, padx=12, pady=6)

        sep = tk.Frame(parent, height=1, bg=T["border"])
        sep.pack(fill=tk.X)

        # ─── 画面区域 ─────────────────
        canvas_frame = ttk.Frame(parent)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(canvas_frame, bg=T["bg"], highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # 初始提示
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self._draw_placeholder()

    def _draw_placeholder(self):
        self.canvas.delete("all")
        self._canvas_image_id = None
        self._photo_ref = None
        w = self.canvas.winfo_width() or 600
        h = self.canvas.winfo_height() or 400
        T = THEME
        self.canvas.create_text(w // 2, h // 2 - 20, text="CapChar",
                                font=FONTS["title"], fill=T["accent"])
        self.canvas.create_text(w // 2, h // 2 + 20, text="选择视频源并点击「开启」开始捕捉",
                                font=FONTS["subtitle"], fill=T["text_dim"])

    def _on_canvas_resize(self, event):
        if not getattr(self, "_has_frame", False):
            self._draw_placeholder()

    # ─── 公共接口 ──────────────────────────
    def set_devices(self, devices):
        """更新设备下拉列表 [(index, name), ...]"""
        self._device_indices = [d[0] for d in devices]
        names = [d[1] for d in devices]
        self._device_combo["values"] = names
        if names:
            self._device_combo.current(0)
        else:
            self._device_combo.set("")

    def set_devices_loading(self):
        """设备扫描中的占位状态"""
        self._device_indices = []
        self._device_combo["values"] = ["正在扫描设备…"]
        self._device_combo.set("正在扫描设备…")

    def set_scanning(self, scanning):
        """扫描期间禁用「开启」，避免与设备探测同时占用摄像头"""
        self._scanning = scanning
        if scanning:
            self._open_btn.config(state=tk.DISABLED)
        elif not self._is_running:
            self._open_btn.config(state=tk.NORMAL)

    def get_selected_device(self):
        """返回下拉项对应的真实设备索引"""
        idx = self._device_combo.current()
        if 0 <= idx < len(self._device_indices):
            return self._device_indices[idx]
        return 0

    def update_frame(self, photo_image):
        """更新画面（复用同一个 Canvas 图像项，避免每帧删除/重建）"""
        if self._canvas_image_id is None:
            self._canvas_image_id = self.canvas.create_image(
                0, 0, image=photo_image, anchor=tk.NW
            )
        else:
            try:
                self.canvas.itemconfig(self._canvas_image_id, image=photo_image)
            except tk.TclError:
                self._canvas_image_id = self.canvas.create_image(
                    0, 0, image=photo_image, anchor=tk.NW
                )
        self._photo_ref = photo_image  # prevent GC
        self._has_frame = True

    def update_stats(self, fps, person_count, state_counts):
        """更新统计（仅文本变化时才写控件）"""
        self._set_stat_text("fps", self._fps_label, f"{fps:.1f}")
        self._set_stat_text("count", self._count_label, str(person_count))
        for state, lbl in self._state_labels.items():
            self._set_stat_text(state, lbl, str(state_counts.get(state, 0)))

    def _set_stat_text(self, key, label, text):
        if self._stat_texts.get(key) != text:
            label.config(text=text)
            self._stat_texts[key] = text

    def set_status(self, text):
        self._status_label.config(text=f"  {text}")

    def set_running(self, running):
        self._is_running = running
        if running:
            self._open_btn.config(state=tk.DISABLED)
            self._close_btn.config(state=tk.NORMAL)
        else:
            self._open_btn.config(
                state=tk.DISABLED if self._scanning else tk.NORMAL
            )
            self._close_btn.config(state=tk.DISABLED)
            self._has_frame = False
            self._draw_placeholder()

    def update_time(self):
        self._time_label.config(text=time.strftime("%H:%M:%S"))

    def get_vars(self):
        return {k: v.get() for k, v in self._vars.items()}

    def on(self, event, callback):
        self._callbacks[event] = callback

    def _on_conf_change(self, v):
        self._conf_label.config(text=f"检测置信度: {float(v):.1f}")
        self._fire("on_option_change")

    def _on_source_type_selected(self):
        """下拉框选的是中文名称，转换回内部标识 camera / screen"""
        label = self._source_display.get()
        for key, text in self.SOURCE_TYPE_LABELS.items():
            if text == label:
                self._vars["source_type"].set(key)
                break
        self._fire("on_source_type_change")

    def _update_perf_info(self):
        from config import PERFORMANCE_PRESETS
        name = self._vars["performance"].get()
        p = PERFORMANCE_PRESETS.get(name, {})
        self._perf_info.config(
            text=f"检测 {p.get('max_width', '?')}px · {p.get('num_poses', '?')}人 · 间隔 {p.get('frame_interval', '?')}ms"
        )

    def get_perf_preset(self):
        """获取当前流畅度档位配置"""
        from config import PERFORMANCE_PRESETS
        name = self._vars["performance"].get()
        return PERFORMANCE_PRESETS.get(name, PERFORMANCE_PRESETS["均衡"])

    def _fire(self, event):
        cb = self._callbacks.get(event)
        if cb:
            cb()
