import time
from collections import deque
from config import (
    EAR_ALERT_SECONDS, MAR_ALERT_SECONDS, HEAD_ALERT_SECONDS,
    ALERT_COOLDOWN_SECONDS, PERCLOS_WINDOW_SECONDS, PERCLOS_THRESHOLD,
    EAR_THRESHOLD, MAR_THRESHOLD, HEAD_YAW_THRESHOLD, HEAD_PITCH_THRESHOLD,
    RECOVERY_SECONDS
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

        # PERCLOS: rolling window of (timestamp, ear_value, closed) tuples
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
    def update_perclos(self, ear, closed=None):
        """
        Push current EAR reading into the rolling window.
        Returns current PERCLOS value (0.0 to 1.0).
        """
        now = time.time()
        self._ear_history.append((now, ear, closed))
        # Drop entries older than the window
        cutoff = now - PERCLOS_WINDOW_SECONDS
        while self._ear_history and self._ear_history[0][0] < cutoff:
            self._ear_history.popleft()

        if len(self._ear_history) == 0:
            return 0.0

        # An explicit per-frame verdict (from the EAR/CNN fusion) wins when
        # supplied. Without it we fall back to the static config threshold,
        # which ignores calibration — so passing `closed` is what makes
        # PERCLOS agree with the alert it is supposed to predict.
        closed_count = sum(
            1 for _, e, c in self._ear_history
            if (c if c is not None else e < EAR_THRESHOLD)
        )
        return round(closed_count / len(self._ear_history), 4)

    def is_drowsy_perclos(self, perclos):
        return perclos >= PERCLOS_THRESHOLD

    # ── In-cooldown helper for UI ──────────────────────────────────
    def in_cooldown(self, name):
        return self._cooldown_until.get(name, 0) > time.time()

    # ── Recovery / auto-clear ────────────────────────────────────
    def is_driver_alert(self, ear, mar, yaw, pitch):
        """
        Returns True if ALL metrics have been normal for RECOVERY_SECONDS,
        meaning the driver is alert again and we can clear the phone alarm.
        """
        now = time.time()
        all_normal = (
            ear >= EAR_THRESHOLD
            and mar <= MAR_THRESHOLD
            and abs(yaw) <= HEAD_YAW_THRESHOLD
            and abs(pitch) <= HEAD_PITCH_THRESHOLD
        )
        if all_normal:
            if "recovery" not in self._start:
                self._start["recovery"] = now
            return (now - self._start["recovery"]) >= RECOVERY_SECONDS
        else:
            self._start.pop("recovery", None)
            return False
