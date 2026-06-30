import threading
import numpy as np

_alarm_active = False
_lock = threading.Lock()

def _generate_beep(frequency=880, duration=0.15, volume=0.8, sample_rate=44100):
    """Generate a square wave beep as numpy array."""
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    wave = np.sign(np.sin(2 * np.pi * frequency * t))
    wave = (wave * volume * 32767).astype(np.int16)
    stereo = np.column_stack([wave, wave])
    return stereo


def _play_pattern(pattern):
    """Play a beep pattern: list of (frequency, duration) tuples."""
    try:
        import pygame
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        for freq, dur in pattern:
            sound_array = _generate_beep(frequency=freq, duration=dur)
            sound = pygame.sndarray.make_sound(sound_array)
            sound.play()
            pygame.time.wait(int(dur * 1000) + 30)
        pygame.mixer.quit()
    except Exception as e:
        print(f"[ALERT] Sound error: {e}")


# Alert patterns per event type
PATTERNS = {
    "drowsy":       [(880, 0.15), (660, 0.15), (880, 0.15), (660, 0.15)],
    "yawning":      [(600, 0.20), (600, 0.20), (600, 0.20)],
    "not_looking":  [(1000, 0.10), (1000, 0.10), (1000, 0.10), (1000, 0.10)],
    "perclos":      [(880, 0.15), (660, 0.15), (880, 0.15), (660, 0.15),
                     (880, 0.15), (660, 0.15)],  # longer for PERCLOS
}


def trigger_alert(alert_type="drowsy"):
    """
    Fire alert sound in a background thread so it never blocks the main loop.
    """
    global _alarm_active
    with _lock:
        if _alarm_active:
            return  # Don't stack sounds
        _alarm_active = True

    def _run():
        global _alarm_active
        pattern = PATTERNS.get(alert_type, PATTERNS["drowsy"])
        _play_pattern(pattern)
        with _lock:
            _alarm_active = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
