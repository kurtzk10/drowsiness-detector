# ─────────────────────────────────────────
#  DROWSINESS DETECTOR — CONFIG
#  Change these values to tune the system
# ─────────────────────────────────────────

# --- Camera ---
# 0 = built-in webcam
# 1 = external USB webcam
# "http://192.168.x.x:81/stream" = ESP32-CAM or IP camera stream
CAMERA_SOURCE = 0

# --- EAR (Eye Aspect Ratio) ---
EAR_THRESHOLD = 0.25        # below this = eyes considered closed
EAR_ALERT_SECONDS = 2.0     # seconds eyes must stay closed to alert

# --- PERCLOS ---
# Percentage of frames where EAR < threshold over a rolling window
PERCLOS_WINDOW_SECONDS = 30  # rolling window duration in seconds
PERCLOS_THRESHOLD = 0.80     # 80% of frames closed = drowsy

# --- MAR (Mouth Aspect Ratio) ---
MAR_THRESHOLD = 0.60         # above this = mouth considered open (yawn)
MAR_ALERT_SECONDS = 3.0      # seconds mouth must stay open to alert

# --- Head Pose ---
HEAD_YAW_THRESHOLD = 30      # degrees left/right before alert
HEAD_PITCH_THRESHOLD = 20    # degrees up/down before alert
HEAD_ALERT_SECONDS = 1.5     # seconds off-road gaze before alert

# --- Alert Cooldown ---
ALERT_COOLDOWN_SECONDS = 4.0  # minimum gap between repeat alerts

# --- Calibration ---
CALIBRATION_SECONDS = 5.0     # duration of baseline sampling
# Dynamic threshold multipliers (applied to baseline average)
EAR_THRESHOLD_MULTIPLIER = 0.85      # baseline EAR * 0.85
MAR_THRESHOLD_MULTIPLIER = 1.20      # baseline MAR * 1.20
HEAD_YAW_THRESHOLD_OFFSET = 25       # baseline yaw + 25 deg
HEAD_PITCH_THRESHOLD_OFFSET = 15     # baseline pitch + 15 deg

# --- Recovery ---
# Seconds all metrics must remain normal before auto-clearing alert
RECOVERY_SECONDS = 3.0

# --- Display ---
SHOW_LANDMARKS = True         # draw eye/mouth landmark dots
SHOW_FPS = True               # show FPS counter on screen

# ── Hybrid CNN Eye Classifier ──────────────────
CNN_ENABLED = True
import os
CNN_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "eye_state.tflite"
)
CNN_CONFIDENCE_THRESHOLD = 0.75
