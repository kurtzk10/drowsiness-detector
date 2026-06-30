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
PERCLOS_WINDOW_SECONDS = 60  # rolling window duration in seconds
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

# --- Display ---
SHOW_LANDMARKS = True         # draw eye/mouth landmark dots
SHOW_FPS = True               # show FPS counter on screen
