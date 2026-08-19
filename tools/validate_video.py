"""
Run the detection pipeline over a recorded video, headless.

No camera, no window, no phone. Imports the real detection modules rather
than reimplementing them, so what it measures is what main.py does.

    ..\.venv\Scripts\python.exe tools\validate_video.py clip.mp4
    ..\.venv\Scripts\python.exe tools\validate_video.py clip.mp4 --csv out.csv
    ..\.venv\Scripts\python.exe tools\validate_video.py clip.mp4 --fusion and

Writes a per-frame CSV and prints a summary. Useful for comparing fusion
modes on identical footage, and for the FPS figures Results 3.3 needs.
"""
import argparse
import csv
import os
import sys
import time

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker, FaceLandmarkerOptions, RunningMode
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_APP = os.path.join(_ROOT, "drowsiness_detector")
for _p in (_APP, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config                                          # noqa: E402
from metrics import (calculate_EAR, calculate_MAR, calculate_head_pose,  # noqa: E402
                     LEFT_EYE, RIGHT_EYE, extract_eye_crop)
from state import StateManager                          # noqa: E402
from calibration import Calibrator                      # noqa: E402
from main import fuse_eye_state, _pick_closest_face     # noqa: E402
from inference.eye_classifier import EyeClassifier      # noqa: E402

ALERT_KINDS = ("drowsy", "perclos", "yawning", "not_looking")


def build_landmarker():
    return FaceLandmarker.create_from_options(FaceLandmarkerOptions(
        base_options=BaseOptions(
            model_asset_path=os.path.join(_APP, "face_landmarker.task")),
        running_mode=RunningMode.VIDEO,
        num_faces=2,
        min_face_detection_confidence=0.6,
        min_face_presence_confidence=0.6,
        min_tracking_confidence=0.6,
    ))


def run(video, csv_path, fusion_mode, calib_seconds):
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        sys.exit(f"[ERROR] Cannot open video: {video}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    print(f"[INFO] {video}")
    print(f"[INFO] {total} frames @ {src_fps:.1f} FPS source")
    print(f"[INFO] fusion mode: {fusion_mode}")

    # Video clock. Durations must be measured in the clip's own seconds,
    # not the machine's, or a fast decode starves every duration-gated
    # alert and the run stops being reproducible.
    clock = {"t": 0.0}

    landmarker = build_landmarker()
    clf = EyeClassifier(config.CNN_MODEL_PATH)
    state = StateManager(now_fn=lambda: clock["t"])
    calibrator = Calibrator(
        duration=calib_seconds,
        ear_mult=config.EAR_THRESHOLD_MULTIPLIER,
        mar_delta=config.MAR_OPEN_DELTA,
        mar_min=config.MAR_THRESHOLD_MIN,
        mar_max=config.MAR_THRESHOLD_MAX,
        yaw_offset=config.HEAD_YAW_THRESHOLD_OFFSET,
        pitch_offset=config.HEAD_PITCH_THRESHOLD_OFFSET,
    )
    calibrator.start()
    # Calibrate over a fixed number of FRAMES, not wall-clock seconds:
    # a clip replays far faster than real time, so a time-driven
    # calibration would finish at a machine-dependent point (or never).
    calib_frames = max(1, int(calib_seconds * src_fps))
    print(f"[INFO] calibrating over first {calib_frames} frames")

    ear_th, mar_th = config.EAR_THRESHOLD, config.MAR_THRESHOLD
    yaw_off = config.HEAD_YAW_THRESHOLD_OFFSET
    pitch_off = config.HEAD_PITCH_THRESHOLD_OFFSET
    base_yaw = base_pitch = 0.0

    alerts = {k: 0 for k in ALERT_KINDS}
    rows, faceless, idx = [], 0, 0
    proc_start = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        clock["t"] = idx / src_fps
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # VIDEO mode needs strictly increasing timestamps; derive them from
        # the source frame rate so results do not depend on how fast this
        # machine happens to decode.
        ts = int(idx * (1000.0 / src_fps))
        res = landmarker.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)

        face = _pick_closest_face(res.face_landmarks, w, h) \
            if res.face_landmarks else None
        if face is None:
            faceless += 1
            rows.append({"frame": idx, "t": round(idx / src_fps, 3),
                         "face": 0})
            continue

        ear = calculate_EAR(face, w, h)
        mar = calculate_MAR(face, w, h)
        yaw, pitch = calculate_head_pose(face, w, h)

        if calibrator.is_running():
            calibrator.add_sample(ear, mar, yaw, pitch)
            if idx >= calib_frames:
                calibrator.finish()
            r = calibrator.get_result()
            if r and r.is_valid():
                ear_th = r.thresholds["ear"]
                mar_th = r.thresholds["mar"]
                base_yaw, base_pitch = r.baseline_yaw, r.baseline_pitch
                print(f"[CALIB] ear_th={ear_th}  mar_th={mar_th}  "
                      f"baseline yaw={base_yaw:+.1f} pitch={base_pitch:+.1f}")
            rows.append({"frame": idx, "t": round(idx / src_fps, 3),
                         "face": 1, "calibrating": 1,
                         "ear": ear, "mar": mar})
            continue

        rel_yaw, rel_pitch = yaw - base_yaw, pitch - base_pitch

        cnn_prob = None
        if config.CNN_ENABLED and clf.is_available():
            lc = extract_eye_crop(frame, face, LEFT_EYE, w, h,
                                  margin=config.CNN_EYE_MARGIN)
            rc = extract_eye_crop(frame, face, RIGHT_EYE, w, h,
                                  margin=config.CNN_EYE_MARGIN)
            cnn_prob = clf.predict(lc, rc)

        ear_closed = ear < ear_th
        cnn_closed = (None if cnn_prob is None
                      else cnn_prob > config.CNN_CLOSED_THRESHOLD)
        eyes_closed = fuse_eye_state(ear_closed, cnn_closed, fusion_mode)
        mouth_open = mar > mar_th
        head_off = abs(rel_yaw) > yaw_off or abs(rel_pitch) > pitch_off

        perclos = state.update_perclos(ear, eyes_closed)
        perclos_high = state.is_drowsy_perclos(perclos)

        fired = []
        if state.check("eyes", eyes_closed):
            fired.append("drowsy")
        elif not state.in_cooldown("eyes") and state.check("perclos", perclos_high):
            fired.append("perclos")
        if state.check("mouth", mouth_open):
            fired.append("yawning")
        if state.check("head", head_off):
            fired.append("not_looking")
        for k in fired:
            alerts[k] += 1

        rows.append({
            "frame": idx, "t": round(idx / src_fps, 3), "face": 1,
            "calibrating": 0,
            "ear": ear, "mar": mar,
            "yaw": rel_yaw, "pitch": rel_pitch,
            "cnn_prob": "" if cnn_prob is None else round(cnn_prob, 4),
            "ear_closed": int(ear_closed),
            "cnn_closed": "" if cnn_closed is None else int(cnn_closed),
            "eyes_closed": int(eyes_closed),
            "mouth_open": int(mouth_open), "head_off": int(head_off),
            "perclos": perclos,
            "alerts": "|".join(fired),
        })

        if idx % 200 == 0:
            print(f"  ...{idx} frames")

    elapsed = time.perf_counter() - proc_start
    cap.release()
    landmarker.close()

    cols = ["frame", "t", "face", "calibrating", "ear", "mar", "yaw", "pitch",
            "cnn_prob", "ear_closed", "cnn_closed", "eyes_closed",
            "mouth_open", "head_off", "perclos", "alerts"]
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        wr.writerows(rows)

    detected = [r for r in rows if r.get("face") and not r.get("calibrating")]
    print()
    print("=" * 58)
    print(f"  frames processed   {idx}")
    pct = (faceless / idx * 100) if idx else 0.0
    print(f"  no face            {faceless}  ({pct:.1f}%)")
    print(f"  processing rate    {idx / elapsed:.1f} FPS "
          f"({elapsed:.1f}s wall)")
    if detected:
        closed = sum(r["eyes_closed"] for r in detected)
        print(f"  eyes closed        {closed}/{len(detected)} frames "
              f"({closed / len(detected) * 100:.1f}%)")
        probs = [r["cnn_prob"] for r in detected if r["cnn_prob"] != ""]
        if probs:
            print(f"  CNN mean p(closed) {sum(probs) / len(probs):.3f}")
    print("  alerts             " +
          ", ".join(f"{k}={v}" for k, v in alerts.items()))
    print(f"  csv                {csv_path}")
    print("=" * 58)
    return alerts


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="path to a recorded clip")
    ap.add_argument("--csv", default=None, help="output CSV (default <video>.csv)")
    ap.add_argument("--fusion", default=config.CNN_FUSION_MODE,
                    choices=["ear", "or", "and", "cnn"],
                    help="override CNN_FUSION_MODE for this run")
    ap.add_argument("--calib", type=float, default=config.CALIBRATION_SECONDS,
                    help="seconds of the clip to use for calibration")
    args = ap.parse_args()

    csv_path = args.csv or os.path.splitext(args.video)[0] + ".csv"
    run(args.video, csv_path, args.fusion, args.calib)


if __name__ == "__main__":
    main()
