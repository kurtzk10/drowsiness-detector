# Real-Time Driver Drowsiness Detection System
# Holy Angel University — Computer Science Thesis

## Quick Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run on your webcam
```bash
python main.py
```

### 3. Change camera source (config.py)
```python
CAMERA_SOURCE = 0          # built-in webcam
CAMERA_SOURCE = 1          # external USB webcam
CAMERA_SOURCE = "http://192.168.4.1:81/stream"  # ESP32-CAM
CAMERA_SOURCE = "http://192.168.x.x:8080/video" # IP Webcam app
```

## What It Detects
- EAR < 0.25 for 2.0s       → DROWSY (eyes closed too long)
- PERCLOS > 80% in window   → DROWSY (sustained eye closure)
- MAR > 0.60 for 3.0s       → YAWNING
- Yaw > 30deg for 1.5s      → NOT LOOKING (head turned)
- Pitch > 20deg for 1.5s    → NOT LOOKING (head tilted)

## Tuning (config.py)
All thresholds are in config.py — adjust these if:
- Too many false alerts: raise EAR_THRESHOLD slightly (e.g. 0.22)
- Missing real drowsiness: lower EAR_THRESHOLD (e.g. 0.28)
- Blinks triggering alert: raise EAR_ALERT_SECONDS (e.g. 2.5)

## Files
```
drowsiness_detector/
├── main.py         ← run this
├── config.py       ← all tunable settings
├── metrics.py      ← EAR, MAR, head pose math
├── state.py        ← duration tracking + PERCLOS
├── alert.py        ← sound alarm
├── display.py      ← OpenCV UI drawing
└── requirements.txt
```

## Next Steps (after webcam works)
1. Switch CAMERA_SOURCE to your IR camera stream URL
2. Deploy to laptop (same code, same install command)
3. Add Flask HTTP server to send alerts to Android phone
4. Build Android app (Java) to receive alerts and play alarm
