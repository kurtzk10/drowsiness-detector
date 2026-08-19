import argparse
import random
from collections import defaultdict
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions, RunningMode

LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
EAR_THRESHOLD = 0.25


def _compute_ear(landmarks, indices, img_w, img_h):
    pts = []
    for idx in indices:
        lm = landmarks[idx]
        pts.append(np.array([lm.x * img_w, lm.y * img_h]))
    v1 = np.linalg.norm(pts[1] - pts[5])
    v2 = np.linalg.norm(pts[2] - pts[4])
    h = np.linalg.norm(pts[0] - pts[3])
    if h == 0:
        return 0.0
    return (v1 + v2) / (2.0 * h)


def _extract_eye_crop(gray, landmarks, indices, img_w, img_h, margin=0.3):
    pts = []
    for idx in indices:
        lm = landmarks[idx]
        pts.append(np.array([lm.x * img_w, lm.y * img_h]))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    w = x2 - x1
    h = y2 - y1
    x1 = max(0, int(x1 - w * margin))
    y1 = max(0, int(y1 - h * margin))
    x2 = min(img_w, int(x2 + w * margin))
    y2 = min(img_h, int(y2 + h * margin))
    if x2 <= x1 or y2 <= y1:
        return None
    crop = gray[y1:y2, x1:x2]
    resized = cv2.resize(crop, (64, 32))
    return resized


def _find_video(stem, video_root):
    candidates = [video_root / (stem + ".avi"),
                  video_root / (stem + ".avi.avi"),
                  video_root / (stem + ".mp4")]
    for c in candidates:
        if c.exists():
            return c
    for c in sorted(video_root.rglob(stem + ".avi*")):
        if c.is_file():
            return c
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Spot-check extracted eye crops against the source video "
                    "frames they claim to come from."
    )
    parser.add_argument("--extracted-dir", default="data/extracted",
                        help="Folder with open/ and closed/ subfolders")
    parser.add_argument("--video-root", default="data/raw/yawdd",
                        help="Root folder to search for source videos")
    parser.add_argument("--n-closed", type=int, default=50,
                        help="Closed crops to sample (default: 50)")
    parser.add_argument("--n-open", type=int, default=50,
                        help="Open crops to sample (default: 50)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--frame-step", type=int, default=3,
                        help="Sampling step used when crops were extracted "
                             "(default: 3)")
    args = parser.parse_args()

    extracted = Path(args.extracted_dir)
    video_root = Path(args.video_root)
    rng = random.Random(args.seed)

    open_dir = extracted / "open"
    closed_dir = extracted / "closed"

    open_files = sorted(open_dir.glob("*.png")) if open_dir.exists() else []
    closed_files = sorted(closed_dir.glob("*.png")) if closed_dir.exists() else []

    closed_sample = rng.sample(closed_files, min(args.n_closed, len(closed_files)))
    open_sample = rng.sample(open_files, min(args.n_open, len(open_files)))

    print(f"[SPOT] sampling {len(closed_sample)} closed + "
          f"{len(open_sample)} open crops (seed={args.seed})")

    by_video = defaultdict(list)
    for p in closed_sample + open_sample:
        stem, fidx, side = p.stem.rsplit("_", 2)
        by_video[stem].append((int(fidx), side, p.parent.name == "closed", p))

    task_path = str(Path(__file__).resolve().parent.parent /
                    "drowsiness_detector" / "face_landmarker.task")
    opts = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=task_path),
        running_mode=RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.6,
        min_face_presence_confidence=0.6,
        min_tracking_confidence=0.6,
        output_face_blendshapes=False,
    )
    face_landmarker = FaceLandmarker.create_from_options(opts)

    results = []
    ts_carry_ms = 0
    last_ts_ms = -1
    for stem in sorted(by_video):
        video_path = _find_video(stem, video_root)
        if video_path is None:
            print(f"[SPOT]  WARN: no video found for stem '{stem}', skipping")
            continue
        cap = cv2.VideoCapture(str(video_path))
        total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0
        ts_base_ms = ts_carry_ms

        wanted = sorted(by_video[stem], key=lambda t: t[0])
        max_idx = wanted[-1][0]
        frame_idx = 0
        while frame_idx <= max_idx:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % args.frame_step == 0:
                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                ts = ts_base_ms + int(round(frame_idx / fps * 1000))
                if ts <= last_ts_ms:
                    ts = last_ts_ms + 1
                last_ts_ms = ts
                res = face_landmarker.detect_for_video(mp_image, ts)
                if res and res.face_landmarks:
                    flm = res.face_landmarks[0]
                    ear = (_compute_ear(flm, LEFT_EYE, w, h) +
                           _compute_ear(flm, RIGHT_EYE, w, h)) / 2.0
                    true_closed = ear < EAR_THRESHOLD
                else:
                    true_closed = None

                for fidx, side, is_closed_crop, p in [t for t in wanted
                                                      if t[0] == frame_idx]:
                    true_state = "closed" if true_closed else \
                        ("open" if true_closed is not None else "no_face")
                    claimed = "closed" if is_closed_crop else "open"
                    match = true_closed is not None and (true_closed == is_closed_crop)
                    results.append({
                        "file": p.name,
                        "video": stem,
                        "frame": fidx,
                        "side": side,
                        "claimed": claimed,
                        "true": true_state,
                        "match": match,
                        "ear": round(ear, 3) if true_closed is not None else None,
                        "crop_path": str(p),
                    })
            frame_idx += 1
        cap.release()
        ts_carry_ms += int(total_video_frames / fps * 1000)

    face_landmarker.close()

    bad_closed = [r for r in results if r["claimed"] == "closed" and not r["match"]]
    bad_open = [r for r in results if r["claimed"] == "open" and not r["match"]]
    no_face = [r for r in results if r["true"] == "no_face"]
    total_closed = sum(1 for r in results if r["claimed"] == "closed")
    total_open = sum(1 for r in results if r["claimed"] == "open")

    print(f"\n[SPOT] {'='*50}")
    print(f"[SPOT]  Closed crops checked: {total_closed}  "
          f"Open crops checked: {total_open}")
    print(f"[SPOT]  Bad CLOSED labels:    {len(bad_closed)}/{total_closed} "
          f"({len(bad_closed)/max(total_closed,1):.1%})")
    print(f"[SPOT]  Bad OPEN labels:      {len(bad_open)}/{total_open} "
          f"({len(bad_open)/max(total_open,1):.1%})")
    print(f"[SPOT]  No-face frames:       {len(no_face)}")
    print(f"[SPOT]  Overall label match:  "
          f"{sum(1 for r in results if r['match'])}/{len(results)} "
          f"({sum(1 for r in results if r['match'])/max(len(results),1):.1%})")
    print(f"[SPOT] {'='*50}")

    if bad_closed:
        print("\n[SPOT] Bad CLOSED crops (claimed closed, frame truly open):")
        for r in sorted(bad_closed, key=lambda r: (r["video"], r["frame"])):
            print(f"  {r['file']}  ear={r['ear']}")


if __name__ == "__main__":
    main()
