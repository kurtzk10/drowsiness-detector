# Real-Time Driver Drowsiness Detection System
# Holy Angel University — Computer Science Thesis

A laptop watches the driver through a webcam and, when it sees drowsiness,
fires an alert to an Android phone over a local hotspot — no internet.
Eye closure is judged by two independent signals: the geometric Eye Aspect
Ratio and a small CNN that reads the eye's appearance.

## Quick Setup

### 1. Install dependencies
```powershell
C:\Python311\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -r drowsiness_detector\requirements.txt
```

### 2. Run
```powershell
cd drowsiness_detector
..\.venv\Scripts\python.exe main.py
```

Expected on startup:
```
[CLASSIFIER] Loaded model from ...models\eye_state.tflite (259.4 KB)
[INFO] CNN fusion mode: or (closed if p > 0.5)
```

### 3. Keys
| Key | Action |
|---|---|
| `Q` | quit |
| `C` | calibrate (look straight ahead) |
| `I` | toggle IR / night-vision simulation |

### 4. Change camera source (config.py)
```python
CAMERA_SOURCE = 0          # built-in webcam
CAMERA_SOURCE = 1          # external USB webcam
CAMERA_SOURCE = "http://192.168.4.1:81/stream"  # ESP32-CAM
```

## What It Detects
- EAR below the calibrated cutoff for 2.0s → DROWSY (eyes closed too long)
- CNN eye-state classifier agrees/disagrees → fused per `CNN_FUSION_MODE`
- PERCLOS > 80% in window   → DROWSY (sustained eye closure)
- MAR > 0.60 for 3.0s       → YAWNING
- Yaw > 30deg for 1.5s      → NOT LOOKING (head turned)
- Pitch > 20deg for 1.5s    → NOT LOOKING (head tilted)

## EAR + CNN fusion
`CNN_FUSION_MODE` in `config.py` decides how the two eye signals combine:

| Mode | Behaviour | Use when |
|---|---|---|
| `ear` | EAR only; CNN shown but ignored | baseline for comparison |
| `or` | either says closed → closed | **default** — favours recall |
| `and` | both must agree | fewest false alarms |
| `cnn` | CNN decides, EAR as fallback | measuring the CNN alone |

If the model is missing, fails to load, or both eye crops leave the frame,
every mode falls back to EAR — the system never ends up with no verdict.

## Tuning (config.py)
- Too many false alerts: raise `EAR_THRESHOLD` slightly (e.g. 0.22)
- Missing real drowsiness: lower `EAR_THRESHOLD` (e.g. 0.28)
- Blinks triggering alert: raise `EAR_ALERT_SECONDS` (e.g. 2.5)
- `CNN_EYE_MARGIN` **must stay 0.3** — it has to match the crop margin in
  `training/dataset_prep.py`, or inference feeds the model patches unlike
  anything it was trained on.

## Layout
```
drowsiness_detector/
├── main.py          ← run this
├── config.py        ← all tunable settings
├── metrics.py       ← EAR, MAR, head pose, eye crops
├── state.py         ← duration tracking + PERCLOS
├── calibration.py   ← per-driver threshold capture
├── alert.py         ← dispatches alerts to the phone
├── http_alerts.py   ← HTTP client (laptop → phone)
├── discovery.py     ← UDP broadcast phone discovery
├── streamer.py      ← MJPEG feed on port 8080
├── filters.py       ← IR / night-vision simulation
└── display.py       ← OpenCV UI drawing

inference/
└── eye_classifier.py   ← TFLite eye-state CNN wrapper

models/
├── eye_state.tflite    ← trained model (259 KB)
├── best_eye_cnn.pth    ← PyTorch checkpoint
└── old/                ← superseded model, kept for comparison

training/               ← not needed to run; kept for the paper
├── dataset_prep.py     ← extracts eye crops from YawDD + NTHU-DD
├── eye_cnn.py          ← model architecture
├── train_colab.ipynb   ← training notebook
├── convert_to_tflite.py
└── spot_check.py       ← label-accuracy audit
```

## Model
| Item | Value |
|---|---|
| Input | `[1, 1, 32, 64]` float32, NCHW, grayscale |
| Output | `[1, 2]` logits — class 0 = OPEN, class 1 = CLOSED |
| Preprocessing | `/255`, then `(x - 0.5) / 0.5` → `[-1, 1]` |
| Accuracy | 87.3% (video-based split) |
| Cost | ~0.3 ms per frame for both eyes |
