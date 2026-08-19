# Change Log — 19 August 2026

Everything below is on branch `build1.0`, **committed locally and not yet
pushed**. Ten commits, from `440fabb` to `7d669d6`.

> **Before you pull:** `drowsy/` has been deleted. If you have uncommitted
> work in there, say so first.

---

## Summary

| # | Change | Commit |
|---|---|---|
| 1 | Ported the retrained model into the build branch | `cd7b3ef` |
| 2 | Wired the CNN into the detection loop | `1131f9e` |
| 3 | Matched eye-crop geometry to the training code | `14effc9` |
| 4 | Merged the `newtrain` training pipeline | `a5acfb9` |
| 5 | Consolidated two apps into one | `c0abba6` |
| 6 | Rewrote README and team_status | `b6825a4` |
| 7 | Fixed the MAR yawn threshold | `6c2b87d` |
| 8 | Recorded four confirmed alert-path bugs | `7127660` |
| 9 | Fixed PERCLOS alert spam | `bc0dc27` |
| 10 | Fixed alarm auto-clear | `7d669d6` |

Also: Python 3.11.9 installed at `C:\Python311\python.exe` with a project
`.venv` — this is environment setup, not a commit.

---

## 1. The repo had two different applications

This was the biggest finding, and it changed everything after it.

`newtrain` carried **two** detectors that had drifted apart:

| | `drowsy/drowsiness_detector/` | `drowsiness_detector/` |
|---|---|---|
| Alerts | pygame beeps, local audio | HTTP POST → phone |
| Phone discovery (UDP) | ✗ | ✓ |
| MJPEG streamer | ✗ | ✓ |
| Closest-face selection | ✗ | ✓ |
| IR simulation | ✓ | ✗ |
| Calibration | inline in `state.py` | separate `calibration.py` |

`team_status.md` described the **second** one — HTTP alerts, UDP discovery,
MJPEG streamer, closest-face — and the Android app pairs with it. So that
one survives; `drowsy/` is deleted. The IR simulation was ported across
first, so nothing was lost.

**Layout now:**

```
drowsiness_detector/   the app
inference/             eye_classifier.py
models/                eye_state.tflite, best_eye_cnn.pth, old/
training/              dataset_prep.py, eye_cnn.py, train_colab.ipynb, ...
```

---

## 2. The CNN was never actually running

The model file was committed, but nothing loaded it. `main.py` was purely
geometric — EAR, MAR, head pose, PERCLOS. The `[CLASSIFIER] Loaded model`
line that team_status said to look for could not have appeared.

It runs now, and it is a **second opinion** on eye closure rather than a
replacement, selectable in `config.py`:

```python
CNN_FUSION_MODE = "or"
```

| Mode | Behaviour |
|---|---|
| `ear` | EAR only; CNN shown on screen but ignored |
| `or` | either says closed → closed — **default**, favours recall |
| `and` | both must agree — fewest false alarms |
| `cnn` | CNN decides, EAR as fallback |

`"or"` is the default because a missed drowsy driver is worse than a
spurious beep, and the 2-second duration gate already absorbs single-frame
noise. Your teammate's original approach — CNN consulted only when EAR
already said closed, able only to cancel — is now `"and"`. Worth knowing
that with CLOSED recall at ~72–73%, that mode can only *lower* sensitivity
versus EAR alone.

**This is still a team decision.** It determines what your 30-participant
numbers measure, and it should be stated in the paper.

If the model is missing, fails to load, or both eye crops leave the frame,
every mode falls back to EAR. The system never ends up with no verdict.

**Cost:** ~0.3 ms per frame for both eyes — 0.9% of a 30 FPS budget. No
frame-skipping needed.

---

## 3. Verified against the training code

These were assumptions in team_status. They are now checked against
`training/`:

| Claim | Verdict |
|---|---|
| `softmax[1]` is the closed-probability | ✅ training assigns `0 = OPEN`, `1 = CLOSED` |
| Normalization is `[-1,1]` | ✅ `/255` then `Normalize(0.5, 0.5)` — matches |
| Crop geometry matches training | ❌ **it did not** — see below |

### The crop bug

`dataset_prep.py` pads the landmark box by a fraction of its own **width**
horizontally and its own **height** vertically:

```python
x1 = max(0, int(x1 - w * margin))
y1 = max(0, int(y1 - h * margin))    # height, not width
```

The inference code padded both axes by width, at margin 0.25 instead of 0.3.
That asymmetry is the entire point — a shut eye is only a few pixels tall,
so training's vertical pad nearly vanishes:

| eye state | training | old inference |
|---|---|---|
| wide open | 3.3:1 | 1.9:1 — 1.7× taller |
| half shut | 8.3:1 | 2.4:1 — 3.2× taller |
| **fully shut** | **33:1** | **2.8:1 — 11× taller** |

The model was being fed a distribution it had never seen, worst exactly
where closure detection matters. Now byte-identical to
`dataset_prep._extract_eye_crop` across 800 randomized crops including
near-shut lids.

> `CNN_EYE_MARGIN` must stay **0.3**. If anyone changes the extraction
> margin in `dataset_prep.py`, this has to change with it.

---

## 4. Bugs found and fixed

### Contaminated eye crops

Crops were read from `frame` *after* `draw_landmarks` had painted coloured
dots over the eye. Every patch the CNN saw had six dots on it; training
crops came from clean frames. Now read from `raw_feed`, the untouched copy
the loop already kept.

### PERCLOS ignored calibration

`update_perclos` scored raw EAR against the **static** `EAR_THRESHOLD`, so
the personalised per-driver cutoff never reached PERCLOS at all. It now
takes the fused verdict.

### MAR fired on a slight lip parting

`MAR_THRESHOLD = 0.60` is a good value — but calibration overwrote it with
about **0.06**.

The bar was `baseline_mar * 1.20`. The MAR baseline is a **closed** mouth
(~0.05), so the product is ~0.06 and nearly any mouth movement clears it.
The multiplier works for EAR because there the baseline is the *open* eye
and 0.85 scales down to find "closed". MAR is inverted, and no multiplier
reaches a yawn at 0.70 starting from 0.05.

Replaced with an additive delta, then clamped:

```python
mar_th = min(MAR_THRESHOLD_MAX, max(MAR_THRESHOLD_MIN, baseline + MAR_OPEN_DELTA))
#            0.65                 0.50                            0.55
```

| resting mouth | baseline | old | new |
|---|---|---|---|
| sealed | 0.017 | 0.020 | 0.567 |
| relaxed | 0.050 | 0.060 | **0.600** |
| slightly parted | 0.120 | 0.144 | 0.650 |
| very parted | 0.250 | 0.300 | 0.650 |

The **ceiling** is the bound that matters: someone calibrating with lips
already parted would otherwise get a bar of 0.80 and sail past real yawns —
trading false alarms for false negatives, which is worse. Across baselines
0.0–0.9 the threshold stays in `[0.50, 0.65]`: always above talking (0.30),
always below a yawn (0.70).

### PERCLOS alert spam

The PERCLOS branch called `trigger_alert` directly instead of going through
`StateManager.check()`, so it fired on **every frame** while PERCLOS stayed
high — 200 alerts in 200 frames, about 30 phone alerts a second.

| scenario | before | after |
|---|---|---|
| 200 frames, PERCLOS high | 200 | **1** |
| 60 frames @30 FPS (~2s) | ~60 | **1** |
| 141 frames @30 FPS (~4.7s) | ~141 | **2** |
| while a drowsy alert cools down | — | **0**, suppressed |

`PERCLOS_ALERT_SECONDS = 0.0` — PERCLOS is already a rolling-window
measure and needs no extra sustain time. What it needed was the shared
cooldown.

### The alarm could never clear for some drivers

`is_driver_alert()` re-derived "driver is fine" from raw metrics against
static config values, while `main()` raised alerts from calibrated ones.
Two answers to the same question, free to disagree — and they did.

A driver with baseline EAR 0.22 calibrates to `ear_th = 0.187`, so an alert
needs `ear < 0.187`. But recovery demanded `ear >= 0.25`, which their open
eye never reaches. **The phone alarm could never auto-clear for them** — and
small-eyed drivers are exactly who calibration exists to serve. Head pose
split the same way: alerts used `yaw_offset` (25°), recovery used
`HEAD_YAW_THRESHOLD` (30°).

`is_driver_alert()` now takes the verdicts `main()` already computed:

```python
def is_driver_alert(self, eyes_closed, mouth_open, head_off):
    all_normal = not (eyes_closed or mouth_open or head_off)
```

Recovery and detection now agree **by construction** rather than by
coincidence. This also closed a gap nobody had hit yet: recovery compared
raw EAR and so ignored the CNN entirely — under `"or"` fusion the alarm
could have cleared while the model still saw shut eyes.

---

## 5. Environment

Python **3.11.9** at `C:\Python311\python.exe`, project `.venv`:

```powershell
git pull
C:\Python311\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -r drowsiness_detector\requirements.txt
```

`requirements.txt` gained `ai-edge-litert`, `requests` and `flask`, all of
which the code already needed but never declared.

**On the 3.11 pin:** the `.tflite` is not tied to any Python version — it is
a portable flatbuffer, and it produces bit-identical output on 3.11 and
3.14. The only thing that actually forced 3.11 was `pygame`, which has no
3.14 wheel. `pygame` is now unused (the surviving app has no local audio),
so the pin is no longer a technical constraint. **Keep 3.11 anyway** so the
whole team matches.

---

## 6. Still open

| # | Issue | Why it matters |
|---|---|---|
| 1 | **Never run on a live camera** since consolidation | Everything was verified with camera, landmarker and network stubbed |
| 2 | **Phone-alert failures are silent** | See below — the dangerous one |
| 3 | **PERCLOS threshold 0.80** | Needs eyes shut 24 of 30 seconds; the metric is inert |
| 4 | **Fusion mode not agreed** | Decides what the results measure |
| 5 | `models/old/` sits beside the current model | Make sure the paper cites the right one |

### Why #2 is the dangerous one

There is no local audio any more. If discovery fails or the phone drops off
the hotspot, `HttpAlertClient` keeps POSTing to `127.0.0.1` and swallows
every error:

```python
except requests.exceptions.ConnectionError:
    pass          # no log, no retry, no fallback
```

The laptop still draws its banner, so a session **looks** fine while the
driver is alerted by nothing — and every such alert silently becomes a
false negative in the results. At minimum: log the failure and show
phone-connected status on screen.

### Why #3 needs a decision

Window 30s × threshold 0.80 means eyes shut for **24 of the last 30
seconds** — while the plain eyes-closed alert already fires at 2s. PERCLOS
can only ever fire 12× later than the alert that already covers it, so it
contributes nothing. The literature normally puts the PERCLOS drowsiness
threshold near **0.15**; 0.80 may be a conflation with PERCLOS-P80, which
refers to 80% *eyelid closure*, not 80% *of frames*.

Decide deliberately. If 0.80 stays, the paper should not claim PERCLOS as a
working detector.

---

## How this was tested

No camera or phone was available, so the camera, landmarker, streamer,
discovery and HTTP client were stubbed and `main()`'s real loop was driven
for 60 frames. That exercises the actual code path — fusion, crops, PERCLOS,
alerts, IR toggle, UI — but **it is not a substitute for a live run.**

Also verified: crop parity vs training (800 crops), the fusion truth table
(24 combinations), PERCLOS rate limiting, MAR thresholds across baselines
0.0–0.9, recovery timing and relapse handling, and graceful degradation
when the model is missing.

**Item 1 in "Still open" is there for a reason.** Please run it on a real
face before anyone starts recruiting participants.
