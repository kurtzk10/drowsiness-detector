"""
Real-Time Driver Drowsiness Detection System
============================================
Run:  python main.py
Press Q to quit.

Detects:
  - Eye closure    (EAR + PERCLOS)
  - Yawning        (MAR)
  - Not looking    (Head Pose: yaw / pitch)
"""

import cv2
import mediapipe as mp
import time
import sys
import os

from config import CAMERA_SOURCE, MAR_THRESHOLD, \
    HEAD_YAW_THRESHOLD, HEAD_PITCH_THRESHOLD, SHOW_LANDMARKS, \
    CALIBRATION_SECONDS, EAR_CALIBRATION, IR_MODE
from metrics import (calculate_EAR, calculate_MAR, calculate_head_pose,
                     get_eye_points_for_drawing, get_mouth_points_for_drawing)
from state import StateManager, Calibrator
from alert import trigger_alert
from filters import apply_ir_filter
from display import (draw_landmarks, draw_ui, draw_alert_banner, draw_no_face,
                     draw_calibration, draw_ir_badge)

from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker, FaceLandmarkerOptions, RunningMode
)


def main():
    # ── MediaPipe setup ───────────────────────────────────────────
    model_path = os.path.join(os.path.dirname(__file__), "face_landmarker.task")
    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.6,
        min_face_presence_confidence=0.6,
        min_tracking_confidence=0.6,
    )
    face_landmarker = FaceLandmarker.create_from_options(options)

    # ── Camera setup ──────────────────────────────────────────────
    print(f"[INFO] Opening camera: {CAMERA_SOURCE}")
    cap = cv2.VideoCapture(CAMERA_SOURCE)
    if not cap.isOpened():
        print("[ERROR] Cannot open camera. Check CAMERA_SOURCE in config.py")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)

    # ── State ─────────────────────────────────────────────────────
    state = StateManager()
    calibrator = Calibrator(CALIBRATION_SECONDS)
    alerts_fired = 0

    # Active banner display state
    active_banner = None   # ("text", "sub", expire_time)

    # FPS tracking
    fps      = 0.0
    fps_prev = time.time()
    fps_count = 0
    frame_count = 0

    ir_enabled = IR_MODE

    print("[INFO] System running. Q=quit, C=recalibrate, I=toggle IR sim.")
    print(f"[INFO] Calibrating for {CALIBRATION_SECONDS:.0f}s - "
          "look straight ahead at the road.")
    if ir_enabled:
        print("[INFO] IR simulation ON (monochrome).")

    def read_key():
        """Poll the keyboard. Returns True if the user wants to quit."""
        nonlocal ir_enabled
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            return True
        if key == ord('c'):
            calibrator.reset()
            print("[INFO] Recalibrating — look straight ahead at the road.")
        if key == ord('i'):
            ir_enabled = not ir_enabled
            print(f"[INFO] IR simulation {'ON' if ir_enabled else 'OFF'}.")
        return False

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[WARN] Frame read failed — retrying...")
            time.sleep(0.05)
            continue

        # Flip for mirror view (comment out for dashcam)
        frame = cv2.flip(frame, 1)

        # IR simulation — applied before detection so MediaPipe runs on
        # the same monochrome input a real IR camera would deliver.
        if ir_enabled:
            frame = apply_ir_filter(frame)

        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        frame_count += 1
        results = face_landmarker.detect_for_video(mp_image, frame_count)

        # Badge drawn on the display copy only (rgb above is already made,
        # so this never contaminates the detection input).
        if ir_enabled:
            draw_ir_badge(frame)

        # ── FPS ───────────────────────────────────────────────────
        fps_count += 1
        now = time.time()
        if now - fps_prev >= 1.0:
            fps = fps_count / (now - fps_prev)
            fps_count = 0
            fps_prev  = now

        # ── No face ───────────────────────────────────────────────
        if not results.face_landmarks:
            if not calibrator.done:
                draw_calibration(frame, calibrator.remaining(),
                                 calibrator.duration, face_missing=True)
            else:
                draw_no_face(frame)
            cv2.imshow("Drowsiness Detector — Q to quit", frame)
            if read_key():
                break
            continue

        face_lm = results.face_landmarks[0]

        # ── Compute metrics ───────────────────────────────────────
        ear     = calculate_EAR(face_lm, w, h)
        mar     = calculate_MAR(face_lm, w, h)
        yaw, pitch = calculate_head_pose(face_lm, w, h)
        perclos = state.update_perclos(ear)

        # ── Draw landmarks ────────────────────────────────────────
        if SHOW_LANDMARKS:
            l_eye, r_eye = get_eye_points_for_drawing(face_lm, w, h)
            mouth_pts    = get_mouth_points_for_drawing(face_lm, w, h)
            draw_landmarks(frame, l_eye, r_eye, mouth_pts, ear, mar,
                           state.ear_threshold)

        # ── Calibration phase ─────────────────────────────────────
        # Capture the driver's neutral head pose before detecting so
        # "not looking" is measured as deviation from where they sit.
        if not calibrator.done:
            remaining = calibrator.add_sample(yaw, pitch, ear)
            if not calibrator.done:
                draw_calibration(frame, remaining, calibrator.duration)
                cv2.imshow("Drowsiness Detector — Q to quit", frame)
                if read_key():
                    break
                continue
            print("[INFO] Calibration complete. Neutral pose captured: "
                  f"yaw={calibrator.yaw_offset:+.1f}deg, "
                  f"pitch={calibrator.pitch_offset:+.1f}deg")
            if EAR_CALIBRATION:
                state.set_ear_threshold(calibrator.ear_threshold)
                print(f"[INFO] Eye baseline EAR={calibrator.ear_baseline:.3f} "
                      f"-> eyes-closed threshold={calibrator.ear_threshold:.3f}")

        # ── Apply calibration offsets (deviation from neutral) ────
        yaw   -= calibrator.yaw_offset
        pitch -= calibrator.pitch_offset

        # ── Check conditions ──────────────────────────────────────
        eyes_closed  = ear < state.ear_threshold
        mouth_open   = mar > MAR_THRESHOLD
        head_off     = (abs(yaw)   > HEAD_YAW_THRESHOLD or
                        abs(pitch) > HEAD_PITCH_THRESHOLD)
        perclos_high = state.is_drowsy_perclos(perclos)

        # ── Alert logic ───────────────────────────────────────────
        if state.check("eyes", eyes_closed):
            trigger_alert("drowsy")
            alerts_fired += 1
            active_banner = ("WAKE UP!",
                             f"Eyes closed > {int(ear*1000)/1000}",
                             time.time() + 3.0)

        elif perclos_high and not state.in_cooldown("eyes"):
            trigger_alert("perclos")
            alerts_fired += 1
            active_banner = ("DROWSY — PERCLOS HIGH",
                             f"{perclos*100:.0f}% eyes closed in window",
                             time.time() + 3.0)

        if state.check("mouth", mouth_open):
            trigger_alert("yawning")
            alerts_fired += 1
            active_banner = ("YAWNING DETECTED",
                             "Take a break soon",
                             time.time() + 3.0)

        if state.check("head", head_off):
            trigger_alert("not_looking")
            alerts_fired += 1
            active_banner = ("EYES ON THE ROAD!",
                             f"Yaw:{yaw:+.0f}deg  Pitch:{pitch:+.0f}deg",
                             time.time() + 3.0)

        # ── Draw UI ───────────────────────────────────────────────
        draw_ui(frame, ear, mar, yaw, pitch, perclos, state, alerts_fired, fps)

        # Banner
        if active_banner and time.time() < active_banner[2]:
            draw_alert_banner(frame, active_banner[0], active_banner[1])
        else:
            active_banner = None

        cv2.imshow("Drowsiness Detector — Q to quit", frame)
        if read_key():
            break

    cap.release()
    cv2.destroyAllWindows()
    face_landmarker.close()
    print("[INFO] System stopped.")


if __name__ == "__main__":
    main()
