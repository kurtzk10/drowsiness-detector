import cv2
import mediapipe as mp
import time
import sys
import os

from config import CAMERA_SOURCE, EAR_THRESHOLD, MAR_THRESHOLD, \
    HEAD_YAW_THRESHOLD, HEAD_PITCH_THRESHOLD, SHOW_LANDMARKS, \
    CALIBRATION_SECONDS, EAR_THRESHOLD_MULTIPLIER, MAR_THRESHOLD_MULTIPLIER, \
    HEAD_YAW_THRESHOLD_OFFSET, HEAD_PITCH_THRESHOLD_OFFSET
from metrics import (calculate_EAR, calculate_MAR, calculate_head_pose,
                     get_eye_points_for_drawing, get_mouth_points_for_drawing)
from state import StateManager
from alert import trigger_alert, clear_alert
from display import draw_landmarks, draw_ui, draw_alert_banner, draw_no_face
from http_alerts import HttpAlertClient
from calibration import Calibrator
from discovery import PhoneDiscovery

from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker, FaceLandmarkerOptions, RunningMode
)


def _get_face_bbox(face_lm, w, h):
    """Compute bounding box area for a face from its landmarks."""
    xs = [lm.x * w for lm in face_lm]
    ys = [lm.y * h for lm in face_lm]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def _pick_closest_face(face_landmarks_list, w, h):
    """Return the face landmarks with the largest bounding box (closest to camera)."""
    if not face_landmarks_list:
        return None
    if len(face_landmarks_list) == 1:
        return face_landmarks_list[0]
    best = max(face_landmarks_list, key=lambda lm: _get_face_bbox(lm, w, h))
    return best


def main():
    # ── MediaPipe setup ───────────────────────────────────────────
    model_path = os.path.join(os.path.dirname(__file__), "face_landmarker.task")
    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.VIDEO,
        num_faces=2,
        min_face_detection_confidence=0.6,
        min_face_presence_confidence=0.6,
        min_tracking_confidence=0.6,
        output_face_blendshapes=False,
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
    http_client = HttpAlertClient()
    discovery = PhoneDiscovery(
        on_phone_found=lambda ip, port: http_client.update_phone(ip, port)
    )
    discovery.start()
    calibrator = Calibrator(
        duration=CALIBRATION_SECONDS,
        ear_mult=EAR_THRESHOLD_MULTIPLIER,
        mar_mult=MAR_THRESHOLD_MULTIPLIER,
        yaw_offset=HEAD_YAW_THRESHOLD_OFFSET,
        pitch_offset=HEAD_PITCH_THRESHOLD_OFFSET,
    )

    # Dynamic thresholds (start with config defaults, updated after calibration)
    ear_th = EAR_THRESHOLD
    mar_th = MAR_THRESHOLD
    yaw_th = HEAD_YAW_THRESHOLD
    pitch_th = HEAD_PITCH_THRESHOLD

    alerts_fired = 0
    active_banner = None
    alert_active = False  # tracks whether phone alarm is currently showing

    # FPS tracking
    fps = 0.0
    fps_prev = time.time()
    fps_count = 0
    frame_count = 0

    print("[INFO] System running. Press Q to quit, C to calibrate.")
    print("[INFO] Look at the camera to begin detection.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[WARN] Frame read failed — retrying...")
            time.sleep(0.05)
            continue

        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        frame_count += 1
        results = face_landmarker.detect_for_video(mp_image, frame_count)

        # ── FPS ───────────────────────────────────────────────────
        fps_count += 1
        now = time.time()
        if now - fps_prev >= 1.0:
            fps = fps_count / (now - fps_prev)
            fps_count = 0
            fps_prev = now

        # ── Handle calibration sampling ───────────────────────────
        if calibrator.is_running():
            if results.face_landmarks:
                face_lm = _pick_closest_face(results.face_landmarks, w, h)
                if face_lm:
                    ear = calculate_EAR(face_lm, w, h)
                    mar = calculate_MAR(face_lm, w, h)
                    yaw, pitch = calculate_head_pose(face_lm, w, h)
                    calibrator.add_sample(ear, mar, yaw, pitch)

            result = calibrator.get_result()
            if result and result.is_valid():
                ear_th = result.thresholds["ear"]
                mar_th = result.thresholds["mar"]
                yaw_th = result.thresholds["yaw"]
                pitch_th = result.thresholds["pitch"]
                print(f"[CALIB] Baseline EAR={result.baseline_ear:.3f}, "
                      f"MAR={result.baseline_mar:.3f}")
                print(f"[CALIB] Dynamic thresholds: EAR<{ear_th}, "
                      f"MAR>{mar_th}, Yaw>{yaw_th}, Pitch>{pitch_th}")

            # Draw calibration overlay
            text = calibrator.get_status_text()
            if text:
                cv2.putText(frame, text, (w // 2 - 120, h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2,
                            cv2.LINE_AA)
                # Progress bar
                bar_w = 200
                bar_h = 10
                bx = w // 2 - bar_w // 2
                by = h // 2 + 20
                cv2.rectangle(frame, (bx, by), (bx + bar_w, by + bar_h),
                              (60, 60, 60), -1)
                fill = int(bar_w * calibrator.progress())
                cv2.rectangle(frame, (bx, by), (bx + fill, by + bar_h),
                              (0, 255, 255), -1)
                cv2.rectangle(frame, (bx, by), (bx + bar_w, by + bar_h),
                              (255, 255, 255), 1)

            cv2.imshow("Drowsiness Detector — Q to quit, C to calibrate", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            continue

        # ── No face ───────────────────────────────────────────────
        if not results.face_landmarks:
            draw_no_face(frame)
            cv2.imshow("Drowsiness Detector — Q to quit, C to calibrate", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord('c'):
                calibrator.start()
                print("[CALIB] Starting calibration...")
            continue

        # ── Pick closest face ─────────────────────────────────────
        face_lm = _pick_closest_face(results.face_landmarks, w, h)
        if face_lm is None:
            draw_no_face(frame)
            cv2.imshow("Drowsiness Detector — Q to quit, C to calibrate", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord('c'):
                calibrator.start()
                print("[CALIB] Starting calibration...")
            continue

        # ── Compute metrics ───────────────────────────────────────
        ear = calculate_EAR(face_lm, w, h)
        mar = calculate_MAR(face_lm, w, h)
        yaw, pitch = calculate_head_pose(face_lm, w, h)
        perclos = state.update_perclos(ear)

        # ── Draw landmarks ────────────────────────────────────────
        if SHOW_LANDMARKS:
            l_eye, r_eye = get_eye_points_for_drawing(face_lm, w, h)
            mouth_pts = get_mouth_points_for_drawing(face_lm, w, h)
            draw_landmarks(frame, l_eye, r_eye, mouth_pts, ear, mar, ear_th, mar_th)

        # ── Check conditions ──────────────────────────────────────
        eyes_closed = ear < ear_th
        mouth_open = mar > mar_th
        head_off = (abs(yaw) > yaw_th or abs(pitch) > pitch_th)
        perclos_high = state.is_drowsy_perclos(perclos)

        # ── Alert logic ───────────────────────────────────────────
        if state.check("eyes", eyes_closed):
            trigger_alert("drowsy", http_client)
            alerts_fired += 1
            alert_active = True
            active_banner = ("WAKE UP!",
                             f"Eyes closed > {int(ear*1000)/1000}",
                             time.time() + 3.0)

        elif perclos_high and not state.in_cooldown("eyes"):
            trigger_alert("perclos", http_client)
            alerts_fired += 1
            alert_active = True
            active_banner = ("DROWSY — PERCLOS HIGH",
                             f"{perclos*100:.0f}% eyes closed in window",
                             time.time() + 3.0)

        if state.check("mouth", mouth_open):
            trigger_alert("yawning", http_client)
            alerts_fired += 1
            alert_active = True
            active_banner = ("YAWNING DETECTED",
                             "Take a break soon",
                             time.time() + 3.0)

        if state.check("head", head_off):
            trigger_alert("not_looking", http_client)
            alerts_fired += 1
            alert_active = True
            active_banner = ("EYES ON THE ROAD!",
                             f"Yaw:{yaw:+.0f}deg  Pitch:{pitch:+.0f}deg",
                             time.time() + 3.0)

        # ── Auto-clear ────────────────────────────────────────────
        if alert_active and state.is_driver_alert(ear, mar, yaw, pitch):
            clear_alert(http_client)
            alert_active = False
            active_banner = None

        # ── Draw UI ───────────────────────────────────────────────
        draw_ui(frame, ear, mar, yaw, pitch, perclos, state, alerts_fired,
                fps, ear_th, mar_th)

        if active_banner and time.time() < active_banner[2]:
            draw_alert_banner(frame, active_banner[0], active_banner[1])
        else:
            active_banner = None

        # Calibration hint
        cv2.putText(frame, "C: Calibrate", (10, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1,
                    cv2.LINE_AA)

        cv2.imshow("Drowsiness Detector — Q to quit, C to calibrate", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == ord('c'):
            calibrator.start()
            alert_active = False
            print("[CALIB] Starting calibration...")

    cap.release()
    cv2.destroyAllWindows()
    face_landmarker.close()
    http_client.shutdown()
    discovery.stop()
    print("[INFO] System stopped.")


if __name__ == "__main__":
    main()
