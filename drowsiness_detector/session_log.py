"""
Per-session logging for live runs.

Writes two files per session into SESSION_LOG_DIR:

    session_<stamp>.csv   one row per frame
    session_<stamp>.txt   summary, written on exit

The CSV is the raw material for the TP/FP/TN/FN analysis; the summary is
what you read at a glance afterwards. The summary also records the config
that produced the run, so a session stays interpretable months later when
thresholds have moved on.

Nothing here may take down the detection loop. Every public method
swallows its own errors — a failed write loses a log line, never a frame.
"""
import csv
import os
import time
from datetime import datetime

COLUMNS = [
    "t", "frame", "face", "ear", "mar", "yaw", "pitch",
    "cnn_prob", "ear_closed", "cnn_closed", "eyes_closed",
    "mouth_open", "head_off", "perclos", "alerts", "phone",
]

# Rows buffered before touching the disk. At 30 FPS this is a flush every
# ~3 seconds — frequent enough that a crash costs almost nothing, rare
# enough to stay clear of the frame budget.
FLUSH_EVERY = 90


class SessionLogger:
    def __init__(self, enabled=True, log_dir="logs", config_snapshot=None):
        self.enabled = enabled
        self.path_csv = None
        self.path_txt = None
        self._fh = None
        self._writer = None
        self._buf = []
        self._events = []
        self._alerts = {}
        self._frames = 0
        self._faces = 0
        self._start = time.time()
        self._config = config_snapshot or {}
        self._broken = False

        if not enabled:
            return
        try:
            os.makedirs(log_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.path_csv = os.path.join(log_dir, f"session_{stamp}.csv")
            self.path_txt = os.path.join(log_dir, f"session_{stamp}.txt")
            self._fh = open(self.path_csv, "w", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._fh, fieldnames=COLUMNS)
            self._writer.writeheader()
            print(f"[LOG] Session log: {self.path_csv}")
        except Exception as e:
            print(f"[LOG] Could not open session log ({e}) — continuing unlogged.")
            self._broken = True

    # ── recording ─────────────────────────────────────────────────
    def event(self, kind, detail=""):
        """Note a non-per-frame occurrence: calibration, phone state, keys."""
        if not self.enabled:
            return
        try:
            self._events.append((time.time() - self._start, kind, str(detail)))
        except Exception:
            pass

    def frame(self, **row):
        if not self.enabled or self._broken:
            return
        try:
            self._frames += 1
            if row.get("face"):
                self._faces += 1
            for a in (row.get("alerts") or "").split("|"):
                if a:
                    self._alerts[a] = self._alerts.get(a, 0) + 1

            row.setdefault("t", round(time.time() - self._start, 3))
            row.setdefault("frame", self._frames)
            self._buf.append({c: row.get(c, "") for c in COLUMNS})
            if len(self._buf) >= FLUSH_EVERY:
                self._flush()
        except Exception:
            pass

    def _flush(self):
        if not self._writer or not self._buf:
            return
        try:
            self._writer.writerows(self._buf)
            self._fh.flush()
            self._buf.clear()
        except Exception:
            self._broken = True

    # ── teardown ──────────────────────────────────────────────────
    def close(self):
        """Flush the CSV and write the summary. Safe to call twice."""
        if not self.enabled or self.path_csv is None:
            return
        try:
            self._flush()
            if self._fh and not self._fh.closed:
                self._fh.close()
            self._write_summary()
            print(f"[LOG] Session summary: {self.path_txt}")
        except Exception as e:
            print(f"[LOG] Could not finish session log: {e}")

    def _write_summary(self):
        dur = time.time() - self._start
        fps = self._frames / dur if dur > 0 else 0.0
        face_pct = (self._faces / self._frames * 100) if self._frames else 0.0

        lines = []
        add = lines.append
        add("DROWSINESS DETECTION — SESSION SUMMARY")
        add("=" * 52)
        add(f"started   {datetime.fromtimestamp(self._start):%Y-%m-%d %H:%M:%S}")
        add(f"duration  {dur / 60:.1f} min ({dur:.0f}s)")
        add(f"frames    {self._frames}")
        add(f"avg FPS   {fps:.1f}")
        add(f"face seen {self._faces} frames ({face_pct:.1f}%)")
        add("")
        add("ALERTS")
        add("-" * 52)
        if self._alerts:
            for k in sorted(self._alerts):
                add(f"  {k:14s} {self._alerts[k]}")
        else:
            add("  none")
        add("")
        add("EVENTS")
        add("-" * 52)
        if self._events:
            for t, kind, detail in self._events:
                add(f"  [{t:7.1f}s] {kind}{(' — ' + detail) if detail else ''}")
        else:
            add("  none")
        add("")
        add("CONFIG AT RUN TIME")
        add("-" * 52)
        add("  (recorded so this session stays interpretable after")
        add("   thresholds change)")
        for k in sorted(self._config):
            add(f"  {k:26s} {self._config[k]}")
        add("")
        add(f"per-frame data: {os.path.basename(self.path_csv)}")

        with open(self.path_txt, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
