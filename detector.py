"""人体检测与姿态状态分析引擎（MediaPipe 1.x PoseLandmarker API）"""
import os
import time
import math
import numpy as np
import cv2

from config import STATE_COLORS

# 模型文件路径（与本文件同目录）
_MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
_MODEL_PATH = os.path.join(_MODEL_DIR, "pose_landmarker.task")

_MP_MODULES = None


def _load_mediapipe():
    """延迟加载 mediapipe：避免程序启动时等待数秒才显示窗口"""
    global _MP_MODULES
    if _MP_MODULES is None:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
        _MP_MODULES = (mp, mp_python, mp_vision)
    return _MP_MODULES


class PoseDetector:
    """基于 MediaPipe PoseLandmarker 的人体姿态检测器"""

    def __init__(self, min_detection_confidence=0.5, min_tracking_confidence=0.5, num_poses=3):
        try:
            self._mp, mp_python, mp_vision = _load_mediapipe()
        except ImportError:
            raise RuntimeError("需要安装 mediapipe：pip install mediapipe")
        if not os.path.exists(_MODEL_PATH):
            raise FileNotFoundError(
                f"模型文件未找到：{_MODEL_PATH}\n"
                "请从以下地址下载：\n"
                "https://storage.googleapis.com/mediapipe-models/"
                "pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
            )

        # 构建 PoseLandmarker
        BaseOptions = mp_python.BaseOptions
        PoseLandmarker = mp_vision.PoseLandmarker
        PoseLandmarkerOptions = mp_vision.PoseLandmarkerOptions
        RunningMode = mp_vision.RunningMode

        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_MODEL_PATH),
            running_mode=RunningMode.VIDEO,
            num_poses=num_poses,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_tracking_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self.landmarker = PoseLandmarker.create_from_options(options)
        self._prev_positions = {}
        self._last_time = {}
        self._frame_timestamp_ms = 0
        # 预分配 numpy 数组用于避免重复内存分配
        self._mp_image_buf = None

    def detect(self, frame_bgr, max_width=640):
        """检测人体姿态，返回人物列表
        max_width: 检测前缩放到的最大宽度，越小越快
        """
        orig_h, orig_w = frame_bgr.shape[:2]

        # 降采样加速：将帧缩小到 max_width 再送入模型
        scale = 1.0
        if orig_w > max_width:
            scale = max_width / orig_w
            small_w = max_width
            small_h = int(orig_h * scale)
            small_bgr = cv2.resize(frame_bgr, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
        else:
            small_bgr = frame_bgr
            small_w, small_h = orig_w, orig_h

        # BGR -> RGB（用 numpy 视图避免拷贝）
        rgb = small_bgr[:, :, ::-1]
        mp_image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(rgb),
        )

        self._frame_timestamp_ms += 33
        result = self.landmarker.detect_for_video(mp_image, self._frame_timestamp_ms)

        persons = []
        if not result.pose_landmarks:
            return persons

        # 坐标映射回原始帧尺寸
        inv_scale = 1.0 / scale if scale != 1.0 else 1.0

        for person_idx, lm_list in enumerate(result.pose_landmarks):
            points = {}
            for idx, lm in enumerate(lm_list):
                if lm.visibility > 0.5:
                    px = int(lm.x * orig_w)
                    py = int(lm.y * orig_h)
                    points[idx] = (px, py)

            if not points:
                continue

            xs = [p[0] for p in points.values()]
            ys = [p[1] for p in points.values()]
            if not xs or not ys:
                continue

            x1 = max(0, min(xs) - 20)
            y1 = max(0, min(ys) - 20)
            x2 = min(orig_w, max(xs) + 20)
            y2 = min(orig_h, max(ys) + 20)

            state = self._analyze_state(points, person_idx)
            confidence = self._calc_confidence(lm_list)

            persons.append({
                "id": person_idx,
                "bbox": (x1, y1, x2, y2),
                "state": state,
                "color": STATE_COLORS.get(state, STATE_COLORS["未知"]),
                "confidence": confidence,
                "landmarks": lm_list,  # 归一化坐标，渲染时乘以原尺寸
                "points": points,
            })

        return persons

    def _analyze_state(self, points, track_id=0):
        """根据关键点分析人体状态"""
        required = [11, 12, 23, 24, 25, 26, 27, 28]
        if not all(k in points for k in required):
            return "未知"

        shoulder_l = points[11]
        shoulder_r = points[12]
        hip_l = points[23]
        hip_r = points[24]
        knee_l = points[25]
        knee_r = points[26]
        ankle_l = points[27]
        ankle_r = points[28]

        # 躯干与垂直线的夹角
        torso_angle = self._calc_torso_angle(
            (shoulder_l[0] + shoulder_r[0]) / 2,
            (shoulder_l[1] + shoulder_r[1]) / 2,
            (hip_l[0] + hip_r[0]) / 2,
            (hip_l[1] + hip_r[1]) / 2,
        )

        # 膝盖角度
        knee_angle_l = self._calc_knee_angle(hip_l, knee_l, ankle_l)
        knee_angle_r = self._calc_knee_angle(hip_r, knee_r, ankle_r)
        min_knee = min(knee_angle_l, knee_angle_r)

        # 身体高度相关
        body_height = abs(
            (shoulder_l[1] + shoulder_r[1]) / 2 - (hip_l[1] + hip_r[1]) / 2
        )
        hip_y = (hip_l[1] + hip_r[1]) / 2

        # 倒地：躯干接近水平
        if torso_angle < 30:
            return "倒地"

        # 弯腰：躯干倾斜明显
        if torso_angle < 60:
            return "弯腰"

        # 蹲下：膝盖角度很小
        if min_knee < 90:
            return "蹲下"

        # 跳跃
        if body_height > 0:
            hip_ankle = abs(hip_y - (ankle_l[1] + ankle_r[1]) / 2)
            ratio = hip_ankle / body_height if body_height > 0 else 0
            if ratio < 1.2:
                return "跳跃"

        # 运动状态：基于速度
        now = time.time()
        speed = self._calc_speed(points, now, track_id)
        if speed > 400:
            return "奔跑"
        elif speed > 100:
            return "行走"

        return "站立"

    def _calc_speed(self, points, now, track_id):
        """计算运动速度（像素/秒）"""
        if 23 not in points or 24 not in points:
            return 0
        cx = (points[23][0] + points[24][0]) / 2
        cy = (points[23][1] + points[24][1]) / 2

        track_key = f"hip_{track_id}"
        prev = self._prev_positions.get(track_key)
        prev_t = self._last_time.get(track_key, 0)

        self._prev_positions[track_key] = (cx, cy)
        self._last_time[track_key] = now

        if prev is None or prev_t == 0:
            return 0

        dt = now - prev_t
        if dt <= 0:
            return 0
        dx = cx - prev[0]
        dy = cy - prev[1]
        dist = math.sqrt(dx * dx + dy * dy)
        return dist / dt

    @staticmethod
    def _calc_torso_angle(sx, sy, hx, hy):
        dx = hx - sx
        dy = hy - sy
        if dy == 0:
            return 90
        return math.degrees(math.atan2(abs(dx), dy))

    @staticmethod
    def _calc_knee_angle(hip, knee, ankle):
        v1 = (hip[0] - knee[0], hip[1] - knee[1])
        v2 = (ankle[0] - knee[0], ankle[1] - knee[1])
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        mag1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2)
        mag2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2)
        if mag1 == 0 or mag2 == 0:
            return 180
        cos_angle = max(-1, min(1, dot / (mag1 * mag2)))
        return math.degrees(math.acos(cos_angle))

    @staticmethod
    def _calc_confidence(landmarks):
        vis = [lm.visibility for lm in landmarks]
        return sum(vis) / len(vis) if vis else 0

    def release(self):
        if self.landmarker:
            self.landmarker.close()
            self.landmarker = None
