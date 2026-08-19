import cv2
import numpy as np
from config import (
    EAR_THRESHOLD, MAR_THRESHOLD,
    HEAD_YAW_THRESHOLD, HEAD_PITCH_THRESHOLD,
    EAR_ALERT_SECONDS, MAR_ALERT_SECONDS, HEAD_ALERT_SECONDS,
    SHOW_LANDMARKS, SHOW_FPS
)

# Colors (BGR)
GREEN  = (60,  200, 60)
YELLOW = (0,   200, 200)
RED    = (50,  50,  220)
WHITE  = (255, 255, 255)
BLACK  = (0,   0,   0)
GRAY   = (160, 160, 160)
DARK   = (30,  30,  30)


def draw_landmarks(frame, eye_pts_l, eye_pts_r, mouth_pts, ear, mar,
                   ear_threshold=EAR_THRESHOLD):
    if not SHOW_LANDMARKS:
        return
    eye_color   = RED if ear < ear_threshold  else GREEN
    mouth_color = RED if mar > MAR_THRESHOLD   else GREEN

    for pt in eye_pts_l + eye_pts_r:
        cv2.circle(frame, (int(pt[0]), int(pt[1])), 2, eye_color, -1)
    for pt in mouth_pts:
        cv2.circle(frame, (int(pt[0]), int(pt[1])), 2, mouth_color, -1)


def _bar(frame, x, y, w, h, value, max_val, color_ok, color_warn, color_danger, label):
    """Draw a horizontal progress bar."""
    pct = min(1.0, value / max_val) if max_val > 0 else 0
    fill = int(w * pct)

    # Background
    cv2.rectangle(frame, (x, y), (x + w, y + h), (60, 60, 60), -1)
    # Fill
    if pct < 0.5:
        color = color_ok
    elif pct < 0.8:
        color = color_warn
    else:
        color = color_danger
    if fill > 0:
        cv2.rectangle(frame, (x, y), (x + fill, y + h), color, -1)
    # Border
    cv2.rectangle(frame, (x, y), (x + w, y + h), GRAY, 1)
    # Label
    cv2.putText(frame, label, (x, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1, cv2.LINE_AA)


def draw_ui(frame, ear, mar, yaw, pitch, perclos, state, alerts_fired, fps,
            cnn_prob=None, eyes_closed=None):
    h, w = frame.shape[:2]
    # Per-driver eyes-closed cutoff (set during calibration); falls back
    # to the fixed config value before calibration completes.
    ear_thr = getattr(state, "ear_threshold", EAR_THRESHOLD)

    # ── Semi-transparent sidebar ──────────────────────────────────
    overlay = frame.copy()
    panel_x = w - 260
    cv2.rectangle(overlay, (panel_x - 10, 0), (w, h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    x0 = panel_x
    y  = 20

    # Title
    cv2.putText(frame, "DROWSINESS", (x0, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA)
    y += 16
    cv2.putText(frame, "DETECTOR", (x0, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA)
    y += 20
    cv2.line(frame, (x0, y), (w - 10, y), GRAY, 1)
    y += 14

    # ── Metric values ─────────────────────────────────────────────
    def metric_line(label, value_str, ok):
        nonlocal y
        color = GREEN if ok else RED
        cv2.putText(frame, label, (x0, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, GRAY, 1, cv2.LINE_AA)
        cv2.putText(frame, value_str, (x0 + 95, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
        y += 18

    metric_line("EAR:   ", f"{ear:.3f}", ear >= ear_thr)
    metric_line("MAR:   ", f"{mar:.3f}", mar <= MAR_THRESHOLD)
    metric_line("YAW:   ", f"{yaw:+.1f}deg", abs(yaw) <= HEAD_YAW_THRESHOLD)
    metric_line("PITCH: ", f"{pitch:+.1f}deg", abs(pitch) <= HEAD_PITCH_THRESHOLD)
    metric_line("PERCLOS:", f"{perclos*100:.1f}%", perclos < 0.80)
    # Only shown when the CNN actually produced a verdict this frame.
    if cnn_prob is not None:
        metric_line("CNN shut:", f"{cnn_prob*100:.0f}%", cnn_prob <= 0.5)
    y += 4
    cv2.line(frame, (x0, y), (w - 10, y), GRAY, 1)
    y += 12

    # ── Progress bars ─────────────────────────────────────────────
    bar_w = w - x0 - 10

    # Track the fused verdict when the caller supplies it, so the bar and
    # the alert it predicts never disagree.
    eye_cond      = (ear < ear_thr) if eyes_closed is None else eyes_closed
    eye_elapsed   = state.get_elapsed("eyes",  eye_cond)
    mouth_elapsed = state.get_elapsed("mouth", mar > MAR_THRESHOLD)
    head_cond     = abs(yaw) > HEAD_YAW_THRESHOLD or abs(pitch) > HEAD_PITCH_THRESHOLD
    head_elapsed  = state.get_elapsed("head",  head_cond)

    _bar(frame, x0, y, bar_w, 10, eye_elapsed,   EAR_ALERT_SECONDS,
         GREEN, YELLOW, RED, "Eyes closed")
    y += 26
    _bar(frame, x0, y, bar_w, 10, mouth_elapsed, MAR_ALERT_SECONDS,
         GREEN, YELLOW, RED, "Yawning")
    y += 26
    _bar(frame, x0, y, bar_w, 10, head_elapsed,  HEAD_ALERT_SECONDS,
         GREEN, YELLOW, RED, "Not looking")
    y += 26
    _bar(frame, x0, y, bar_w, 10, perclos,       1.0,
         GREEN, YELLOW, RED, "PERCLOS")
    y += 26

    cv2.line(frame, (x0, y), (w - 10, y), GRAY, 1)
    y += 12

    # ── Alert count ───────────────────────────────────────────────
    cv2.putText(frame, f"Alerts: {alerts_fired}", (x0, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1, cv2.LINE_AA)
    y += 18

    if SHOW_FPS:
        cv2.putText(frame, f"FPS: {fps:.1f}", (x0, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, GRAY, 1, cv2.LINE_AA)

    # ── Active alert banner ───────────────────────────────────────
    # Shown centered on the video feed (not in sidebar)
    return frame


def draw_alert_banner(frame, text, sub=""):
    h, w = frame.shape[:2]
    panel_w = w - 260
    # Red bar across top of video
    cv2.rectangle(frame, (0, 0), (panel_w, 60), (0, 0, 180), -1)
    cv2.putText(frame, text, (10, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, WHITE, 2, cv2.LINE_AA)
    if sub:
        cv2.putText(frame, sub, (10, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 255), 1, cv2.LINE_AA)


def draw_no_face(frame):
    h, w = frame.shape[:2]
    panel_w = w - 260
    cv2.putText(frame, "No face detected", (10, h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, YELLOW, 2, cv2.LINE_AA)


def draw_ir_badge(frame):
    """Small corner badge shown while IR simulation is active."""
    h, w = frame.shape[:2]
    cv2.putText(frame, "IR SIM", (10, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, GREEN, 2, cv2.LINE_AA)


def draw_calibration(frame, remaining, duration, face_missing=False):
    """
    Centered overlay shown during the startup calibration window.
    Tells the driver to hold a neutral gaze while the baseline is captured.
    """
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2

    # Dim the whole frame so the message stands out
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, h), BLACK, -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    def centered(text, y, scale, color, thick):
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        cv2.putText(frame, text, (cx - tw // 2, y),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)

    centered("CALIBRATING", cy - 40, 1.1, YELLOW, 2)

    if face_missing:
        centered("Please face the camera", cy, 0.6, RED, 1)
    else:
        centered("Look straight ahead, eyes open", cy, 0.6, WHITE, 1)

    # Progress bar
    bar_w = int(w * 0.4)
    bar_h = 14
    bx = cx - bar_w // 2
    by = cy + 25
    pct = 0.0 if duration <= 0 else max(0.0, min(1.0, 1.0 - remaining / duration))
    cv2.rectangle(frame, (bx, by), (bx + bar_w, by + bar_h), (60, 60, 60), -1)
    if pct > 0:
        cv2.rectangle(frame, (bx, by), (bx + int(bar_w * pct), by + bar_h), GREEN, -1)
    cv2.rectangle(frame, (bx, by), (bx + bar_w, by + bar_h), GRAY, 1)

    centered(f"{remaining:.1f}s", by + bar_h + 22, 0.6, WHITE, 1)
