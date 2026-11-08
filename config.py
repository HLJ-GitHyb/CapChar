"""CapChar 全局配置"""

APP_NAME = "CapChar"
APP_VERSION = "1.0.0"

# ─── 状态颜色映射 ─────────────────────────────────
STATE_COLORS = {
    "站立": "#00E676",
    "行走": "#FFD600",
    "奔跑": "#FF1744",
    "坐姿": "#2979FF",
    "蹲下": "#AA00FF",
    "跳跃": "#00E5FF",
    "弯腰": "#FF9100",
    "倒地": "#F50057",
    "静止": "#78909C",
    "未知": "#9E9E9E",
}

# ─── 深色主题配色 ───────────────────────────────────
THEME = {
    "bg": "#0D1117",
    "panel": "#161B22",
    "card": "#21262D",
    "border": "#30363D",
    "text": "#E6EDF3",
    "text_dim": "#8B949E",
    "accent": "#58A6FF",
    "danger": "#F85149",
    "success": "#3FB950",
    "warning": "#D29922",
}

# ─── 字体 ──────────────────────────────────────
FONTS = {
    "title": ("Segoe UI", 18, "bold"),
    "subtitle": ("Segoe UI", 11),
    "label": ("Segoe UI", 10),
    "value": ("Segoe UI", 11, "bold"),
    "small": ("Segoe UI", 9),
    "fps": ("Consolas", 11, "bold"),
    "button": ("Segoe UI", 10, "bold"),
}

# ─── 检测参数 ──────────────────────────────────────
DETECTION_CONFIDENCE = 0.5
TRACKING_CONFIDENCE = 0.5

# ─── 流畅度档位（UI 可调） ──────────────────────────
# 每个档位定义：检测宽度 / 最大人数 / 渲染缩放插值 / 帧间隔ms
PERFORMANCE_PRESETS = {
    "极致画质": {"max_width": 960, "num_poses": 5, "frame_interval": 1},
    "高画质":   {"max_width": 640, "num_poses": 4, "frame_interval": 1},
    "均衡":     {"max_width": 480, "num_poses": 3, "frame_interval": 3},
    "流畅":     {"max_width": 320, "num_poses": 2, "frame_interval": 5},
    "极致流畅": {"max_width": 240, "num_poses": 1, "frame_interval": 8},
}
PERFORMANCE_PRESET_NAMES = list(PERFORMANCE_PRESETS.keys())
DEFAULT_PERFORMANCE = "均衡"

# 兼容旧引用（启动时的默认值，运行时由 UI 档位覆盖）
DETECTION_MAX_WIDTH = PERFORMANCE_PRESETS[DEFAULT_PERFORMANCE]["max_width"]
NUM_POSES = PERFORMANCE_PRESETS[DEFAULT_PERFORMANCE]["num_poses"]

# ─── 骨骼连接定义 ────────────────────────────────────
SKELETON_CONNECTIONS = [
    (11, 12),  # 肩膀
    (11, 13), (13, 15),  # 左臂
    (12, 14), (14, 16),  # 右臂
    (11, 23), (12, 24),  # 躯干侧边
    (23, 24),  # 髋部
    (23, 25), (25, 27),  # 左腿
    (24, 26), (26, 28),  # 右腿
    (27, 29), (29, 31),  # 左脚
    (28, 30), (30, 32),  # 右脚
]

# ─── UI 刷新与采集 ────────────────────────────────
UI_FRAME_INTERVAL_MS = 30   # 画面刷新间隔（约 33 fps）
CAPTURE_TARGET_FPS = 30     # 屏幕捕获目标帧率（摄像头按设备自身速率）
CAMERA_SCAN_LIMIT = 5       # 摄像头索引扫描范围

# ─── UI 布局 ──────────────────────────────────────
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 800
SIDEBAR_WIDTH = 300
BBOX_THICKNESS = 3
LABEL_FONT = ("Segoe UI", 10, "bold")
TRAIL_LENGTH = 15
