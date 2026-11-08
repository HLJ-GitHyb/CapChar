"""CapChar 主程序入口（性能优化版）"""
import os
import sys

# mediapipe 的绘图工具会连带导入 matplotlib；打包后不带 Qt 绑定，强制无界面后端
os.environ.setdefault("MPLBACKEND", "Agg")

import tkinter as tk
import queue
import traceback
from PIL import Image, ImageTk
import cv2
import time
import threading

from config import APP_NAME, APP_VERSION, UI_FRAME_INTERVAL_MS, CAPTURE_TARGET_FPS
from detector import PoseDetector
from frame_renderer import FrameRenderer
from source_manager import SourceManager
from ui import CapCharUI


class AsyncDetector:
    """异步检测器：在独立线程中运行检测，不阻塞 UI 线程"""

    def __init__(self, detector, max_width=480, num_poses=3, frame_interval=3):
        self._detector = detector
        self._max_width = max_width
        self._num_poses = num_poses
        self._frame_interval = frame_interval
        self._lock = threading.Lock()
        self._latest_persons = []
        self._latest_frame = None
        self._busy = False
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._frame_ready = threading.Event()
        self._result_ready = threading.Event()
        self._input_frame = None

    def start(self):
        self._thread.start()

    def stop(self):
        self._running = False
        self._frame_ready.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def update_params(self, max_width, num_poses, frame_interval):
        """动态更新检测参数（运行时调用）"""
        with self._lock:
            self._max_width = max_width
            self._num_poses = num_poses
            self._frame_interval = frame_interval

    def submit(self, frame):
        """提交新帧进行检测（非阻塞）"""
        if self._busy:
            return  # 上一帧还在处理中，跳过
        with self._lock:
            self._input_frame = frame.copy()
            self._busy = True
        self._frame_ready.set()

    def get_result(self):
        """获取最新检测结果（非阻塞），返回 (persons, is_fresh)"""
        if self._result_ready.is_set():
            self._result_ready.clear()
            with self._lock:
                persons = self._latest_persons
            return persons, True
        with self._lock:
            return self._latest_persons, False

    def _worker(self):
        while self._running:
            self._frame_ready.wait(timeout=0.5)
            self._frame_ready.clear()
            if not self._running:
                break

            with self._lock:
                frame = self._input_frame
                mw = self._max_width
                if frame is None:
                    self._busy = False
                    continue

            try:
                persons = self._detector.detect(frame, max_width=mw)
            except Exception:
                persons = []

            with self._lock:
                self._latest_persons = persons
                self._busy = False
            self._result_ready.set()


class CaptureWorker:
    """采集线程：把可能阻塞的 read() 移出 UI 线程，UI 只取最新一帧"""

    def __init__(self, source, target_fps=CAPTURE_TARGET_FPS):
        self._source = source
        self._interval = 1.0 / max(1, target_fps)
        self._lock = threading.Lock()
        self._frame = None
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def take_latest(self):
        """取出最新帧并清空槽位（返回 None 表示没有新帧）"""
        with self._lock:
            frame = self._frame
            self._frame = None
            return frame

    def _worker(self):
        try:
            while self._running:
                started = time.time()
                try:
                    ok, frame = self._source.read()
                except Exception:
                    ok, frame = False, None
                if not self._running:
                    break
                if ok and frame is not None:
                    with self._lock:
                        self._frame = frame
                else:
                    time.sleep(0.01)
                if self._source.source_type == "screen":
                    # 屏幕捕获按目标帧率限速，避免空转占满 CPU
                    elapsed = time.time() - started
                    if elapsed < self._interval:
                        time.sleep(self._interval - elapsed)
        finally:
            # mss 句柄必须由创建它的线程释放
            self._source.close_thread_local()


class CapCharApp:
    """CapChar 应用程序"""

    def __init__(self):
        self.root = tk.Tk()
        self._apply_window_icon()
        self.ui = CapCharUI(self.root)
        self.source = SourceManager()
        self.renderer = FrameRenderer()
        self.detector = None
        self._detector_cfg = None  # 检测器创建参数，用于跨启动复用
        self.async_det = None

        self._running = False
        self._starting = False
        self._start_cancel = False
        self._loop_id = None
        self._capture = None
        self._last_fps_time = time.time()
        self._frame_count = 0
        self._fps = 0.0
        self._last_stats_time = 0.0

        # 缓存画布尺寸，避免每帧查询
        self._canvas_w = 640
        self._canvas_h = 480
        self._last_persons = []

        # 后台线程 --> UI 线程的回调队列（Tk 只能在主线程操作）
        self._ui_queue = queue.Queue()
        self._device_scan_id = 0
        self._devices_ready = False
        self._cleanup_done = True

        self._bind_events()
        self.root.after(50, self._pump_ui)
        self._refresh_devices()
        self._tick_clock()

    def _apply_window_icon(self):
        """设置窗口 / 任务栏图标（源码运行与打包后均可用）"""
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        ico = os.path.join(base, "image.ico")
        png = os.path.join(base, "image.png")
        try:
            if os.name == "nt" and os.path.exists(ico):
                self.root.iconbitmap(default=ico)
                return
        except tk.TclError:
            pass
        try:
            if os.path.exists(png):
                self._window_icon = tk.PhotoImage(file=png)
                self.root.iconphoto(True, self._window_icon)
        except tk.TclError:
            pass

    def _bind_events(self):
        self.ui.on("on_source_type_change", self._refresh_devices)
        self.ui.on("on_open", self._start)
        self.ui.on("on_close", self._stop)
        self.ui.on("on_option_change", self._on_option_change)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.ui.canvas.bind("<Configure>", self._on_canvas_resize)

    def _on_canvas_resize(self, event):
        self._canvas_w = event.width
        self._canvas_h = event.height

    def _on_option_change(self):
        """UI 选项变化时回调：动态更新检测参数"""
        if self.async_det:
            preset = self.ui.get_perf_preset()
            self.async_det.update_params(
                max_width=preset["max_width"],
                num_poses=preset["num_poses"],
                frame_interval=preset["frame_interval"],
            )
        # 更新流畅度信息标签
        self.ui._update_perf_info()

    def _pump_ui(self):
        """在 UI 线程执行后台线程投递的回调"""
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                # 单个回调出错不能影响后续后台任务的 UI 更新
                traceback.print_exc()
        try:
            self.root.after(50, self._pump_ui)
        except tk.TclError:
            pass

    # ─── 设备扫描（后台线程，避免阻塞界面） ──────────
    def _refresh_devices(self):
        src_type = self.ui.get_vars()["source_type"]
        self._device_scan_id += 1
        token = self._device_scan_id
        self._devices_ready = False
        self.ui.set_devices_loading()
        self.ui.set_scanning(True)
        if not self._running and not self._starting:
            self.ui.set_status("正在扫描设备…")
        threading.Thread(
            target=self._scan_devices, args=(src_type, token), daemon=True
        ).start()

    def _scan_devices(self, src_type, token):
        try:
            if src_type == "camera":
                devices = self.source.list_cameras()
                fallback = [(0, "默认摄像头")]
            else:
                devices = self.source.list_monitors()
                fallback = [(0, "默认显示器")]
            if not devices:
                devices = fallback
        except Exception:
            devices = [(0, "默认摄像头" if src_type == "camera" else "默认显示器")]
        self._ui_queue.put(lambda: self._apply_devices(src_type, token, devices))

    def _apply_devices(self, src_type, token, devices):
        if token != self._device_scan_id:
            return
        if self.ui.get_vars()["source_type"] != src_type:
            return
        self._devices_ready = True
        self.ui.set_devices(devices)
        self.ui.set_scanning(False)
        if not self._running and not self._starting:
            self.ui.set_status(f"就绪 · 已找到 {len(devices)} 个设备")

    # ─── 启动 / 停止（初始化在后台线程完成） ────────
    def _start(self):
        if self._running or self._starting:
            return
        if not self._devices_ready:
            self.ui.set_status("设备扫描中，请稍候…")
            return
        if not self._cleanup_done:
            self.ui.set_status("正在停止，请稍候…")
            return
        vars_ = self.ui.get_vars()
        preset = self.ui.get_perf_preset()
        self._starting = True
        self._start_cancel = False
        self.ui.set_status("正在启动…")
        self.ui.set_running(True)  # 启动中禁用「开启」，可点「关闭」取消
        threading.Thread(
            target=self._start_worker,
            args=(
                vars_["source_type"],
                self.ui.get_selected_device(),
                vars_["detection_conf"],
                preset,
            ),
            daemon=True,
        ).start()

    def _start_worker(self, src_type, device_idx, conf, preset):
        detector = None
        async_det = None
        try:
            if src_type == "camera":
                self.source.open_camera(device_idx)
            else:
                self.source.open_screen(device_idx)
            if self._start_cancel:
                self.source.close()
                return

            # 复用已创建的检测器：MediaPipe 初始化约 2~3 秒，
            # 且其 close() 在本机可能耗时数十秒，因此停止时不释放、再次启动直接复用
            cfg = (conf, preset["num_poses"])
            detector = self.detector
            if detector is None or self._detector_cfg != cfg:
                old = detector
                detector = PoseDetector(
                    min_detection_confidence=conf,
                    min_tracking_confidence=conf,
                    num_poses=preset["num_poses"],
                )
                if old is not None:
                    self._release_later(old)
            if self._start_cancel:
                if detector is not self.detector:
                    self._release_later(detector)
                self.source.close()
                return

            async_det = AsyncDetector(
                detector,
                max_width=preset["max_width"],
                num_poses=preset["num_poses"],
                frame_interval=preset["frame_interval"],
            )
            async_det.start()
            if self._start_cancel:
                async_det.stop()
                if detector is not self.detector:
                    self._release_later(detector)
                self.source.close()
                return

            self._ui_queue.put(lambda: self._on_started(detector, async_det, cfg))
        except Exception as e:
            if async_det:
                async_det.stop()
            if detector is not None and detector is not self.detector:
                self._release_later(detector)
            self.source.close()
            msg = str(e)
            self._ui_queue.put(lambda: self._on_start_failed(msg))

    def _release_later(self, detector):
        """在后台释放检测器：MediaPipe close() 可能很慢，不能卡住主流程"""
        threading.Thread(
            target=self._safe_release, args=(detector,), daemon=True
        ).start()

    @staticmethod
    def _safe_release(detector):
        try:
            detector.release()
        except Exception:
            pass

    def _on_started(self, detector, async_det, cfg):
        if self._start_cancel:
            async_det.stop()
            if detector is not self.detector:
                self._release_later(detector)
            self.source.close()
            return
        self._starting = False
        self.detector = detector
        self._detector_cfg = cfg
        self.async_det = async_det
        self._capture = CaptureWorker(self.source)
        self._capture.start()

        self.renderer.reset_trails()
        self._running = True
        self._frame_count = 0
        self._last_fps_time = time.time()
        self._last_stats_time = 0.0
        self._last_persons = []
        self.ui.set_running(True)
        self.ui.set_status("运行中...")
        self._loop()

    def _on_start_failed(self, msg):
        if self._start_cancel:
            self._start_cancel = False
            self.ui.set_running(False)
            self.ui.set_status("已停止")
            return
        self._starting = False
        self.source.close()
        self.ui.set_running(False)
        self.ui.set_status(f"启动失败：{msg}")

    def _stop(self):
        was_starting = self._starting
        self._starting = False
        self._start_cancel = True
        self._running = False
        if self._loop_id:
            self.root.after_cancel(self._loop_id)
            self._loop_id = None

        # 采集器 / 检测线程 / 视频源在后台线程释放：
        # 摄像头 release() 可能耗时，不能阻塞 UI；检测器保留以便下次启动复用
        capture, async_det = self._capture, self.async_det
        self._capture = None
        self.async_det = None
        self._cleanup_done = False

        self.ui.set_running(False)
        if capture or async_det:
            self.ui.set_status("正在停止…")
            threading.Thread(
                target=self._cleanup_worker,
                args=(capture, async_det),
                daemon=True,
            ).start()
        else:
            self.source.close()
            self._cleanup_done = True
            self.ui.set_status("已取消" if was_starting else "已停止")

    def _cleanup_worker(self, capture, async_det):
        try:
            if capture:
                capture.stop()
            self.source.close()
            if async_det:
                async_det.stop()
        finally:
            self._ui_queue.put(self._on_cleanup_done)

    def _on_cleanup_done(self):
        self._cleanup_done = True
        if not self._running and not self._starting:
            self.ui.set_status("已停止")

    def _loop(self):
        if not self._running:
            return

        # 采集在独立线程进行，这里只处理最新帧，避免 read() 阻塞 UI
        frame = self._capture.take_latest() if self._capture else None
        if frame is not None:
            self._render_frame(frame)
        self._loop_id = self.root.after(UI_FRAME_INTERVAL_MS, self._loop)

    def _render_frame(self, frame):
        # 提交帧到异步检测线程（非阻塞，上一帧未完成时自动跳过）
        if self.async_det:
            self.async_det.submit(frame)

        # 获取最新检测结果（可能是上一帧的，但保持画面流畅）
        persons, is_fresh = ([], False)
        if self.async_det:
            persons, is_fresh = self.async_det.get_result()
        if not is_fresh:
            persons = self._last_persons
        self._last_persons = persons

        # 渲染
        vars_ = self.ui.get_vars()
        rendered = self.renderer.render(
            frame, persons,
            show_skeleton=vars_["show_skeleton"],
            show_trails=vars_["show_trails"],
        )

        # 先缩放到画布尺寸再转 RGB：避免对整张高分辨率帧做颜色转换
        cw = self._canvas_w
        ch = self._canvas_h
        ih, iw = rendered.shape[:2]
        if cw > 1 and ch > 1:
            scale = min(cw / iw, ch / ih)
            nw, nh = int(iw * scale), int(ih * scale)
            if nw > 0 and nh > 0 and (nw != iw or nh != ih):
                interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
                rendered = cv2.resize(rendered, (nw, nh), interpolation=interp)

        rgb = cv2.cvtColor(rendered, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        photo = ImageTk.PhotoImage(pil_img)
        self.ui.update_frame(photo)

        # FPS 计算
        self._frame_count += 1
        now = time.time()
        elapsed = now - self._last_fps_time
        if elapsed >= 1.0:
            self._fps = self._frame_count / elapsed
            self._frame_count = 0
            self._last_fps_time = now

        # 统计（限制到约 2 次/秒，减少 Tk 控件更新）
        if now - self._last_stats_time >= 0.5:
            self._last_stats_time = now
            state_counts = {}
            for p in persons:
                s = p["state"]
                state_counts[s] = state_counts.get(s, 0) + 1
            self.ui.update_stats(self._fps, len(persons), state_counts)

    def _tick_clock(self):
        self.ui.update_time()
        self.root.after(1000, self._tick_clock)

    def _on_close(self):
        self._stop()
        self.root.destroy()

    def run(self):
        self.ui.set_status(f"{APP_NAME} v{APP_VERSION} 就绪")
        self.root.mainloop()


def main():
    app = CapCharApp()
    app.run()


if __name__ == "__main__":
    main()
