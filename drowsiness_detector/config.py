import os

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
# Fraction of the window with eyes closed. 0.15 is the usual drowsiness
# criterion and sits well clear of normal blinking (~2% of the time).
# This was 0.80, which required eyes shut for 24 of every 30 seconds —
# far beyond the 2s eyes-closed alert, so PERCLOS never contributed.
# NOTE: 'PERCLOS-P80' in the literature refers to 80% eyelid CLOSURE,
# not 80% of frames; that is most likely where 0.80 came from.
# Validate this in a pilot run before the participant sessions.
PERCLOS_THRESHOLD = 0.15
# PERCLOS is already a rolling-window measure, so it needs no extra
# sustain time — 0.0 means fire as soon as it crosses. What it does need
# is the shared ALERT_COOLDOWN_SECONDS gate, which it gets by going
# through StateManager.check() like every other alert.
PERCLOS_ALERT_SECONDS = 0.0

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
# MAR is calibrated by ADDITION, not multiplication. The baseline is a
# CLOSED mouth (MAR ~0.05), so scaling it up never reaches a yawn (~0.70)
# — baseline * 1.20 lands at ~0.06 and any slight lip parting trips it.
# The delta asks how far the mouth must OPEN from rest instead. For a
# typical driver 0.05 + 0.55 = 0.60, matching MAR_THRESHOLD above.
MAR_OPEN_DELTA = 0.55       # baseline MAR + 0.55
MAR_THRESHOLD_MIN = 0.50    # floor; calibration can never go below this
MAR_THRESHOLD_MAX = 0.65    # ceiling. Calibrating with lips already
                            # parted pushes the bar up, and an unbounded
                            # bar would sail past a real yawn (~0.70).
                            # This is the one that actually bites.
HEAD_YAW_THRESHOLD_OFFSET = 25       # baseline yaw + 25 deg
HEAD_PITCH_THRESHOLD_OFFSET = 15     # baseline pitch + 15 deg

# --- Recovery ---
# Seconds all metrics must remain normal before auto-clearing alert
RECOVERY_SECONDS = 3.0

# --- Display ---
SHOW_LANDMARKS = True         # draw eye/mouth landmark dots
SHOW_FPS = True               # show FPS counter on screen

# ── Hybrid CNN Eye Classifier ──────────────────
# A small CNN classifies each eye crop as open/closed, complementing the
# geometric EAR. EAR is robust but scale- and angle-sensitive; the CNN reads
# appearance instead, so the two fail in different ways. If the model file is
# missing or fails to load the system falls back to EAR alone automatically.
CNN_ENABLED = True
CNN_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "eye_state.tflite"
)
CNN_CLOSED_THRESHOLD = 0.5   # closed-probability above this = eyes closed
CNN_EYE_MARGIN = 0.3         # must match dataset_prep.py's extraction margin
                             # (0.3) or inference sees crops the model was
                             # never trained on

# How the CNN verdict combines with the EAR verdict:
#   "ear"  - EAR only; CNN runs for display but never affects alerts
#   "or"   - either says closed -> closed  (highest recall, more false alarms)
#   "and"  - both must say closed         (fewest false alarms, lowest recall)
#   "cnn"  - CNN decides; EAR used only when a crop is unavailable
# "or" is the default: a missed drowsy driver is worse than a spurious alert,
# and the existing duration gate (EAR_ALERT_SECONDS) already absorbs
# single-frame noise before anything fires.
CNN_FUSION_MODE = "or"

# ── IR / night-vision simulation (prototype) ───
# Simulates a monochrome IR camera feed from a normal webcam so the pipeline
# can be validated ahead of a dark-setting IR deployment. Applied BEFORE
# detection, so MediaPipe runs on IR-style grayscale input. Toggle with 'i'.
IR_MODE = False               # start with IR simulation enabled?
IR_CONTRAST = 2.0             # CLAHE clip limit (0 = off) — ISP-style contrast
IR_GAMMA = 1.4                # >1 lifts midtones so skin looks pale/luminous
                              #   under near-IR (melanin is ~transparent to IR)
IR_VIGNETTE = 0.35            # 0..1 — IR-illuminator hotspot: bright center,
                              #   darker edges. Higher = stronger falloff.
IR_NOISE = 6.0                # std-dev of low-light sensor noise (0 = off).
