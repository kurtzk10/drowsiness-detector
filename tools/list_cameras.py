"""List every camera OpenCV can open, and save a preview frame from each.

Camera indices are not stable. On Windows they come from DirectShow's
enumeration order, so installing OBS — or any other virtual-camera software —
inserts a device and shifts the real webcam to a different number. That is why
CAMERA_SOURCE = 1 can be an external webcam on one laptop and the OBS Virtual
Camera on another.

There is no reliable way to ask OpenCV for a device *name*, so this looks at
the picture instead: it opens each index, grabs a frame, and writes it to
tools/camera_previews/. Open that folder, see which file shows your face, and
put that index in config.py.

    python tools/list_cameras.py

"""

import os
import sys

import cv2


MAX_INDEX = 8
WARMUP_FRAMES = 5          # first frames off a webcam are often black
PREVIEW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "camera_previews")


def backends():
    """Backends worth trying, most specific first.

    CAP_DSHOW is the one that enumerates by index reliably on Windows; CAP_MSMF
    is the default there and often opens a device it then cannot read from.
    CAP_ANY covers Linux and macOS.
    """
    if sys.platform == "win32":
        return [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF)]
    return [("ANY", cv2.CAP_ANY)]


def probe(index, backend):
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        return None
    frame = None
    for _ in range(WARMUP_FRAMES):
        ok, candidate = cap.read()
        if ok and candidate is not None:
            frame = candidate
    cap.release()
    return frame


def main():
    os.makedirs(PREVIEW_DIR, exist_ok=True)

    # Quieten OpenCV's per-index "backend can't be used" warnings; a device
    # that isn't there is the normal case here, not an error worth printing.
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        pass

    print(f"[CAMERAS] Probing indices 0-{MAX_INDEX - 1}...\n")
    found = []

    for name, backend in backends():
        for index in range(MAX_INDEX):
            frame = probe(index, backend)
            if frame is None:
                continue
            h, w = frame.shape[:2]
            path = os.path.join(PREVIEW_DIR, f"index{index}_{name}.png")
            cv2.imwrite(path, frame)
            found.append((index, name, f"{w}x{h}", path))
            print(f"  index {index}  [{name}]  {w}x{h}  -> {os.path.basename(path)}")

    if not found:
        print("  No camera opened at any index.")
        print("\n  Things to check:")
        print("   - another app (Teams, Zoom, Slack, OBS) is holding the camera")
        print("   - Windows camera privacy: Settings > Privacy > Camera")
        print("   - the webcam is disabled in Device Manager")
        return 1

    print(f"\n[CAMERAS] Previews written to {PREVIEW_DIR}")
    print("[CAMERAS] Open that folder and find the image showing your face.")
    print("[CAMERAS] The filename gives you BOTH values to set in")
    print("[CAMERAS] drowsiness_detector/config.py — an index on its own is")
    print("[CAMERAS] ambiguous, since the backends number devices separately:\n")

    for index, name, _res, _path in found:
        print(f"    index{index}_{name}.png  ->  CAMERA_SOURCE = {index}, "
              f'CAMERA_BACKEND = "{name.lower()}"')

    print("\n  A preview showing a logo, a black frame, or a 'camera off'")
    print("  icon is a virtual camera (OBS and similar) — not the one you want.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
