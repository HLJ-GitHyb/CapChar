"""画面渲染引擎：绘制检测框、骨架、标签和视觉效果（性能优化版）"""
import cv2
import numpy as np
from config import SKELETON_CONNECTIONS, BBOX_THICKNESS, TRAIL_LENGTH

# 预计算颜色缓存，避免每帧重复转换
_color_cache = {}


def _hex_to_bgr_cached(hex_color):
    if hex_color not in _color_cache:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        _color_cache[hex_color] = (b, g, r)
    return _color_cache[hex_color]


class FrameRenderer:
    """在帧上绘制所有可视化元素（优化：零全帧 copy）"""

    def __init__(self):
        self._trails = {}
        # 预分配标签 alpha 缓冲区
        self._label_buf = None

    def render(self, frame_bgr, persons, show_skeleton=True, show_trails=True):
        """在帧上直接绘制（in-place，不复制整个帧）"""
        # 直接在原帧上绘制，避免全帧 copy
        canvas = frame_bgr

        # 无检测结果时直接返回，跳过所有开销
        if not persons:
            return canvas

        for p in persons:
            color_bgr = _hex_to_bgr_cached(p["color"])

            if show_trails:
                self._draw_trail(canvas, p["id"], p["bbox"], color_bgr)

            self._draw_bbox(canvas, p["bbox"], color_bgr, p["confidence"])

            if show_skeleton and p.get("landmarks"):
                self._draw_skeleton(canvas, p["landmarks"], color_bgr)

            self._draw_label(canvas, p["bbox"], p["state"], p["confidence"], color_bgr)

        return canvas

    def _draw_bbox(self, canvas, bbox, color_bgr, confidence):
        """绘制包围框（移除全帧 copy 发光，改用直接绘制）"""
        x1, y1, x2, y2 = bbox
        t = BBOX_THICKNESS

        # 外框（用更粗的线模拟发光，不做 addWeighted）
        outer_color = tuple(min(255, c // 2 + 60) for c in color_bgr)
        cv2.rectangle(canvas, (x1 - 1, y1 - 1), (x2 + 1, y2 + 1), outer_color, t + 2)

        # 主矩形框
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color_bgr, t)

        # 四角装饰
        corner_len = max(15, (x2 - x1) // 6)
        bright = tuple(min(255, c + 40) for c in color_bgr)
        corners = [
            (x1, y1, 1, 1), (x2, y1, -1, 1),
            (x1, y2, 1, -1), (x2, y2, -1, -1),
        ]
        for cx, cy, dx, dy in corners:
            cv2.line(canvas, (cx, cy), (cx + dx * corner_len, cy), bright, t + 1)
            cv2.line(canvas, (cx, cy), (cx, cy + dy * corner_len), bright, t + 1)

        # 置信度条（直接绘制，不做混合）
        bar_y = y1 - 8
        if bar_y > 10:
            bar_w = int((x2 - x1) * confidence)
            cv2.rectangle(canvas, (x1, bar_y), (x2, bar_y + 4), (40, 40, 40), -1)
            cv2.rectangle(canvas, (x1, bar_y), (x1 + bar_w, bar_y + 4), color_bgr, -1)

    def _draw_skeleton(self, canvas, landmarks, color_bgr):
        """绘制骨架连线（简化为单次绘制）"""
        h, w = canvas.shape[:2]
        bright = tuple(min(255, c + 60) for c in color_bgr)
        for i1, i2 in SKELETON_CONNECTIONS:
            lm1 = landmarks[i1] if isinstance(landmarks, list) else landmarks.landmark[i1]
            lm2 = landmarks[i2] if isinstance(landmarks, list) else landmarks.landmark[i2]
            if lm1.visibility > 0.5 and lm2.visibility > 0.5:
                pt1 = (int(lm1.x * w), int(lm1.y * h))
                pt2 = (int(lm2.x * w), int(lm2.y * h))
                cv2.line(canvas, pt1, pt2, bright, 2, cv2.LINE_AA)

    def _draw_label(self, canvas, bbox, state, confidence, color_bgr):
        """绘制标签（用简单半透明矩形替代 addWeighted）"""
        x1, y1, x2, y2 = bbox
        label = f"{state} {confidence:.0%}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.55
        thickness = 1

        (tw, th), _ = cv2.getTextSize(label, font, scale, thickness)
        pad = 6

        lx1 = x1
        ly1 = max(0, y1 - th - pad * 2 - 12)
        lx2 = lx1 + tw + pad * 2
        ly2 = ly1 + th + pad * 2

        # 半透明背景：直接在 ROI 上做简单 alpha 混合（比 addWeighted 快）
        roi = canvas[ly1:ly2, lx1:lx2]
        if roi.size > 0:
            # 用整数运算的简单混合，避免 addWeighted 的函数调用开销
            alpha = 0.7
            roi[:, :, 0] = (roi[:, :, 0] * (1 - alpha) + color_bgr[0] * alpha).astype(np.uint8)
            roi[:, :, 1] = (roi[:, :, 1] * (1 - alpha) + color_bgr[1] * alpha).astype(np.uint8)
            roi[:, :, 2] = (roi[:, :, 2] * (1 - alpha) + color_bgr[2] * alpha).astype(np.uint8)

        cv2.rectangle(canvas, (lx1, ly1), (lx2, ly2), color_bgr, 1)
        cv2.putText(canvas, label, (lx1 + pad, ly1 + th + pad),
                    font, scale, (255, 255, 255), thickness, cv2.LINE_AA)

    def _draw_trail(self, canvas, person_id, bbox, color_bgr):
        cx = (bbox[0] + bbox[2]) // 2
        cy = (bbox[1] + bbox[3]) // 2

        trail = self._trails.get(person_id)
        if trail is None:
            trail = []
            self._trails[person_id] = trail

        trail.append((cx, cy))
        if len(trail) > TRAIL_LENGTH:
            # 裁剪而不是重建列表
            del trail[:len(trail) - TRAIL_LENGTH]

        n = len(trail)
        if n < 2:
            return
        # 用 polylines 批量绘制替代逐段 line
        pts = np.array(trail, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(canvas, [pts], False, color_bgr, 2, cv2.LINE_AA)

    def reset_trails(self):
        self._trails.clear()
