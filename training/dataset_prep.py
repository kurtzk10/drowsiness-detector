import argparse
import cv2
import mediapipe as mp
import numpy as np
import os
import zipfile
from pathlib import Path
from tqdm import tqdm


LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
EAR_THRESHOLD = 0.25
CROP_WIDTH = 64
CROP_HEIGHT = 32


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
    resized = cv2.resize(crop, (CROP_WIDTH, CROP_HEIGHT))
    return resized


def _load_label_file(label_path):
    labels = {}
    if not label_path.exists():
        return labels
    with open(label_path, "r") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                parts = line.split()
                if len(parts) >= 2:
                    frame_idx = int(parts[0])
                    value = int(parts[1])
                    labels[frame_idx] = value
                else:
                    labels[i] = int(line)
            except ValueError:
                continue
    return labels


def _scan_videos(input_dir):
    exts = {".mp4", ".avi", ".mov", ".mkv"}
    videos = []
    for p in Path(input_dir).rglob("*"):
        if p.suffix.lower() in exts:
            videos.append(p)
    return sorted(videos)


def _find_label_boundaries(label_lookup, num_frames, margin=2):
    sequence = [label_lookup.get(f) for f in range(num_frames)]
    boundary_frames = set()
    transition_count = 0
    prev_label = None
    for f in range(num_frames):
        label = sequence[f]
        if label is None:
            continue
        if prev_label is not None and label != prev_label:
            transition_count += 1
            for g in range(max(0, f - margin),
                           min(num_frames, f + margin + 1)):
                boundary_frames.add(g)
        prev_label = label
    return boundary_frames, transition_count


def main():
    parser = argparse.ArgumentParser(
        description="Dataset preparation for eye state CNN training"
    )
    parser.add_argument("--input-dir", required=True,
                        help="Root folder containing video files")
    parser.add_argument("--output-dir", default="data/extracted",
                        help="Output directory for extracted crops")
    parser.add_argument("--frame-step", type=int, default=3,
                        help="Sample every Nth frame (default: 3)")
    parser.add_argument("--drop-boundary-frames", action="store_true",
                        help="Skip frames within --boundary-margin of an "
                             "open<->closed label transition")
    parser.add_argument("--boundary-margin", type=int, default=2,
                        help="Frames around a label transition treated as "
                             "ambiguous (default: 2)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    frame_step = args.frame_step
    drop_boundary = args.drop_boundary_frames
    boundary_margin = args.boundary_margin

    open_dir = output_dir / "open"
    closed_dir = output_dir / "closed"
    open_dir.mkdir(parents=True, exist_ok=True)
    closed_dir.mkdir(parents=True, exist_ok=True)

    videos = _scan_videos(input_dir)
    print(f"[PREP] Found {len(videos)} video files in {input_dir}")

    ts_carry_ms = 0
    last_ts_ms = -1

    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions, RunningMode

    task_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "drowsiness_detector", "face_landmarker.task"
    )
    face_mesh_options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=task_path),
        running_mode=RunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.6,
        min_face_presence_confidence=0.6,
        min_tracking_confidence=0.6,
        output_face_blendshapes=False,
    )
    face_landmarker = FaceLandmarker.create_from_options(face_mesh_options)

    total_frames = 0
    skipped_no_face = 0
    skipped_no_label = 0
    skipped_boundary = 0
    boundary_transitions = 0
    open_count = 0
    closed_count = 0
    labeled_by_file = 0
    labeled_by_ear = 0

    for video_path in videos:
        label_path = video_path.with_suffix(".txt")
        has_label_file = label_path.exists()

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            print(f"[PREP]  Could not open {video_path}, skipping")
            continue

        total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0

        label_lookup = {}
        boundary_frames = set()
        if has_label_file:
            label_lookup = _load_label_file(label_path)
            if label_lookup:
                n_lines = len(label_lookup)
                idx_min = min(label_lookup)
                idx_max = max(label_lookup)
                if n_lines > total_video_frames:
                    print(f"[PREP]  WARN {video_path.name}: label file has "
                          f"{n_lines} lines for {total_video_frames} frames "
                          f"(check 1-indexed / trailing lines)")
                print(f"[PREP]  {video_path.name}: label indices "
                      f"[{idx_min}..{idx_max}] for {total_video_frames} frames "
                      f"({n_lines} labels)")
                boundary_frames, n_transitions = _find_label_boundaries(
                    label_lookup, total_video_frames, margin=boundary_margin)
                boundary_transitions += n_transitions
                if n_transitions:
                    print(f"[PREP]  {video_path.name}: {n_transitions} "
                          f"open<->closed transitions, "
                          f"{len(boundary_frames)} frames within +/-"
                          f"{boundary_margin} flagged as ambiguous")

        video_duration_ms = int(total_video_frames / fps * 1000)
        ts_base_ms = ts_carry_ms

        desc = f"[PREP]  {video_path.name}"
        frame_idx = 0
        with tqdm(total=total_video_frames, desc=desc, leave=False) as pbar:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if frame_idx % frame_step == 0:
                    total_frames += 1
                    h, w = frame.shape[:2]
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                                        data=rgb)
                    timestamp_ms = ts_base_ms + int(
                        round(frame_idx / fps * 1000))
                    if timestamp_ms <= last_ts_ms:
                        timestamp_ms = last_ts_ms + 1
                    last_ts_ms = timestamp_ms
                    result = face_landmarker.detect_for_video(
                        mp_image, timestamp_ms)

                    if not result or not result.face_landmarks:
                        skipped_no_face += 1
                        pbar.update(1)
                        frame_idx += 1
                        continue

                    face_lm = result.face_landmarks[0]

                    if has_label_file:
                        if frame_idx not in label_lookup:
                            skipped_no_label += 1
                            pbar.update(1)
                            frame_idx += 1
                            continue
                        if drop_boundary and frame_idx in boundary_frames:
                            skipped_boundary += 1
                            pbar.update(1)
                            frame_idx += 1
                            continue
                        label = label_lookup[frame_idx]
                        labeled_by_file += 1
                    else:
                        ear = _compute_ear(face_lm, LEFT_EYE, w, h)
                        ear_r = _compute_ear(face_lm, RIGHT_EYE, w, h)
                        ear = (ear + ear_r) / 2.0
                        label = 1 if ear < EAR_THRESHOLD else 0
                        labeled_by_ear += 1

                    stem = video_path.stem
                    for side_idx, indices in enumerate([LEFT_EYE, RIGHT_EYE]):
                        side = "L" if side_idx == 0 else "R"
                        crop = _extract_eye_crop(gray, face_lm,
                                                 indices, w, h, margin=0.3)
                        if crop is None:
                            continue
                        filename = f"{stem}_{frame_idx:06d}_{side}.png"
                        if label == 1:
                            cv2.imwrite(str(closed_dir / filename), crop)
                            closed_count += 1
                        else:
                            cv2.imwrite(str(open_dir / filename), crop)
                            open_count += 1
                pbar.update(1)
                frame_idx += 1

        cap.release()
        ts_carry_ms += video_duration_ms

    face_landmarker.close()

    print(f"\n[PREP] {'='*40}")
    print(f"[PREP]  Total frames processed:     {total_frames}")
    print(f"[PREP]  Skipped (no face detected): {skipped_no_face}")
    print(f"[PREP]  Skipped (missing label):    {skipped_no_label}")
    if drop_boundary:
        print(f"[PREP]  Skipped (boundary frames):  {skipped_boundary}")
    print(f"[PREP]  Label transitions found:    {boundary_transitions}")
    print(f"[PREP]  Open crops saved:           {open_count}")
    print(f"[PREP]  Closed crops saved:         {closed_count}")
    print(f"[PREP]  Labeled by file:            {labeled_by_file}")
    print(f"[PREP]  Labeled by EAR:             {labeled_by_ear}")
    print(f"[PREP] {'='*40}")

    zip_path = output_dir.parent / "dataset.zip"
    print(f"[PREP] Zipping {output_dir} to {zip_path} ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for class_dir in ["open", "closed"]:
            dir_path = output_dir / class_dir
            for img_path in dir_path.iterdir():
                if img_path.suffix.lower() == ".png":
                    arcname = str(img_path.relative_to(output_dir.parent))
                    zf.write(img_path, arcname)
    print(f"[PREP] Done. Zip size: "
          f"{zip_path.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
