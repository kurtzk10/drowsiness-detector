import time
from collections import deque
from config import (
    EAR_ALERT_SECONDS, MAR_ALERT_SECONDS, HEAD_ALERT_SECONDS,
    ALERT_COOLDOWN_SECONDS, PERCLOS_WINDOW_SECONDS, PERCLOS_THRESHOLD,
    PERCLOS_ALERT_SECONDS, PERCLOS_MIN_WINDOW_SECONDS,
    EAR_THRESHOLD, RECOVERY_SECONDS
)


class StateManager:
    """
    Tracks duration of each alert condition and manages cooldowns.
    Also computes PERCLOS over a rolling time window.
    """

    def __init__(self, now_fn=None):
        # Clock source. Defaults to wall time; offline replay passes a
        # video-time function instead, so a clip decoded faster than real
        # time still measures durations in the footage's own seconds
        # rather than the machine's. Alert counts then reproduce exactly.
        self._now = now_fn or time.time

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
            "perclos": PERCLOS_ALERT_SECONDS,
        }

    # ── Core check ────────────────────────────────────────────────
    def check(self, name, condition):
        """
        Returns True if condition has been True long enough to alert,
        and the alert is not in cooldown.
        """
        now = self._now()
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
        return self._now() - self._start[name]

    # ── PERCLOS ───────────────────────────────────────────────────
    def update_perclos(self, ear, closed=None):
        """
        Push current EAR reading into the rolling window.
        Returns current PERCLOS value (0.0 to 1.0).
        """
        now = self._now()
        self._ear_history.append((now, ear, closed))
        # Drop entries older than the window
        cutoff = now - PERCLOS_WINDOW_SECONDS
        while self._ear_history and self._ear_history[0][0] < cutoff:
            self._ear_history.popleft()

        if len(self._ear_history) == 0:
            return 0.0

        # A ratio over a nearly-empty window is noise, not a measurement:
        # one closed frame out of one reads as 100%. Report 0 until the
        # history actually spans enough time to mean something.
        span = self._ear_history[-1][0] - self._ear_history[0][0]
        if span < PERCLOS_MIN_WINDOW_SECONDS:
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
        return self._cooldown_until.get(name, 0) > self._now()

    # ── Recovery / auto-clear ────────────────────────────────────
    def is_driver_alert(self, eyes_closed, mouth_open, head_off):
        """
        Returns True once every condition has stayed clear for
        RECOVERY_SECONDS, meaning the driver is alert again and the phone
        alarm can be cleared.

        Takes the verdicts main() has already computed rather than
        re-deriving them from raw metrics. Those verdicts carry the
        calibrated thresholds and the CNN fusion; re-deriving here against
        the static config values let recovery and alerting disagree — a
        driver calibrating to ear_th 0.187 had to reach ear >= 0.25 to
        clear, which their open eye never did, so the alarm never cleared.
        Sharing the verdict makes the two agree by construction.
        """
        now = self._now()
        all_normal = not (eyes_closed or mouth_open or head_off)
        if all_normal:
            if "recovery" not in self._start:
                self._start["recovery"] = now
            return (now - self._start["recovery"]) >= RECOVERY_SECONDS
        else:
            self._start.pop("recovery", None)
            return False
