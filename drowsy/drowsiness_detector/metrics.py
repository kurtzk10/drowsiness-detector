import numpy as np
import cv2

# ─────────────────────────────────────────
#  MediaPipe Face Mesh landmark indices
# ─────────────────────────────────────────

# Left eye (6 points)
LEFT_EYE  = [362, 385, 387, 263, 373, 380]
# Right eye (6 points)
RIGHT_EYE = [33,  160, 158, 133, 153, 144]

# Mouth — inner lip (8 points for MAR)
#   0: left corner (78)    1: right corner (308)
#   2: upper-left (82)     3: lower-left (87)
#   4: upper-center (13)   5: lower-center (14)
#   6: upper-right (312)   7: lower-right (317)
MOUTH = [78, 308, 82, 87, 13, 14, 312, 317]

# Head pose reference points (3D model)
HEAD_POSE_POINTS_3D = np.array([
    (0.0,    0.0,    0.0),    # Nose tip
    (0.0,   -330.0, -65.0),   # Chin
    (-225.0,  170.0,-135.0),  # Left eye corner
    (225.0,   170.0,-135.0),  # Right eye corner
    (-150.0, -150.0,-125.0),  # Left mouth corner
    (150.0,  -150.0,-125.0),  # Right mouth corner
], dtype=np.float64)

# Corresponding MediaPipe indices
HEAD_POSE_INDICES = [1, 152, 263, 33, 287, 57]


def _dist(a, b):
    return np.linalg.norm(a - b)


def get_landmarks_array(face_landmarks, indices, img_w, img_h):
    """Extract (x, y) pixel coords for given landmark indices."""
    pts = []
    for i in indices:
        lm = face_landmarks[i]
        pts.append(np.array([lm.x * img_w, lm.y * img_h]))
    return pts


def calculate_EAR(face_landmarks, img_w, img_h):
    """
    Eye Aspect Ratio — average of both eyes.
    EAR = (v1 + v2) / (2 * h)
    Returns float. Lower = more closed.
    """
    def eye_ear(indices):
        pts = get_landmarks_array(face_landmarks, indices, img_w, img_h)
        v1 = _dist(pts[1], pts[5])
        v2 = _dist(pts[2], pts[4])
        h  = _dist(pts[0], pts[3])
        if h == 0:
            return 0.0
        return (v1 + v2) / (2.0 * h)

    left  = eye_ear(LEFT_EYE)
    right = eye_ear(RIGHT_EYE)
    return round((left + right) / 2.0, 4)


def calculate_MAR(face_landmarks, img_w, img_h):
    """
    Mouth Aspect Ratio (inner lip).
    MAR = (v1 + v2 + v3) / (3 * h)
    Returns float. Higher = more open (yawning).
    """
    pts = get_landmarks_array(face_landmarks, MOUTH, img_w, img_h)
    # Vertical: upper-to-lower lip at left / center / right
    v1 = _dist(pts[2], pts[3])   # 82 ↔ 87   (left)
    v2 = _dist(pts[4], pts[5])   # 13 ↔ 14   (center)
    v3 = _dist(pts[6], pts[7])   # 312 ↔ 317 (right)
    # Horizontal: mouth width
    h  = _dist(pts[0], pts[1])   # 78 ↔ 308
    if h == 0:
        return 0.0
    return round((v1 + v2 + v3) / (3.0 * h), 4)


def calculate_head_pose(face_landmarks, img_w, img_h):
    """
    Head pose estimation using solvePnP.
    Returns (yaw, pitch) in degrees.
    Yaw  > 0 = looking right, < 0 = looking left
    Pitch > 0 = looking up,   < 0 = looking down
    """
    image_points = []
    for i in HEAD_POSE_INDICES:
        lm = face_landmarks[i]
        image_points.append([lm.x * img_w, lm.y * img_h])
    image_points = np.array(image_points, dtype=np.float64)

    focal_length = img_w
    center = (img_w / 2, img_h / 2)
    camera_matrix = np.array([
        [focal_length, 0,            center[0]],
        [0,            focal_length, center[1]],
        [0,            0,            1         ]
    ], dtype=np.float64)
    dist_coeffs = np.zeros((4, 1))

    success, rotation_vec, _ = cv2.solvePnP(
        HEAD_POSE_POINTS_3D,
        image_points,
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE
    )
    if not success:
        return 0.0, 0.0

    rotation_mat, _ = cv2.Rodrigues(rotation_vec)
    pose_mat = cv2.hconcat([rotation_mat, np.zeros((3, 1))])
    _, _, _, _, _, _, euler = cv2.decomposeProjectionMatrix(pose_mat)

    pitch = float(euler[0][0])
    yaw   = float(euler[1][0])
    return round(yaw, 2), round(pitch, 2)


def get_eye_points_for_drawing(face_landmarks, img_w, img_h):
    left  = get_landmarks_array(face_landmarks, LEFT_EYE,  img_w, img_h)
    right = get_landmarks_array(face_landmarks, RIGHT_EYE, img_w, img_h)
    return left, right


def get_mouth_points_for_drawing(face_landmarks, img_w, img_h):
    return get_landmarks_array(face_landmarks, MOUTH, img_w, img_h)


def _crop_eye(gray, pts, img_w, img_h, margin):
    """
    Cut one eye out of a grayscale frame using its landmark points.

    The box around the 6 eye landmarks is padded by `margin` (a fraction of
    the eye's own width) so the crop carries the lid and lash context the
    classifier was trained on, not just the aperture. Returns None when the
    eye falls outside the frame — the caller then skips CNN for this frame
    rather than feeding the model a degenerate patch.
    """
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)

    eye_w = x1 - x0
    if eye_w <= 1:
        return None

    # Pad relative to eye width on both axes, so the patch keeps a
    # consistent scale regardless of how far the driver sits from the lens.
    pad_x = eye_w * margin
    pad_y = eye_w * margin

    cx0 = int(round(x0 - pad_x))
    cx1 = int(round(x1 + pad_x))
    cy0 = int(round(y0 - pad_y))
    cy1 = int(round(y1 + pad_y))

    # Clamp to frame bounds
    cx0 = max(0, cx0)
    cy0 = max(0, cy0)
    cx1 = min(img_w, cx1)
    cy1 = min(img_h, cy1)

    if cx1 - cx0 < 2 or cy1 - cy0 < 2:
        return None

    crop = gray[cy0:cy1, cx0:cx1]
    if crop.size == 0:
        return None
    return crop


def get_eye_crops(face_landmarks, gray, img_w, img_h, margin=0.25):
    """
    Grayscale crops of both eyes, ready for the CNN eye-state classifier.

    Returns (left_crop, right_crop); either may be None if that eye is out
    of frame. `gray` must be single-channel — the classifier reshapes to
    (1, 1, 32, 64) and a 3-channel patch would fail that reshape.
    """
    left_pts  = get_landmarks_array(face_landmarks, LEFT_EYE,  img_w, img_h)
    right_pts = get_landmarks_array(face_landmarks, RIGHT_EYE, img_w, img_h)
    return (_crop_eye(gray, left_pts,  img_w, img_h, margin),
            _crop_eye(gray, right_pts, img_w, img_h, margin))
