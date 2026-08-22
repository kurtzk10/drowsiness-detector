import os

# ─────────────────────────────────────────
#  DROWSINESS DETECTOR — CONFIG
#  Change these values to tune the system
# ─────────────────────────────────────────

# --- Camera ---
# An index is only meaningful together with a backend: DirectShow and Media
# Foundation enumerate devices separately, so index 0 can be the built-in
# webcam on one and an external USB camera on the other, on the same laptop.
# Installing OBS shifts the numbering again.
#
# Run `python tools/list_cameras.py` — it writes a preview frame per
# index/backend, so you can pick the pair by sight.
#
# "http://192.168.x.x:81/stream" = ESP32-CAM or IP camera stream (backend
# is ignored for URL sources; those always go through FFMPEG).
CAMERA_SOURCE = 0

# "auto"  = DirectShow first on Windows, then whatever OpenCV picks
# "dshow" = force DirectShow      (Windows only)
# "msmf"  = force Media Foundation (Windows only)
# "any"   = let OpenCV choose
#
# Anything other than "auto" is honoured exactly: if the named backend cannot
# produce a frame the detector stops rather than quietly opening a different
# camera, since falling back is how you end up recording the wrong lens.
CAMERA_BACKEND = "auto"

# --- Phone alerts ---
# Static fallback used when UDP auto-discovery finds no phone within
# DISCOVERY_TIMEOUT (10s) — e.g. the hotspot blocks broadcast packets or a
# firewall drops them. The phone on an Android hotspot is usually 192.168.x.x.
# Leave as None to rely on discovery alone.
PHONE_IP = None
PHONE_PORT = 5000

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
# Measured on real footage: PERCLOS moves slowly, so requiring it to stay
# high for a few seconds costs no detection latency and rejects brief
# excursions caused by a burst of blinks.
PERCLOS_ALERT_SECONDS = 5.0

# A rolling ratio is meaningless until the window actually holds data.
# On the first live session PERCLOS fired at t=0.5s with ONE frame in the
# window (1 closed / 1 total = 1.0), and kept firing while the window
# filled: 5 seconds of history containing two blinks reads as 20% closed.
# 17 of 17 spurious alerts in that session were this artifact. Until the
# history spans this many seconds, PERCLOS reports 0.
PERCLOS_MIN_WINDOW_SECONDS = 30

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
# Was 0.85, which put the cutoff inside normal EAR fluctuation: in the calm
# stretches of the second live session EAR called 17-31% of frames closed
# while the CNN said 2-7%, and that noise fed straight into PERCLOS. At
# 0.75 the two agree 91% of the time (was 80%) and partial eyelid droop —
# which is real drowsiness evidence — still registers.
EAR_THRESHOLD_MULTIPLIER = 0.75      # baseline EAR * 0.75
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
RECOVERY_SECONDS = 8.0

# --- Session logging ---
# Writes logs/session_<stamp>.csv (one row per frame) and a .txt
# summary on exit. This is the raw material for the participant
# TP/FP/TN/FN analysis — without it every alert has to be
# transcribed by hand from the console during the drive.
SESSION_LOG = True
SESSION_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")

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
# Raised from 0.5 after the first live session. The model separates open
# from closed very well on real footage (AUC 0.971 against the calibrated
# EAR), but its probabilities are shifted high: at 0.5 it called 29.9% of
# frames closed where EAR said 9.4%, a 23% false-positive rate. At 0.9 the
# false-positive rate is 1.2% and the closed-rate matches EAR's.
# Re-check this if the camera, lighting or model changes.
CNN_CLOSED_THRESHOLD = 0.9
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

# PERCLOS is scored from a STRICTER verdict than the instantaneous alert.
# The two have different error costs: one stray closed frame barely moves a
# 2s-sustained alert, but it directly inflates a 60s rolling average. Using
# 'and' here means PERCLOS only counts frames where both signals agree, so
# detection stays sensitive while the long-window metric stays precise.
# Set to None to reuse CNN_FUSION_MODE.
PERCLOS_FUSION_MODE = "and"

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
