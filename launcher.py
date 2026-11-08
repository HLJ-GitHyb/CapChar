"""CapChar UI 启动系统 - 替代 run.bat"""
import tkinter as tk
from tkinter import ttk
import subprocess
import sys
import os
import threading
import importlib

from config import APP_NAME, APP_VERSION, THEME, FONTS


class LauncherApp:
    """CapChar 启动器"""

    REQUIRED_PACKAGES = [
        ("cv2", "opencv-python"),
        ("mediapipe", "mediapipe"),
        ("mss", "mss"),
        ("numpy", "numpy"),
        ("PIL", "Pillow"),
    ]

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} 启动器")
        self.root.geometry("560x480")
        self.root.resizable(False, False)
        self.root.configure(bg=THEME["bg"])

        self._style = ttk.Style()
        self._style.theme_use("clam")
        self._apply_style()
        self._build_ui()
        self._status_data = {}  # module -> (ok: bool, name: str)

        # 启动后自动检查
        self.root.after(200, self._check_all_deps)

    def _apply_style(self):
        T = THEME
        self.root.option_add("*Font", FONTS["label"])
        self.root.option_add("*Foreground", T["text"])
        self.root.option_add("*Background", T["bg"])

        self._style.configure("TFrame", background=T["bg"])
        self._style.configure("Panel.TFrame", background=T["panel"])
        self._style.configure("Card.TFrame", background=T["card"])

        self._style.configure("TLabel", background=T["bg"], foreground=T["text"])
        self._style.configure("Title.TLabel", font=FONTS["title"],
                              foreground=T["accent"], background=T["bg"])
        self._style.configure("Subtitle.TLabel", font=FONTS["subtitle"],
                              foreground=T["text_dim"], background=T["bg"])
        self._style.configure("Card.TLabel", font=FONTS["label"],
                              foreground=T["text"], background=T["card"])
        self._style.configure("Panel.TLabel", font=FONTS["label"],
                              foreground=T["text"], background=T["panel"])

        self._style.configure("Accent.TButton", font=FONTS["button"],
                              foreground=T["bg"], background=T["accent"], borderwidth=0)
        self._style.map("Accent.TButton",
                        background=[("active", "#79B8FF"), ("pressed", "#1F6FEB")])

        self._style.configure("Small.TButton", font=FONTS["small"],
                              foreground=T["text"], background=T["card"], borderwidth=0)
        self._style.map("Small.TButton",
                        background=[("active", T["border"])])

    def _build_ui(self):
        T = THEME
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=24, pady=20)

        # ─── 标题区 ─────────────────
        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 16))

        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, text=f"v{APP_VERSION}", style="Subtitle.TLabel").pack(
            side=tk.LEFT, padx=(8, 0), pady=(6, 0))
        ttk.Label(main, text="启动前环境检查", style="Subtitle.TLabel").pack(anchor=tk.W)

        # ─── 依赖检查卡片 ─────────────────
        card = ttk.Frame(main, style="Card.TFrame")
        card.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        inner = ttk.Frame(card, style="Card.TFrame")
        inner.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)

        ttk.Label(inner, text="依赖组件", style="Card.TLabel",
                  font=FONTS["subtitle"]).pack(anchor=tk.W)

        self._dep_frame = ttk.Frame(inner, style="Card.TFrame")
        self._dep_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        # 每行一个依赖
        self._dep_rows = {}
        for mod_name, pip_name in self.REQUIRED_PACKAGES:
            row = ttk.Frame(self._dep_frame, style="Card.TFrame")
            row.pack(fill=tk.X, pady=3)

            icon_lbl = ttk.Label(row, text="...", style="Card.TLabel",
                                 font=("Consolas", 11, "bold"), width=3)
            icon_lbl.pack(side=tk.LEFT)

            name_lbl = ttk.Label(row, text=pip_name, style="Card.TLabel",
                                 font=FONTS["label"])
            name_lbl.pack(side=tk.LEFT, padx=(6, 0))

            ver_lbl = ttk.Label(row, text="", style="Card.TLabel",
                                font=FONTS["small"], foreground=T["text_dim"])
            ver_lbl.pack(side=tk.LEFT, padx=(8, 0))

            self._dep_rows[mod_name] = (icon_lbl, name_lbl, ver_lbl)

        # ─── 模型文件 ─────────────────
        model_row = ttk.Frame(inner, style="Card.TFrame")
        model_row.pack(fill=tk.X, pady=(8, 0))
        self._model_icon = ttk.Label(model_row, text="...", style="Card.TLabel",
                                     font=("Consolas", 11, "bold"), width=3)
        self._model_icon.pack(side=tk.LEFT)
        self._model_label = ttk.Label(model_row, text="pose_landmarker.task",
                                      style="Card.TLabel", font=FONTS["label"])
        self._model_label.pack(side=tk.LEFT, padx=(6, 0))

        # ─── 底部按钮区 ─────────────────
        bottom = ttk.Frame(main)
        bottom.pack(fill=tk.X, pady=(16, 0))

        self._status_label = ttk.Label(bottom, text="检查中...", style="Subtitle.TLabel")
        self._status_label.pack(side=tk.LEFT)

        self._launch_btn = ttk.Button(
            bottom, text="启动 CapChar", style="Accent.TButton",
            command=self._launch, state=tk.DISABLED,
        )
        self._launch_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self._fix_btn = ttk.Button(
            bottom, text="一键安装缺失依赖", style="Small.TButton",
            command=self._install_missing, state=tk.DISABLED,
        )
        self._fix_btn.pack(side=tk.RIGHT)

    # ─── 依赖检查 ──────────────────────────────
    def _check_all_deps(self):
        threading.Thread(target=self._do_check, daemon=True).start()

    def _do_check(self):
        T = THEME
        all_ok = True
        missing = []

        for mod_name, pip_name in self.REQUIRED_PACKAGES:
            try:
                mod = importlib.import_module(mod_name)
                ver = getattr(mod, "__version__", "已安装")
                self.root.after(0, self._set_dep_status, mod_name, True, str(ver))
            except ImportError:
                all_ok = False
                missing.append(pip_name)
                self.root.after(0, self._set_dep_status, mod_name, False, "未安装")

        # 检查模型文件
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pose_landmarker.task")
        model_ok = os.path.exists(model_path)
        self.root.after(0, self._set_model_status, model_ok)
        if not model_ok:
            all_ok = False

        if all_ok:
            self.root.after(0, self._all_ready)
        else:
            self.root.after(0, self._has_missing, missing)

    def _set_dep_status(self, mod_name, ok, version_text):
        T = THEME
        icon_lbl, name_lbl, ver_lbl = self._dep_rows[mod_name]
        if ok:
            icon_lbl.config(text="OK", foreground=T["success"])
            ver_lbl.config(text=version_text)
        else:
            icon_lbl.config(text="X", foreground=T["danger"])
            ver_lbl.config(text=version_text, foreground=T["danger"])

    def _set_model_status(self, ok):
        T = THEME
        if ok:
            self._model_icon.config(text="OK", foreground=T["success"])
        else:
            self._model_icon.config(text="X", foreground=T["danger"])
            self._model_label.config(foreground=T["danger"])

    def _all_ready(self):
        T = THEME
        self._status_label.config(text="所有依赖就绪，可以启动", foreground=T["success"])
        self._launch_btn.config(state=tk.NORMAL)
        self._fix_btn.config(state=tk.DISABLED)

    def _has_missing(self, missing):
        T = THEME
        names = ", ".join(missing)
        self._status_label.config(text=f"缺少: {names}", foreground=T["warning"])
        self._launch_btn.config(state=tk.DISABLED)
        self._fix_btn.config(state=tk.NORMAL)

    # ─── 安装依赖 ──────────────────────────────
    def _install_missing(self):
        self._fix_btn.config(state=tk.DISABLED)
        self._status_label.config(text="正在安装...", foreground=THEME["accent"])
        threading.Thread(target=self._do_install, daemon=True).start()

    def _do_install(self):
        missing = []
        for mod_name, pip_name in self.REQUIRED_PACKAGES:
            try:
                importlib.import_module(mod_name)
            except ImportError:
                missing.append(pip_name)

        # 检查模型
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pose_landmarker.task")
        need_model = not os.path.exists(model_path)

        ok = True
        if missing:
            cmd = [sys.executable, "-m", "pip", "install"] + missing
            ret = subprocess.run(cmd, capture_output=True, text=True)
            if ret.returncode != 0:
                ok = False
                self.root.after(0, self._install_failed, ret.stderr[:200])

        if need_model and ok:
            model_url = ("https://storage.googleapis.com/mediapipe-models/"
                         "pose_landmarker/pose_landmarker_lite/float16/1/"
                         "pose_landmarker_lite.task")
            ret = subprocess.run(
                ["curl", "-L", "-o", model_path, model_url],
                capture_output=True, text=True,
            )
            if ret.returncode != 0:
                ok = False
                self.root.after(0, self._install_failed, "模型下载失败")

        if ok:
            self.root.after(0, self._install_done)

    def _install_done(self):
        self._status_label.config(text="安装完成，重新检查中...")
        self.root.after(300, self._check_all_deps)

    def _install_failed(self, err):
        T = THEME
        self._status_label.config(text=f"安装失败: {err[:80]}", foreground=T["danger"])
        self._fix_btn.config(state=tk.NORMAL)

    # ─── 启动主程序 ──────────────────────────────
    def _launch(self):
        self.root.withdraw()
        # 导入并运行主程序（同进程，共享 tkinter mainloop）
        try:
            from main import CapCharApp
            app = CapCharApp()
            app.run()
        except Exception as e:
            self.root.deiconify()
            self._status_label.config(text=f"启动失败: {e}", foreground=THEME["danger"])

    def run(self):
        self.root.mainloop()


def main():
    app = LauncherApp()
    app.run()


if __name__ == "__main__":
    main()
