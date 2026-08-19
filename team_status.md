# Drowsiness Detection — Team Status & Next Steps
**Last updated:** 19 August 2026

---

## System Status: ONE CODEBASE ✅ — NOT YET CAMERA-TESTED ⚠️

The repo used to carry two divergent detectors. It now carries one.
Everything needed to run is in git — **nobody needs to copy files from
Drive any more.**

---

## ⚠️ Read this first — what changed on 19 Aug

**1. `drowsy/` is gone.** There were two apps: `drowsiness_detector/`
(phone alerts, discovery, streamer, closest-face) and
`drowsy/drowsiness_detector/` (local beeps, IR sim). The first survives —
it is what this document always described and what the Android app pairs
with. The IR simulation was ported across so nothing was lost.
**If you have local work in `drowsy/`, speak up before you pull.**

**2. The "replace 3 files from Drive" task is obsolete.**
`eye_state.tflite`, `eye_classifier.py`, `dataset_prep.py` and the rest of
the training pipeline are all committed. Pull instead of copying.

**3. The CNN is actually wired in now.** It previously was not called at
all on the build branch — the model file was present but nothing loaded it.

**4. Python 3.11 is set up** at `C:\Python311\python.exe`, with a project
`.venv`. See Setup below.

---

## What Is Done

### Code & System
- [x] Python detection pipeline (EAR, MAR, Head Pose, PERCLOS, Calibration)
- [x] MediaPipe FaceLandmarker integration
- [x] Duration-based state manager (prevents false alarms)
- [x] HTTP alert system (laptop → phone)
- [x] Phone hotspot offline architecture
- [x] Android alert app (rings + vibrates + event log)
- [x] Auto phone discovery (UDP broadcast)
- [x] MJPEG streamer (port 8080)
- [x] Closest face selection (picks driver face)
- [x] Calibration system (personalizes thresholds per driver)
- [x] IR / night-vision simulation (`I` key)
- [x] **Single consolidated codebase** — `drowsy/` removed

### CNN Hybrid Model
- [x] Dataset extracted: 190,490 eye crops (YawDD + NTHU-DD)
- [x] Label accuracy verified: 99.7% (spot-checked 150 samples)
- [x] Timestamp bug fixed in dataset_prep.py
- [x] Video-based group split (zero data leakage)
- [x] Model retrained: 87.3% honest accuracy
- [x] Exported: eye_state.tflite (259.4 KB)
- [x] **Model loaded and running in main.py** (genuinely, as of 19 Aug)
- [x] **Configurable EAR/CNN fusion** — `CNN_FUSION_MODE`
- [x] Whole training pipeline committed to git
- [x] **MAR yawn threshold fixed** — calibration was overwriting 0.60 with
      ~0.06, so a slight lip parting fired the yawn alert. Now additive and
      clamped to `[0.50, 0.65]`.

### Verified against the training code (19 Aug)
These were assumptions before. They are now checked:
- [x] **Class order** — training assigns `0 = OPEN`, `1 = CLOSED`, so
      `softmax[1]` really is the closed-probability. Not flipped.
- [x] **Normalization** — training does `/255` then `Normalize(0.5, 0.5)`,
      exactly the `[-1,1]` the classifier applies.
- [x] **Crop geometry** — inference crops are byte-identical to
      `dataset_prep._extract_eye_crop` across 800 randomized crops,
      including near-shut lids.
- [x] **Cost** — ~0.3 ms/frame for both eyes, 0.9% of a 30 FPS budget.

### Thesis Paper
- [x] Chapter 1 — Introduction (mostly complete)
- [x] Chapter 1 — RRL (complete with research gap)
- [x] Chapter 1 — Conceptual Framework (figures in place)
- [x] Chapter 2 — All Methods sections written
- [x] Activity Schedule submitted (Aug 4)
- [x] Expert validators contacted (AI + Systems Engineer)

---

## Setup (replaces the old "copy from Drive" steps)

```powershell
git pull
C:\Python311\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -r drowsiness_detector\requirements.txt
```

Run:
```powershell
cd drowsiness_detector
..\.venv\Scripts\python.exe main.py
```

Expected startup lines:
```
[CLASSIFIER] Loaded model from ...models\eye_state.tflite (259.4 KB)
[INFO] CNN fusion mode: or (closed if p > 0.5)
```

**Python 3.11.9.** Not 3.14 — `pygame` has no 3.14 wheel. Everything else
in the stack does, so if `pygame` is ever dropped, 3.13/3.14 become viable.

Keys: `Q` quit · `C` calibrate · `I` toggle IR simulation

---

## What Still Needs to Be Done

### 🔴 Critical — Do First

**1. Run it on a real camera.**
Everything above was verified with the camera, landmarker and network
stack stubbed. The full loop executes and the model produces sane outputs,
but **nobody has pointed it at a live face since the consolidation.**
Do this before anything else.
```
- Does calibration complete and produce sensible thresholds?
- Does the phone still pair (discovery → HTTP alert → alarm)?
- Does the MJPEG stream still serve on :8080?
- What does "CNN shut:" read when you deliberately close your eyes?
- FPS with the CNN on?
```

**2. Decide the fusion mode — it decides what your results measure.**
Default is `"or"` (either EAR or CNN says closed → closed), chosen for
recall: a missed drowsy driver is worse than a spurious beep, and the 2s
duration gate absorbs single-frame noise.
The earlier veto-only approach (CNN consulted only when EAR already said
closed, and able only to cancel) is available as `"and"`. With CLOSED
recall at ~72–73%, veto-only can only *lower* sensitivity versus EAR alone.
**The whole team should agree, and the choice must be stated in the paper.**

**3. Two alert-path bugs remain (two are fixed).**

~~**3a. PERCLOS alert spam**~~ — ✅ fixed in `bc0dc27`. It now goes through
`StateManager.check()` like every other alert: 1 alert per cooldown
instead of 200 in 200 frames.

~~**3b. Auto-clear ignores calibration**~~ — ✅ fixed in `7d669d6`.
`is_driver_alert()` now takes the `eyes_closed` / `mouth_open` / `head_off`
verdicts that `main()` already computed, so recovery and detection agree by
construction. This also means the CNN feeds recovery, which it never did
before.

**3c. PERCLOS threshold is effectively dead.** Window 30s, threshold 0.80
means eyes must be shut for **24 of the last 30 seconds** — while the
plain eyes-closed alert already fires at 2s. PERCLOS can only ever fire
12x later than the alert that already covers it, so it contributes
nothing. Drowsiness literature normally puts the PERCLOS drowsiness
threshold near **0.15**, not 0.80. Decide whether 0.80 is intended; if it
stays, the paper should not claim PERCLOS as a working detector.

**3d. Phone alert failures are completely silent.** There is no local
audio any more — `pygame` is gone with the old app. If discovery fails or
the phone drops off the hotspot, `HttpAlertClient` keeps POSTing to
`127.0.0.1` and swallows every error:
```python
except requests.exceptions.ConnectionError:
    pass          # no log, no retry, no fallback
```
The laptop still draws its banner, so the session *looks* fine while the
driver is being alerted by nothing. **Every such alert silently becomes a
false negative in your results.** At minimum log the failure and show
phone-connected status on screen.

**4. Fix remaining paper issues**
```
- Title page: names are broken/split wrong
- Output section: remove "over the internet" → local HTTP
- Scope Delimitations: remove internet dependency claim
- Approval Sheet: still says THESIS TITLE
- Specific Objectives: add head pose + CNN + Android objectives
- List of Tables: remove Likert Scale entry
- List of Figures: fix Figure 2 and 3 labels
- References: remove Qin et al. (ophthalmology paper)
- Significance: remove "infrared imaging"  <- but note IR SIMULATION does
                                              exist; describe it honestly
- Sources of Data: replace "preset datasets" with YawDD + NTHU-DD
- Cover Page: replace "Month Year" with actual date
- Acknowledgment: replace placeholder text with real content
```

**5. Android app UI finalization**
- Polish alert screens (red/yellow/orange per event type)
- Add app logo
- Test dismiss button
- Test event log display

---

### 🟡 Important — Do This Week

**6. Participant Testing (30 drivers)**
```
Criteria: licensed drivers, ages 18-55, normal/corrected vision,
          no facial condition affecting eye/mouth shape

Setting:  private enclosed area, low speed, observer present

Per session:
  1. Participant sits in driver seat
  2. Press C to calibrate (look straight)
  3. Drive session 10-15 minutes
  4. Observer notes ground truth manually
  5. System logs automatically

Collect per alert: TP / FP / TN / FN
```
Do **not** start until items 1–3 above are closed.

**7. Prepare testing documents**
- Informed consent form (30 copies)
- Data collection sheet per participant
- Observer ground truth checklist

---

### 🟠 After Participant Testing

**8. Analyze results** — per alert type (drowsy / yawning / not looking)
```
Accuracy  = (TP + TN) / Total      Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)         F1 = 2 x (P x R) / (P + R)
Average FPS during sessions - False alarm rate
```
Consider reporting an **ablation across `CNN_FUSION_MODE`** (`ear` vs `or`
vs `and` vs `cnn`). It is one config line per run and turns "we added a
CNN" into a measured claim.

**9. Write Abstract** (150-250 words)
`Problem → Gap → Solution → Method → Results → Conclusion`

**10. Write Results Chapter**
```
3.1 CNN Model Performance — 87.3%, OPEN recall ~93%, CLOSED ~72-73%,
    label accuracy 99.7%, confusion matrix (from training/)
3.2 Participant Testing Results (30 drivers)
3.3 System Performance (FPS, latency, CNN cost ~0.3 ms/frame)
3.4 Threshold Calibration Results
3.5 Fusion-mode ablation   <- new, if you run it
```

**11. Write Discussion Chapter**
```
4.1 Interpretation - 4.2 Comparison with Literature - 4.3 Limitations
4.4 Conclusion - 4.5 Future Work
```
A limitation worth stating honestly: CLOSED recall is the weak side of the
model (~72–73%), which is precisely why EAR is kept in the loop rather
than replaced by the CNN.

**12. Complete Appendices**
```
A Cover Letter - B Consent Form - C Sample Instrument - D Use Case Diagram
E Data Flow Diagram - G Data Dictionary (source: training/dataset_prep.py)
H Gantt Chart (done) - I Screenshots - J Hardware/Software Spec
K Experts CV - L Editor's Note - M Plagiarism Certificate - N Researchers CV
```

---

### 🔵 Defense Preparation

**13. Build slide deck (10 slides)**
```
1 Title + members - 2 Problem - 3 Objectives - 4 Architecture
5 Methodology (IPO) - 6 Algorithms (EAR, MAR, Head Pose, PERCLOS, CNN)
7 CNN results + confusion matrix - 8 Live demo
9 Participant results - 10 Conclusion + future work
```

**14. Demo rehearsal (3+ times)**
```
Startup → calibration → normal → drowsy → yawning → not looking
→ show phone event log
```

**15. Final document checks**
Plagiarism check - Editor review - Adviser approval - Submit

---

## Known Open Issues

| # | Issue | Impact | Status |
|---|---|---|---|
| 1 | PERCLOS alert has no cooldown — ~30 alerts/sec | Alert spam; blocks testing | ✅ **fixed** `bc0dc27` |
| 2 | Auto-clear uses static thresholds, not calibrated | Alarm can never clear for small-eyed drivers | ✅ **fixed** `7d669d6` |
| 3 | PERCLOS threshold 0.80 needs 24s of 30s closed | Metric contributes nothing | ✅ **now 0.15 / 60s** `dad6959` — validate in pilot |
| 4 | Phone-alert failures silent — no audio, no log | Alerts vanish; become false negatives | ✅ **surfaced** `dad6959` — see caveat below |
| 5 | Never run against a live camera since consolidation | Unknown | **open — yours** |
| 6 | Fusion mode not yet agreed by the team | Changes what the results mean | open — **team decision** |
| 7 | `models/old/` kept beside the current model | Make sure the paper cites the right one | check |
| 8 | `display.py` hardcodes `0.80` instead of `PERCLOS_THRESHOLD` | Cosmetic; UI lies if config changes | ✅ fixed `dad6959` |
| 9 | `except requests.exceptions...` when `requests` may be `None` | AttributeError on an unrelated failure | ✅ fixed `dad6959` |

**Caveat on #4:** failures are now *visible* — the sidebar shows
`PHONE OK` / `PHONE FAIL xN` / `NO PHONE`, and the console logs once every
10s rather than 30×/second. But there is still **no local audio**, so an
unreachable phone still means the driver hears nothing. The operator can
now see it happening; the driver is still not alerted. Restoring a laptop
beep as a fallback is a separate decision.

**Note:** `pygame` is no longer used by anything — the surviving app has no
local audio. The Python 3.11 pin therefore no longer applies technically
(3.13/3.14 would work). Keep 3.11 anyway so the whole team matches, but the
constraint is worth knowing if it ever gets in the way.

---

## CNN Model Summary

| Item | Value |
|---|---|
| Accuracy | 87.3% (honest, video-based split) |
| OPEN recall | ~93% |
| CLOSED recall | ~72-73% |
| Label accuracy | 99.7% |
| Training samples | 190,490 eye crops |
| Datasets | YawDD + NTHU-DD |
| Input / Output | `[1,1,32,64]` float32 NCHW / `[1,2]` logits |
| Class order | 0 = OPEN, 1 = CLOSED |
| Preprocessing | `/255` then `(x-0.5)/0.5` → `[-1,1]` |
| Crop margin | **0.3 — must match `training/dataset_prep.py`** |
| Size / cost | 259.4 KB · ~0.3 ms per frame (both eyes) |

---

## Priority Order This Week

```
1. Live-camera test of the consolidated app       <- blocks everything
2. Pilot run: validate PERCLOS 0.15 and the fusion mode
3. Agree the fusion mode with the team            <- blocks Results
4. Fix paper issues
5. Finalize Android app UI
6. Start participant recruitment
7. Conduct 30 participant sessions
8. Write Results + Discussion
```

Item 1 still gates everything, and it is the one nobody has done. Every
verification so far ran with the camera, landmarker and network stubbed,
or over a synthetic clip — the pipeline has never seen a real face.

Item 2 matters because PERCLOS just went from inert to live. At 0.15 it
can now actually fire, which is the point, but nobody has yet seen what
rate it fires at on real footage. Check that before it reaches
participants, not after.

## Offline validation — `tools/validate_video.py`

Runs the real pipeline over a recorded clip, headless, and writes a
per-frame CSV plus a summary:

```powershell
.venv\Scripts\python.exe tools\validate_video.py clip.mp4
.venv\Scripts\python.exe tools\validate_video.py clip.mp4 --fusion and
```

Record one clip of a driver, then replay it through each fusion mode. Same
footage, four modes, directly comparable — that is the Results 3.5 ablation
with no extra sessions. It also reports the processing FPS that Results 3.3
needs. Repeat runs produce byte-identical CSVs.

It is **not** a substitute for item 1: it never touches a camera, a window,
or the phone.
