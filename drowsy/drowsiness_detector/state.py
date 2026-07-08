import time
import statistics
from collections import deque
from config import (
    EAR_ALERT_SECONDS, MAR_ALERT_SECONDS, HEAD_ALERT_SECONDS,
    ALERT_COOLDOWN_SECONDS, PERCLOS_WINDOW_SECONDS, PERCLOS_THRESHOLD,
    EAR_THRESHOLD, EAR_CLOSED_RATIO
)


class StateManager:
    """
    Tracks duration of each alert condition and manages cooldowns.
    Also computes PERCLOS over a rolling time window.
    """

    def __init__(self):
        # Timers: when did each condition START being true
        self._start = {}
        # Cooldowns: when is each alert allowed to fire again
        self._cooldown_until = {}

        # Active "eyes closed" cutoff — replaced by the per-driver value
        # from calibration; defaults to the fixed config threshold.
        self.ear_threshold = EAR_THRESHOLD

        # PERCLOS: rolling window of (timestamp, ear_value) tuples
        self._ear_history = deque()

        # Durations per metric
        self._durations = {
            "eyes":    EAR_ALERT_SECONDS,
            "mouth":   MAR_ALERT_SECONDS,
            "head":    HEAD_ALERT_SECONDS,
        }

    # ── Core check ────────────────────────────────────────────────
    def check(self, name, condition):
        """
        Returns True if condition has been True long enough to alert,
        and the alert is not in cooldown.
        """
        now = time.time()
        required = self._durations[name]

        # In cooldown — skip
        if self._cooldown_until.get(name, 0) > now:
            return False

        if condition:
            if name not in self._start:
                self._start[name] = now
            elapsed = now - self._start[name]
            if elapsed >= required:
                # Fire alert, set cooldown, reset timer
                self._cooldown_until[name] = now + ALERT_COOLDOWN_SECONDS
                self._start.pop(name, None)
                return True
        else:
            # Reset timer when condition clears
            self._start.pop(name, None)

        return False

    # ── Elapsed time for progress bar ─────────────────────────────
    def get_elapsed(self, name, condition):
        """How many seconds the condition has been active (for UI bar)."""
        if not condition:
            return 0.0
        if name not in self._start:
            return 0.0
        return time.time() - self._start[name]

    # ── PERCLOS ───────────────────────────────────────────────────
    def update_perclos(self, ear):
        """
        Push current EAR reading into the rolling window.
        Returns current PERCLOS value (0.0 to 1.0).
        """
        now = time.time()
        self._ear_history.append((now, ear))
        # Drop entries older than the window
        cutoff = now - PERCLOS_WINDOW_SECONDS
        while self._ear_history and self._ear_history[0][0] < cutoff:
            self._ear_history.popleft()

        if len(self._ear_history) == 0:
            return 0.0

        closed = sum(1 for _, e in self._ear_history if e < self.ear_threshold)
        return round(closed / len(self._ear_history), 4)

    def is_drowsy_perclos(self, perclos):
        return perclos >= PERCLOS_THRESHOLD

    def set_ear_threshold(self, value):
        """Adopt a per-driver eyes-closed cutoff (from calibration)."""
        self.ear_threshold = value

    # ── In-cooldown helper for UI ──────────────────────────────────
    def in_cooldown(self, name):
        return self._cooldown_until.get(name, 0) > time.time()


class Calibrator:
    """
    Captures the driver's neutral head pose at startup so that "not
    looking" is measured as deviation from where they naturally sit,
    not from an absolute zero.

    Collects yaw/pitch samples over a short window (only while a face is
    present) and uses the median — robust to a stray frame — as the
    baseline. Head-pose checks then subtract this baseline.
    """

    def __init__(self, duration):
        self.duration = duration
        self.yaw_offset = 0.0
        self.pitch_offset = 0.0
        self.ear_baseline = 0.0
        self.ear_threshold = EAR_THRESHOLD   # per-driver eyes-closed cutoff
        self.done = False
        self._start = None
        self._yaw_samples = []
        self._pitch_samples = []
        self._ear_samples = []

    def add_sample(self, yaw, pitch, ear):
        """
        Record one pose + EAR sample. The countdown starts on the first
        sample, so calibration only progresses while a face is tracked.
        Returns the seconds remaining (0.0 once complete).
        """
        now = time.time()
        if self._start is None:
            self._start = now

        self._yaw_samples.append(yaw)
        self._pitch_samples.append(pitch)
        self._ear_samples.append(ear)

        remaining = self.duration - (now - self._start)
        if remaining <= 0:
            self._finish()
            return 0.0
        return remaining

    def _finish(self):
        if self._yaw_samples:
            self.yaw_offset = statistics.median(self._yaw_samples)
            self.pitch_offset = statistics.median(self._pitch_samples)
            self.ear_baseline = statistics.median(self._ear_samples)
            # Personalize the closed-eye cutoff to this driver's open-eye
            # EAR so small or large eyes don't skew detection. Median
            # shrugs off the odd blink during calibration. Guard against a
            # degenerate (near-zero) baseline by keeping the default.
            if self.ear_baseline > 0.05:
                self.ear_threshold = round(self.ear_baseline * EAR_CLOSED_RATIO, 4)
            else:
                self.ear_threshold = EAR_THRESHOLD
        self.done = True

    def remaining(self):
        """Seconds left; full duration before the first sample is seen."""
        if self.done:
            return 0.0
        if self._start is None:
            return self.duration
        return max(0.0, self.duration - (time.time() - self._start))

    def reset(self):
        """Restart calibration from scratch (bound to the 'c' key)."""
        self.__init__(self.duration)
