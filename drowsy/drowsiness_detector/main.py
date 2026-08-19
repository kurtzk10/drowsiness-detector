"""
Real-Time Driver Drowsiness Detection System
============================================
Run:  python main.py
Press Q to quit.

Detects:
  - Eye closure    (EAR + CNN eye-state + PERCLOS)
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
    CALIBRATION_SECONDS, EAR_CALIBRATION, IR_MODE, \
    CNN_ENABLED, CNN_MODEL_PATH, CNN_CLOSED_THRESHOLD, CNN_EYE_MARGIN, \
    CNN_FUSION_MODE
from metrics import (calculate_EAR, calculate_MAR, calculate_head_pose,
                     get_eye_points_for_drawing, get_mouth_points_for_drawing,
                     get_eye_crops)
from state import StateManager, Calibrator
from alert import trigger_alert
from filters import apply_ir_filter
from display import (draw_landmarks, draw_ui, draw_alert_banner, draw_no_face,
                     draw_calibration, draw_ir_badge)
from inference.eye_classifier import EyeClassifier

from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker, FaceLandmarkerOptions, RunningMode
)


def fuse_eye_state(ear_closed, cnn_closed, mode):
    """
    Combine the geometric (EAR) and appearance (CNN) verdicts on eye closure.

    `cnn_closed` is None when the CNN had nothing to say this frame — model
    disabled or unloaded, or both eye crops fell outside the frame. In that
    case every mode degrades to the EAR verdict, so losing the model can
    never leave the detector with no opinion at all.

    See CNN_FUSION_MODE in config.py for what each mode is for.
    """
    if cnn_closed is None or mode == "ear":
        return ear_closed
    if mode == "or":
        return ear_closed or cnn_closed
    if mode == "and":
        return ear_closed and cnn_closed
    if mode == "cnn":
        return cnn_closed
    # Unknown mode in config — fall back to the geometric signal rather than
    # silently disabling detection.
    return ear_closed


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

    # ── CNN eye-state classifier ──────────────────────────────────
    # Optional second opinion on eye closure. Construction never raises:
    # a missing or unreadable model leaves is_available() False and the
    # detector runs on EAR alone.
    eye_clf = None
    if CNN_ENABLED:
        cnn_path = os.path.join(os.path.dirname(__file__), CNN_MODEL_PATH)
        eye_clf = EyeClassifier(cnn_path)
        if eye_clf.is_available():
            print(f"[INFO] CNN fusion mode: {CNN_FUSION_MODE} "
                  f"(closed if p > {CNN_CLOSED_THRESHOLD})")
    else:
        print("[INFO] CNN disabled in config — EAR-only eye detection.")

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

        # ── CNN eye state ─────────────────────────────────────────
        # Crops come off `rgb`, the exact buffer handed to MediaPipe, so the
        # landmark dots and banners drawn onto `frame` further down can never
        # end up inside a patch the model sees.
        cnn_prob = None
        if eye_clf is not None and eye_clf.is_available():
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            left_crop, right_crop = get_eye_crops(face_lm, gray, w, h,
                                                  CNN_EYE_MARGIN)
            cnn_prob = eye_clf.predict(left_crop, right_crop)

        ear_closed = ear < state.ear_threshold
        cnn_closed = None if cnn_prob is None else cnn_prob > CNN_CLOSED_THRESHOLD
        eyes_closed = fuse_eye_state(ear_closed, cnn_closed, CNN_FUSION_MODE)

        # Feed PERCLOS the fused verdict only once calibration has settled.
        # Before that the eyes-closed cutoff is still provisional, so the
        # window keeps storing raw EAR and re-scores it when the per-driver
        # threshold lands.
        perclos = state.update_perclos(
            ear, eyes_closed if calibrator.done else None)

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
        # eyes_closed was already decided by the EAR/CNN fusion above.
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
        draw_ui(frame, ear, mar, yaw, pitch, perclos, state, alerts_fired,
                fps, cnn_prob=cnn_prob, eyes_closed=eyes_closed)

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
