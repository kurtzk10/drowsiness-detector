import time
import numpy as np
from dataclasses import dataclass, field


@dataclass
class CalibrationResult:
    baseline_ear: float = 0.0
    baseline_mar: float = 0.0
    baseline_yaw: float = 0.0
    baseline_pitch: float = 0.0
    thresholds: dict = field(default_factory=dict)

    def is_valid(self):
        return self.baseline_ear > 0


class Calibrator:
    """
    Samples metrics for CALIBRATION_SECONDS and computes dynamic thresholds.
    """

    def __init__(self, duration, ear_mult, mar_delta, mar_min, mar_max,
                 yaw_offset, pitch_offset):
        self._duration = duration
        self._ear_mult = ear_mult
        self._mar_delta = mar_delta
        self._mar_min = mar_min
        self._mar_max = mar_max
        self._yaw_offset = yaw_offset
        self._pitch_offset = pitch_offset
        self.reset()

    def reset(self):
        self._samples_ear = []
        self._samples_mar = []
        self._samples_yaw = []
        self._samples_pitch = []
        self._start_time = None
        self._finished = False
        self._result = None

    def start(self):
        self.reset()
        self._start_time = time.time()

    def is_running(self):
        return self._start_time is not None and not self._finished

    def elapsed(self):
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    def remaining(self):
        return max(0.0, self._duration - self.elapsed())

    def progress(self):
        return min(1.0, self.elapsed() / self._duration)

    def add_sample(self, ear, mar, yaw, pitch):
        if not self.is_running():
            return
        if ear > 0:
            self._samples_ear.append(ear)
            self._samples_mar.append(mar)
            self._samples_yaw.append(yaw)
            self._samples_pitch.append(pitch)

        if self.elapsed() >= self._duration:
            self._finalize()

    def _finalize(self):
        self._finished = True
        if len(self._samples_ear) == 0:
            self._result = CalibrationResult()
            return

        avg_ear = float(np.mean(self._samples_ear))
        avg_mar = float(np.mean(self._samples_mar))
        avg_yaw = float(np.mean(self._samples_yaw))
        avg_pitch = float(np.mean(self._samples_pitch))

        self._result = CalibrationResult(
            baseline_ear=avg_ear,
            baseline_mar=avg_mar,
            baseline_yaw=avg_yaw,
            baseline_pitch=avg_pitch,
            thresholds={
                "ear": round(avg_ear * self._ear_mult, 4),
                # Additive, not multiplicative: the MAR baseline is a
                # closed mouth near zero, and no multiplier gets from
                # there to a yawn. The floor keeps a driver who rests
                # with parted lips from lowering their own bar.
                "mar": round(min(self._mar_max,
                                 max(self._mar_min,
                                     avg_mar + self._mar_delta)), 4),
                "yaw": round(avg_yaw + self._yaw_offset, 2),
                "pitch": round(avg_pitch + self._pitch_offset, 2),
            },
        )

    def get_result(self):
        return self._result

    def get_status_text(self):
        if self._start_time is None:
            return ""
        if self._finished:
            return "Calibration complete!"
        remaining = self.remaining()
        return f"Calibrating... {remaining:.0f}s"
