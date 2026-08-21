# Build1.2.1 — Changes Summary
**Date:** 21 August 2026  
**Branch:** build1.2.1

---

## Python Side Changes

### http_alerts.py
| What | Before | After |
|---|---|---|
| HTTP timeout | `timeout=1.0` | `timeout=(3.0, 15.0)` |
| Response handling | Strict — only 200 = success | Any response = success |
| Failure condition | Any exception | Only ConnectionRefused or timeout |

**Why:** Python was logging "Alert NOT delivered" even when phone successfully received and played the alarm. The phone's NanoHTTPD launches AlarmActivity before sending HTTP response — so Python timed out before response arrived. Fix treats any connection success as delivered.

---

### config.py
| What | Before | After |
|---|---|---|
| RECOVERY_SECONDS | `3.0` | `8.0` |

**Why:** Alarm was stopping after only 3 seconds of looking forward — too easy to accidentally dismiss. Now requires 8 full seconds of sustained alert behavior before auto-clear fires.

---

### main.py
| What | Before | After |
|---|---|---|
| Auto-clear condition | `is_driver_alert(eyes, mouth, head)` | `is_driver_alert(eyes, mouth, head) and not perclos_high` |

**Why:** Alarm was clearing even when PERCLOS was still elevated. A brief 3-second glance forward could dismiss an alarm raised from 60 seconds of accumulated drowsiness. Now PERCLOS must also be low before auto-clear fires.

---

### discovery.py
| What | Status |
|---|---|
| Gateway filter (attempted) | ❌ Reverted — would break phone hotspot discovery |
| Current state | Back to committed build1.2.1 state |

**Note:** Discovery still picks up wrong IP (`10.49.56.20`) on some networks. Workaround is setting `PHONE_IP` manually in config.py.

---

## Android App Side Changes

### app/build.gradle.kts
| What | Before | After |
|---|---|---|
| Release signing | No signing config | Signs with debug keystore |
| Minification | Not configured | `isMinifyEnabled = true` |
| Resource shrinking | Not configured | `isShrinkResources = true` |

**Why:** Release APK is more stable than debug — foreground service stays alive longer, better background performance, discovery broadcaster works more reliably.

---

## Already Implemented (No Changes Needed)

These were checked and confirmed already correct:

| Feature | File | Status |
|---|---|---|
| Foreground service | AlertService.java | ✅ startForeground() in onCreate() |
| Notification channel | AlertService.java | ✅ createNotificationChannel() |
| FOREGROUND_SERVICE permission | AndroidManifest.xml | ✅ Present |
| POST_NOTIFICATIONS permission | AndroidManifest.xml | ✅ Present |
| foregroundServiceType | AndroidManifest.xml | ✅ dataSync |
| setLooping(true) | MainActivity.java | ✅ Already set |
| Volume down dismiss | MainActivity.java | ✅ onKeyDown() implemented |
| DiscoveryBroadcaster fix | DiscoveryBroadcaster.java | ✅ Per-interface broadcast in APK |

---

## Bugs Found and Root Causes

### "Alert NOT delivered" false negative
**Root cause:** HTTP read timeout fired before NanoHTTPD sent response  
**Fix:** Changed to `(3.0, 15.0)` — connect timeout 3s, read timeout 15s

### Alarm stops randomly
**Root cause:** `RECOVERY_SECONDS = 3.0` — too short, normal driving clears alarm  
**Fix:** Raised to 8.0 seconds

### Alarm clears despite high PERCLOS
**Root cause:** Auto-clear only checked instantaneous metrics, not rolling PERCLOS  
**Fix:** Added `and not perclos_high` to auto-clear condition

### Discovery locks to wrong IP
**Root cause:** Another device on network responding to UDP port 9876  
**Workaround:** Set `PHONE_IP = "x.x.x.x"` manually in config.py  
**Permanent fix:** Install release APK with per-interface DiscoveryBroadcaster

---

## What Still Needs to Be Done

```
⬜ Find phone's actual IP and set in config.py (fixes PHONE FAIL permanently)
⬜ Rebuild release APK (.\gradlew assembleRelease)
⬜ Uninstall old APK on phone
⬜ Install new release APK
⬜ Disable battery optimization on phone for DrowsinessAlertApp
⬜ Test with screen locked
⬜ Test with app in background
⬜ Participant testing (30 drivers)
```

---

## How to Rebuild APK

```powershell
cd C:\Users\JUSTINELUISCALAGUAS\Desktop\drowsy\drowsiness_detector\android\DrowsinessAlertApp
$env:JAVA_HOME = "C:\Program Files\Microsoft\jdk-17.0.20.8-hotspot"
.\gradlew assembleRelease
```

APK location after build:
```
app\build\outputs\apk\release\app-release.apk
```

---

## How to Find Phone IP

```powershell
arp -a
```

Look for your phone's MAC address manufacturer prefix (Samsung, Xiaomi, etc.)  
The IP next to it is your phone's actual IP.  
Set it in `drowsiness_detector/config.py`:
```python
PHONE_IP = "x.x.x.x"  # your phone's actual IP
```

---

## Battery Optimization (Do This on Each Test Phone)

```
Settings → Apps → DrowsinessAlertApp
→ Battery → Unrestricted
```

This ensures Android never kills the foreground service during participant testing sessions.
