"""视频源管理器：摄像头 / 屏幕捕获"""
import os
import time
import ctypes
import threading
from ctypes import wintypes

import cv2
import numpy as np

from config import CAMERA_SCAN_LIMIT

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False


# ─── Windows 设备名称查询 ──────────────────────────
# DirectShow 视频输入设备类别 GUID 下的注册表项，保存着设备友好名称
_DS_VIDEO_CATEGORY = (
    r"SOFTWARE\Classes\CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance"
)

# 摄像头扫描结果缓存：避免每次切换视频源都重新探测（探测会短暂占用设备）
_CAMERA_CACHE_TTL = 5.0
_camera_cache = {"ts": 0.0, "devices": []}


def _directshow_camera_names():
    """读取 DirectShow 视频输入设备的友好名称（如 OBS Virtual Camera）"""
    try:
        import winreg
    except ImportError:
        return []

    names = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CLASSES_ROOT):
        try:
            with winreg.OpenKey(root, _DS_VIDEO_CATEGORY) as key:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                            friendly, _ = winreg.QueryValueEx(sub, "FriendlyName")
                    except OSError:
                        continue
                    friendly = str(friendly).strip()
                    if friendly and friendly not in names:
                        names.append(friendly)
            if names:
                break
        except OSError:
            continue
    return names


if os.name == "nt":
    class _MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    class _DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]


def _enum_display_monitors():
    """枚举显示器：设备名、位置尺寸、是否主屏"""
    if os.name != "nt":
        return []

    user32 = ctypes.windll.user32
    result = []
    MONITORINFOF_PRIMARY = 0x1

    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )

    def _callback(hmon, hdc, lprc, data):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            rect = info.rcMonitor
            result.append({
                "device": info.szDevice,
                "left": rect.left,
                "top": rect.top,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
                "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
            })
        return True

    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_callback), 0)
    return result


def _monitor_friendly_name(device_name):
    """获取显示器友好名称（过滤无意义的通用名称）"""
    if os.name != "nt":
        return ""
    info = _DISPLAY_DEVICEW()
    info.cb = ctypes.sizeof(_DISPLAY_DEVICEW)
    if ctypes.windll.user32.EnumDisplayDevicesW(
        device_name, 0, ctypes.byref(info), 0
    ):
        name = info.DeviceString.strip()
        generic = ("generic pnp monitor", "通用即插即用监视器", "通用非即插即用监视器")
        if name and name.lower() not in generic:
            return name
    return ""


class SourceManager:
    """管理视频输入源（摄像头、屏幕捕获）"""

    def __init__(self):
        self._cap = None
        self._monitor = None
        self._current_device = 0
        # mss 的 GDI 句柄与线程绑定，必须每线程各建一个实例
        self._thread_local = threading.local()
        self._source_type = None  # "camera" | "screen"
        self._width = 1280
        self._height = 720

    # ─── 摄像头 ────────────────────────────────
    def list_cameras(self, max_check=CAMERA_SCAN_LIMIT):
        """扫描可用摄像头，返回 [(index, 真实设备名), ...]"""
        now = time.time()
        if now - _camera_cache["ts"] < _CAMERA_CACHE_TTL:
            return list(_camera_cache["devices"])

        # 当前摄像头正在推流时不再探测，避免占用/打断正在采集的设备
        if self._source_type == "camera" and self._cap is not None and self._cap.isOpened():
            if _camera_cache["devices"]:
                return list(_camera_cache["devices"])
            names = _directshow_camera_names()
            name = names[0] if names else f"摄像头 {self._current_device}"
            return [(self._current_device, name)]

        names = _directshow_camera_names()
        # 已知设备数量时只需探测少量索引，显著缩短扫描时间
        limit = min(max_check, max(2, len(names) + 1)) if names else max_check
        found = []
        for i in range(limit):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                name = names[len(found)] if len(found) < len(names) else f"摄像头 {i}"
                found.append((i, name))
                cap.release()

        _camera_cache["ts"] = now
        _camera_cache["devices"] = list(found)
        return found

    def open_camera(self, index=0):
        """打开指定摄像头"""
        self.close()
        self._cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            raise RuntimeError(f"无法打开摄像头 {index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._current_device = index
        self._source_type = "camera"

    # ─── 屏幕捕获 ──────────────────────────────
    def open_screen(self, monitor_index=0):
        """打开屏幕捕获（只记录显示器区域，抓屏实例由读取线程创建）"""
        if not HAS_MSS:
            raise RuntimeError("需要安装 mss：pip install mss")
        self.close()
        sct = mss.mss()
        try:
            monitors = sct.monitors
            if monitor_index + 1 >= len(monitors):
                monitor_index = 0
            self._monitor = dict(monitors[monitor_index + 1])  # [0] 是虚拟全屏幕
        finally:
            try:
                sct.close()
            except Exception:
                pass
        self._source_type = "screen"

    def _thread_sct(self):
        """获取当前线程的 mss 实例（mss 句柄不能跨线程使用）"""
        sct = getattr(self._thread_local, "sct", None)
        if sct is None:
            sct = mss.mss()
            self._thread_local.sct = sct
        return sct

    def close_thread_local(self):
        """关闭当前线程的 mss 实例（必须在该线程内调用）"""
        sct = getattr(self._thread_local, "sct", None)
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass
            self._thread_local.sct = None

    def list_monitors(self):
        """列出可用显示器，返回 [(index, 设备名 · 分辨率 · 主屏标记), ...]"""
        if not HAS_MSS:
            return []
        sct = mss.mss()
        result = []
        displays = _enum_display_monitors()
        try:
            for i, m in enumerate(sct.monitors[1:], 0):
                matched = None
                for d in displays:
                    if (d["left"], d["top"], d["width"], d["height"]) == (
                        m["left"], m["top"], m["width"], m["height"]
                    ):
                        matched = d
                        break

                parts = []
                if matched:
                    dev = matched["device"].replace("\\\\.\\", "")
                    friendly = _monitor_friendly_name(matched["device"])
                    parts.append(f"{friendly} ({dev})" if friendly else dev)
                else:
                    parts.append(f"显示器 {i + 1}")
                parts.append(f"{m['width']}×{m['height']}")
                if matched and matched["primary"]:
                    parts.append("主屏")
                result.append((i, " · ".join(parts)))
        finally:
            sct.close()
        return result

    # ─── 帧读取 ────────────────────────────────
    def read(self):
        """读取一帧，返回 (success, frame_bgr)"""
        if self._source_type == "camera" and self._cap:
            ret, frame = self._cap.read()
            if not ret:
                return False, None
            return True, frame

        if self._source_type == "screen" and self._monitor:
            img = np.array(self._thread_sct().grab(self._monitor))
            # mss 返回 BGRA
            frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            return True, frame

        return False, None

    # ─── 属性 ────────────────────────────────
    @property
    def is_opened(self):
        if self._source_type == "camera":
            return self._cap is not None and self._cap.isOpened()
        return self._source_type == "screen"

    @property
    def source_type(self):
        return self._source_type

    def close(self):
        if self._cap:
            self._cap.release()
            self._cap = None
        self.close_thread_local()
        self._monitor = None
        self._source_type = None
