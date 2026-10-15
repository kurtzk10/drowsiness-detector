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
[INFO] CNN fusion mode: or (closed if p > 0.9)
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

**Wrong camera opens?** An index on its own does not identify a camera.
Windows has two capture backends — DirectShow and Media Foundation — and they
enumerate devices independently, so on one laptop here index 0 is the built-in
webcam under DSHOW and an **external USB camera** under MSMF. Installing OBS
shifts the numbering again.

So the backend is part of the address:

```python
CAMERA_SOURCE  = 0
CAMERA_BACKEND = "msmf"     # "auto" | "dshow" | "msmf" | "any"
```

`"auto"` tries DirectShow first on Windows. Anything else is honoured exactly
— if that backend cannot produce a frame the detector stops, rather than
quietly opening a different camera and looking like it worked.

Run the picker and look at the previews it writes:

```powershell
python tools\list_cameras.py
```

It grabs a frame from every index on every backend into
`tools/camera_previews/`, then prints the `CAMERA_SOURCE` / `CAMERA_BACKEND`
pair for each. Whichever image shows your face is the pair to use. A preview
showing a logo, a black frame, or a "camera off" icon is a virtual camera.

## Docker

The detector also ships as a container. One image, three modes:

| Mode | Runs on | Camera | Window | Phone alerts |
|---|---|---|---|---|
| `validate` | Windows, macOS, Linux | a recorded clip | no | no |
| `headless` | Windows, macOS, Linux | laptop webcam via the bridge | no | yes, auto-discovered by the bridge |
| `live` | Linux / Raspberry Pi | USB webcam | yes | yes, auto-discovered |

Build once:

```powershell
docker compose --profile validate build validate
```

**validate** — replay a clip through the real detection modules. Put the clip
in `videos/`; the per-frame CSV is written next to it.

```powershell
docker compose --profile validate run --rm validate /videos/clip.mp4 --fusion or
```

**headless** — live detection with no window. Docker Desktop on Windows and
macOS cannot pass a webcam into a container, and the phone's UDP discovery
broadcast never reaches one. `tools/webcam_bridge.py` runs on the laptop and
covers both: it streams the webcam to the container, and answers the phone's
broadcast exactly as the native detector does. It needs only OpenCV:

```powershell
python -m pip install opencv-python
python tools\webcam_bridge.py              # leave running; --source 1 for another camera
```

Then, in a second terminal:

```powershell
docker compose --profile headless up
```

With the laptop on the phone's hotspot and the alert app open, the bridge
prints `[DISCOVERY] Phone detected at ...` and the container picks the phone
up within a couple of seconds — no IP to type. The phone learns the laptop's
address, so its video feed and calibrate screen work as they do natively.
The first run may raise a Windows Firewall prompt for Python (UDP 9876) and
for Docker (TCP 8080): allow both on private networks.

Calibration also starts on its own the first time a face is seen, since there
is no keyboard. `http://localhost:8080/video_feed` shows the camera feed in a
browser.

Overrides, all optional: `CAMERA_SOURCE` (a phone IP-camera app's
`http://<phone-ip>:8080/video`, or `/videos/clip.mp4`), and `PHONE_IP` to
name the phone by hand if discovery is blocked.

**live** — the full system as it runs natively, on a Linux host with a
display:

```bash
xhost +local:docker
docker compose --profile live up
```

Host networking lets the phone discover the detector over the hotspot as
usual, and the webcam at `/dev/video0` is passed through (`CAMERA_DEVICE` to
use another). Session logs from every mode land in `logs/`.

Settings that differ per machine come from environment variables instead of
`config.py`: `CAMERA_SOURCE`, `CAMERA_BACKEND`, `PHONE_IP`, `PHONE_PORT`,
`PHONE_DISCOVERY_URL`, `SESSION_LOG_DIR` and `HEADLESS`.

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
| Alert | Fires when | Held for |
|---|---|---|
| DROWSY | eyes closed (EAR and CNN fused per `CNN_FUSION_MODE`) | 2.0s |
| DROWSY (PERCLOS) | eyes closed in ≥ 15% of the last 60s | 5.0s |
| YAWNING | MAR above the yawn threshold | 3.0s |
| NOT LOOKING | head yaw or pitch past the limit | 1.5s |

The same alert cannot repeat within 4s. Once every signal has been normal for
8s (and PERCLOS is back under 15%), the phone alarm clears on its own.

PERCLOS reports 0 until it has 30s of history, so it cannot fire at startup,
and it only counts frames where EAR **and** the CNN both say closed
(`PERCLOS_FUSION_MODE = "and"`), so single-frame noise does not pile up over
the 60s window.

### Thresholds and calibration
Press `C` (or tap calibrate in the phone app) and look straight ahead for 5s.
The detector takes the median of each metric and sets per-driver thresholds:

| Signal | Before calibration (`config.py`) | After calibration |
|---|---|---|
| EAR (eyes closed) | below 0.25 | below baseline × 0.75 |
| CNN (eyes closed) | probability above 0.9 | unchanged |
| MAR (yawn) | above 0.60 | above baseline + 0.55, kept within 0.50–0.65 |
| Head yaw | beyond ±30° | beyond baseline ±25° |
| Head pitch | beyond ±20° | beyond baseline ±15° |

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
After calibration the EAR cutoff comes from `EAR_THRESHOLD_MULTIPLIER`, not
`EAR_THRESHOLD`, so that is the one to adjust:
- Too many false alerts: **lower** `EAR_THRESHOLD_MULTIPLIER` (e.g. 0.70) —
  eyes must close further before they count as closed
- Missing real drowsiness: **raise** it (e.g. 0.80)
- Blinks triggering alert: raise `EAR_ALERT_SECONDS` (e.g. 2.5)
- CNN calling open eyes closed: raise `CNN_CLOSED_THRESHOLD`; at 0.5 it gave a
  23% false-positive rate on live footage, at 0.9 about 1%
- `EAR_THRESHOLD` (0.25) only applies until the driver calibrates.
- `CNN_EYE_MARGIN` **must stay 0.3** — it has to match the crop margin in
  `training/dataset_prep.py`, or inference feeds the model patches unlike
  anything it was trained on.

To compare settings without a live drive, replay a recording through the real
detection modules:

```powershell
python tools\validate_video.py clip.mp4 --fusion and
```

## Session logs
Every run writes `logs/session_<date>_<time>.csv` (one row per frame) and a
matching `.txt` summary at the repository root. `logs/` is gitignored — it is
participant research data, so archive it separately.

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
├── session_log.py   ← per-frame CSV + session summary
├── filters.py       ← IR / night-vision simulation
├── display.py       ← OpenCV UI drawing
└── android/DrowsinessAlertApp/   ← phone alert app (Java)

inference/
└── eye_classifier.py   ← TFLite eye-state CNN wrapper

models/
├── eye_state.tflite    ← trained model (259 KB)
└── best_eye_cnn.pth    ← PyTorch checkpoint

tools/
├── list_cameras.py     ← preview every camera index/backend
└── validate_video.py   ← replay a recording offline, compare fusion modes

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
| Accuracy | 90.45% (video-based split, no subject in both train and validation) |
| Precision / specificity | 86.21% / 94.46% |
| Cost | ~0.3 ms per frame for both eyes |
