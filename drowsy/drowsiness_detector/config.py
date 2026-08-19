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

# Personalize the closed-eye cutoff to the driver during calibration.
# Eye size varies per person — a fixed EAR_THRESHOLD misfires for people
# with naturally small (or large) eyes. When EAR_CALIBRATION is on, the
# "eyes closed" cutoff becomes EAR_CLOSED_RATIO x the driver's own
# open-eye EAR (captured during calibration). This also feeds PERCLOS,
# which counts frames below that same cutoff. EAR_THRESHOLD above is the
# fallback used when calibration is off.
EAR_CALIBRATION = True
EAR_CLOSED_RATIO = 0.6

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

# --- Calibration ---
# On startup the system watches the driver's neutral head position for
# this many seconds and treats THAT pose as "looking at the road" (the
# zero point). Head-pose alerts then trigger on deviation FROM this
# baseline, not from an absolute zero — so an off-center camera or a
# natural sitting angle won't cause false "not looking" alerts.
# Press 'c' at any time to recalibrate.
CALIBRATION_SECONDS = 3.0

# --- Alert Cooldown ---
ALERT_COOLDOWN_SECONDS = 4.0  # minimum gap between repeat alerts

# --- Display ---
SHOW_LANDMARKS = True         # draw eye/mouth landmark dots
SHOW_FPS = True               # show FPS counter on screen

# --- IR / night-vision simulation (prototype) ---
# Simulates a monochrome IR camera feed from a normal webcam so the
# pipeline can be validated ahead of a dark-setting IR deployment. The
# filter is applied to the frame BEFORE detection, so MediaPipe actually
# runs on IR-style grayscale input. Toggle live with the 'i' key.
IR_MODE = False               # start with IR simulation enabled?
IR_CONTRAST = 2.0             # CLAHE clip limit (0 = off) — ISP-style contrast
IR_GAMMA = 1.4                # >1 lifts midtones so skin looks pale/luminous
                              #   under near-IR (melanin is ~transparent to IR)
IR_VIGNETTE = 0.35            # 0..1 — IR-illuminator hotspot: bright center,
                              #   darker edges. Higher = stronger falloff.
IR_NOISE = 6.0                # std-dev of low-light sensor noise (0 = off).
                              #   The realistic stress on the detector.

# --- CNN eye-state classifier (hybrid detection) ---
# A small CNN classifies each eye crop as open/closed, complementing the
# geometric EAR. EAR is robust but scale- and angle-sensitive; the CNN reads
# appearance instead, so the two fail in different ways. If the model file is
# missing or fails to load the system falls back to EAR alone automatically.
CNN_ENABLED = True
CNN_MODEL_PATH = "models/eye_state.tflite"   # relative to this file
CNN_CLOSED_THRESHOLD = 0.5   # closed-probability above this = eyes closed
CNN_EYE_MARGIN = 0.3         # must match dataset_prep.py's extraction
                             # margin (0.3) or inference sees crops the
                             # model was never trained on

# How the CNN verdict combines with the EAR verdict:
#   "ear"  - EAR only; CNN runs for display but never affects alerts
#   "or"   - either says closed -> closed  (highest recall, more false alarms)
#   "and"  - both must say closed         (fewest false alarms, lowest recall)
#   "cnn"  - CNN decides; EAR used only when a crop is unavailable
# "or" is the default: a missed drowsy driver is worse than a spurious alert,
# and the existing duration gate (EAR_ALERT_SECONDS) already absorbs
# single-frame noise before anything fires.
CNN_FUSION_MODE = "or"
