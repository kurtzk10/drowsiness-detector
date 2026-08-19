import cv2
import mediapipe as mp
import time
import sys
import os

from config import CAMERA_SOURCE, EAR_THRESHOLD, MAR_THRESHOLD, \
    HEAD_YAW_THRESHOLD, HEAD_PITCH_THRESHOLD, SHOW_LANDMARKS, \
    CALIBRATION_SECONDS, EAR_THRESHOLD_MULTIPLIER, MAR_OPEN_DELTA, MAR_THRESHOLD_MIN, MAR_THRESHOLD_MAX, \
    HEAD_YAW_THRESHOLD_OFFSET, HEAD_PITCH_THRESHOLD_OFFSET, \
    CNN_ENABLED, CNN_MODEL_PATH, CNN_CLOSED_THRESHOLD, CNN_EYE_MARGIN, \
    CNN_FUSION_MODE, IR_MODE
from metrics import (calculate_EAR, calculate_MAR, calculate_head_pose,
                     get_eye_points_for_drawing, get_mouth_points_for_drawing,
                     LEFT_EYE, RIGHT_EYE, extract_eye_crop)
from state import StateManager
from alert import trigger_alert, clear_alert
from display import draw_landmarks, draw_ui, draw_alert_banner, draw_no_face
from http_alerts import HttpAlertClient
from calibration import Calibrator
from discovery import PhoneDiscovery
from streamer import Streamer
from filters import apply_ir_filter

from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker, FaceLandmarkerOptions, RunningMode
)

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from inference.eye_classifier import EyeClassifier


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
    streamer = Streamer()
    streamer.start()
    calibrator = Calibrator(
        duration=CALIBRATION_SECONDS,
        ear_mult=EAR_THRESHOLD_MULTIPLIER,
        mar_delta=MAR_OPEN_DELTA,
        mar_min=MAR_THRESHOLD_MIN,
        mar_max=MAR_THRESHOLD_MAX,
        yaw_offset=HEAD_YAW_THRESHOLD_OFFSET,
        pitch_offset=HEAD_PITCH_THRESHOLD_OFFSET,
    )

    eye_classifier = EyeClassifier(CNN_MODEL_PATH)
    if CNN_ENABLED and eye_classifier.is_available():
        print(f"[INFO] CNN fusion mode: {CNN_FUSION_MODE} "
              f"(closed if p > {CNN_CLOSED_THRESHOLD})")
    elif not CNN_ENABLED:
        print("[INFO] CNN disabled in config — EAR-only eye detection.")

    # Dynamic thresholds (start with config defaults, updated after calibration)
    ear_th = EAR_THRESHOLD
    mar_th = MAR_THRESHOLD
    yaw_th = HEAD_YAW_THRESHOLD
    pitch_th = HEAD_PITCH_THRESHOLD

    baseline_yaw = 0.0
    baseline_pitch = 0.0
    yaw_offset = HEAD_YAW_THRESHOLD
    pitch_offset = HEAD_PITCH_THRESHOLD

    alerts_fired = 0
    active_banner = None
    alert_active = False  # tracks whether phone alarm is currently showing

    # FPS tracking
    fps = 0.0
    fps_prev = time.time()
    fps_count = 0
    frame_count = 0

    cal_phone_requested = False
    ir_enabled = IR_MODE

    print("[INFO] System running. Q=quit, C=calibrate, I=toggle IR sim.")
    if ir_enabled:
        print("[INFO] IR simulation ON (monochrome).")
    print("[INFO] Look at the camera to begin detection.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[WARN] Frame read failed — retrying...")
            time.sleep(0.05)
            continue

        frame = cv2.flip(frame, 1)

        # IR simulation runs before detection AND before raw_feed is
        # taken, so MediaPipe, the CNN crops and the phone stream all
        # see the same monochrome input a real IR camera would deliver.
        if ir_enabled:
            frame = apply_ir_filter(frame)

        raw_feed = frame.copy()
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

        # ── Check for remote calibration trigger ─────────────────
        if streamer.calibration_pending() and not calibrator.is_running() and not cal_phone_requested:
            calibrator.start()
            alert_active = False
            cal_phone_requested = True
            print("[CALIB] Remote calibration triggered by phone...")

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
                baseline_yaw = result.baseline_yaw
                baseline_pitch = result.baseline_pitch
                yaw_offset = HEAD_YAW_THRESHOLD_OFFSET
                pitch_offset = HEAD_PITCH_THRESHOLD_OFFSET
                yaw_th = yaw_offset
                pitch_th = pitch_offset
                print(f"[CALIB] Baseline EAR={result.baseline_ear:.3f}, "
                      f"MAR={result.baseline_mar:.3f}, "
                      f"Yaw={baseline_yaw:+.1f}deg, Pitch={baseline_pitch:+.1f}deg")
                print(f"[CALIB] Dynamic thresholds: EAR<{ear_th}, "
                      f"MAR>{mar_th}, Yaw offset ±{yaw_offset}deg, Pitch offset ±{pitch_offset}deg")

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

            _, jpeg = cv2.imencode(".jpg", raw_feed, [cv2.IMWRITE_JPEG_QUALITY, 55])
            streamer.push_jpeg(jpeg.tobytes())

            cv2.imshow("Drowsiness Detector — Q to quit, C to calibrate", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            continue

        # ── Remote calibration done ───────────────────────────────
        if cal_phone_requested and not calibrator.is_running():
            cal_phone_requested = False
            r = calibrator.get_result()
            streamer.complete_calibration(
                {"status": "ok", "thresholds": r.thresholds} if r and r.is_valid() else None
            )
            print("[CALIB] Remote calibration complete, thresholds sent to phone")

        # ── No face ───────────────────────────────────────────────
        if not results.face_landmarks:
            draw_no_face(frame)
            _, jpeg = cv2.imencode(".jpg", raw_feed, [cv2.IMWRITE_JPEG_QUALITY, 55])
            streamer.push_jpeg(jpeg.tobytes())
            cv2.imshow("Drowsiness Detector — Q to quit, C to calibrate", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord('c'):
                calibrator.start()
                print("[CALIB] Starting calibration...")
            if key == ord('i'):
                ir_enabled = not ir_enabled
                print(f"[INFO] IR simulation {'ON' if ir_enabled else 'OFF'}.")
            continue

        # ── Pick closest face ─────────────────────────────────────
        face_lm = _pick_closest_face(results.face_landmarks, w, h)
        if face_lm is None:
            draw_no_face(frame)
            _, jpeg = cv2.imencode(".jpg", raw_feed, [cv2.IMWRITE_JPEG_QUALITY, 55])
            streamer.push_jpeg(jpeg.tobytes())
            cv2.imshow("Drowsiness Detector — Q to quit, C to calibrate", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord('c'):
                calibrator.start()
                print("[CALIB] Starting calibration...")
            if key == ord('i'):
                ir_enabled = not ir_enabled
                print(f"[INFO] IR simulation {'ON' if ir_enabled else 'OFF'}.")
            continue

        # ── Compute metrics ───────────────────────────────────────
        ear = calculate_EAR(face_lm, w, h)
        mar = calculate_MAR(face_lm, w, h)
        yaw, pitch = calculate_head_pose(face_lm, w, h)
        rel_yaw = yaw - baseline_yaw
        rel_pitch = pitch - baseline_pitch

        # ── Draw landmarks ────────────────────────────────────────
        if SHOW_LANDMARKS:
            l_eye, r_eye = get_eye_points_for_drawing(face_lm, w, h)
            mouth_pts = get_mouth_points_for_drawing(face_lm, w, h)
            draw_landmarks(frame, l_eye, r_eye, mouth_pts, ear, mar, ear_th, mar_th)

        # ── Check conditions ──────────────────────────────────────
        # ── CNN eye state ─────────────────────────────────────────
        # Crops come off `raw_feed`, the untouched copy taken before any
        # drawing. Reading `frame` here would feed the model the landmark
        # dots painted over the eye a few lines above — patches unlike
        # anything in the training set.
        cnn_prob = None
        if CNN_ENABLED and eye_classifier.is_available():
            left_crop = extract_eye_crop(raw_feed, face_lm, LEFT_EYE, w, h,
                                         margin=CNN_EYE_MARGIN)
            right_crop = extract_eye_crop(raw_feed, face_lm, RIGHT_EYE, w, h,
                                          margin=CNN_EYE_MARGIN)
            cnn_prob = eye_classifier.predict(left_crop, right_crop)

        ear_closed = ear < ear_th
        cnn_closed = None if cnn_prob is None else cnn_prob > CNN_CLOSED_THRESHOLD
        eyes_closed = fuse_eye_state(ear_closed, cnn_closed, CNN_FUSION_MODE)
        mouth_open = mar > mar_th
        head_off = (abs(rel_yaw) > yaw_offset or abs(rel_pitch) > pitch_offset)

        # Scored from the fused verdict, so PERCLOS measures the same
        # eye state the alert does — and picks up the calibrated
        # threshold, which the raw-EAR path never did.
        perclos = state.update_perclos(ear, eyes_closed)
        perclos_high = state.is_drowsy_perclos(perclos)

        # ── Alert logic ───────────────────────────────────────────
        if state.check("eyes", eyes_closed):
            trigger_alert("drowsy", http_client)
            alerts_fired += 1
            alert_active = True
            active_banner = ("WAKE UP!",
                             f"Eyes closed > {int(ear*1000)/1000}",
                             time.time() + 3.0)

        # Routed through check() like every other alert, so a sustained
        # high reading fires once per ALERT_COOLDOWN_SECONDS instead of
        # on every frame. The eyes-cooldown test comes first and has no
        # side effects, so a PERCLOS alert is suppressed rather than
        # merely delayed while a drowsy alert is still current.
        elif not state.in_cooldown("eyes") and state.check("perclos", perclos_high):
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
                             f"Yaw:{rel_yaw:+.0f}deg  Pitch:{rel_pitch:+.0f}deg",
                             time.time() + 3.0)

        # ── Auto-clear ────────────────────────────────────────────
        # Same verdicts that fired the alert, so recovery can never
        # disagree with detection.
        if alert_active and state.is_driver_alert(eyes_closed, mouth_open,
                                                  head_off):
            clear_alert(http_client)
            alert_active = False
            active_banner = None

        # ── Draw UI ───────────────────────────────────────────────
        draw_ui(frame, ear, mar, rel_yaw, rel_pitch, perclos, state, alerts_fired,
                fps, ear_th, mar_th, yaw_offset, pitch_offset,
                cnn_prob=cnn_prob, eyes_closed=eyes_closed)

        if active_banner and time.time() < active_banner[2]:
            draw_alert_banner(frame, active_banner[0], active_banner[1])
        else:
            active_banner = None

        # Calibration hint
        cv2.putText(frame, "C: Calibrate", (10, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1,
                    cv2.LINE_AA)

        _, jpeg = cv2.imencode(".jpg", raw_feed, [cv2.IMWRITE_JPEG_QUALITY, 55])
        streamer.push_jpeg(jpeg.tobytes())

        cv2.imshow("Drowsiness Detector — Q to quit, C to calibrate", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        if key == ord('c'):
            calibrator.start()
            alert_active = False
            print("[CALIB] Starting calibration...")
        if key == ord('i'):
            ir_enabled = not ir_enabled
            print(f"[INFO] IR simulation {'ON' if ir_enabled else 'OFF'}.")

    cap.release()
    cv2.destroyAllWindows()
    face_landmarker.close()
    http_client.shutdown()
    streamer.stop()
    discovery.stop()
    print("[INFO] System stopped.")


if __name__ == "__main__":
    main()
