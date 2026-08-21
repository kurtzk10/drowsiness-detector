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

## Phone Alert App (Android)

The detector pushes alerts to a companion Android app over the phone's own
hotspot. Put the PC on that hotspot — the app and the detector find each other
by UDP broadcast on port 9876, no IP configuration needed.

### Build the APK

Prerequisites, one time per machine:

| Need | Notes |
|---|---|
| **JDK 17** | AGP 8.2 cannot parse Java 21+ version strings and fails with a bare version number as the error. `winget install Microsoft.OpenJDK.17` |
| **Android SDK** | Platform 34 and build-tools 34.0.0: `sdkmanager "platforms;android-34" "build-tools;34.0.0"` |
| **`ANDROID_HOME`** | Point it at your SDK, e.g. `C:\Users\<you>\AppData\Local\Android\Sdk` |

Then, from `drowsiness_detector/android/DrowsinessAlertApp`:

```powershell
$env:JAVA_HOME = "C:\Program Files\Microsoft\jdk-17.0.20.8-hotspot"
.\gradlew assembleDebug
```

The APK lands at `app/build/outputs/apk/debug/app-debug.apk`.

`local.properties` is deliberately **not** in git — it hardcodes one machine's
SDK path. Gradle falls back to `ANDROID_HOME`, so you do not need to create it.

### Install it

```powershell
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

Or copy the APK to the phone and tap it, granting "install unknown apps" to
whichever app you tap from.

> **Debug APKs are signed with a per-user keystore** (`~/.android/debug.keystore`).
> An APK you built will not install *over* one a teammate built — Android
> rejects the signature change. Uninstall the old app first; this clears its
> data.

### Check discovery worked

With the app running and the PC on the phone's hotspot, startup should print:

```
[DISCOVERY] Phone detected at 10.x.x.x:5000, PC IP is 10.x.x.x
```

Both addresses must be on the hotspot subnet. If you instead see
`Ignoring announcement from ...`, a VPN or hypervisor adapter is broadcasting
on the same port and is being correctly rejected. If nothing appears within
10s, discovery warns and disables phone alerts — check the app is running and
that UDP 9876 is allowed through the firewall. Set `PHONE_IP` in `config.py`
to skip discovery entirely.

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
