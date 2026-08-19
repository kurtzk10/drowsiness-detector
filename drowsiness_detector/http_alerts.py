import threading
import json
import time
from queue import Queue, Empty

# A failing phone would otherwise log on every queued alert. One line per
# interval is enough to notice, and quiet enough to leave running.
FAILURE_LOG_INTERVAL = 10.0

try:
    import requests
except ImportError:
    requests = None


class HttpAlertClient:
    """
    Non-blocking HTTP client that sends alert/clear POST requests
    to the phone's NanoHTTPD server.

    Uses a background thread + queue so the detection loop never blocks.
    """

    def __init__(self, phone_ip=None, phone_port=5000):
        self._base_url = f"http://{phone_ip or '127.0.0.1'}:{phone_port}"
        self._lock = threading.Lock()
        self._queue = Queue()
        self._running = True

        # Delivery state. Alerts are fire-and-forget over the queue, so
        # without this a phone that never answers looks identical to one
        # that is working — the loop gets no feedback either way.
        self._phone_found = phone_ip is not None
        self._last_send_ok = None      # None = nothing sent yet
        self._consecutive_failures = 0
        self._last_failure_log = 0.0

        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def update_phone(self, ip, port=5000):
        with self._lock:
            self._base_url = f"http://{ip}:{port}"
            self._phone_found = True
            self._last_send_ok = None
            self._consecutive_failures = 0

    def _worker(self):
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except Empty:
                continue

            endpoint, payload = item
            with self._lock:
                url = f"{self._base_url}{endpoint}"
            if requests is None:
                self._record_failure("requests not installed")
                continue

            try:
                requests.post(
                    url,
                    json=payload,
                    timeout=1.0,
                    headers={"Connection": "close"},
                )
            except requests.exceptions.Timeout:
                self._record_failure(f"timeout talking to {url}")
            except requests.exceptions.ConnectionError:
                self._record_failure(f"cannot reach {url}")
            except Exception as e:
                self._record_failure(f"{type(e).__name__} sending to {url}")
            else:
                self._record_success()

    # ── Delivery bookkeeping ──────────────────────────────────────
    def _record_success(self):
        with self._lock:
            recovered = self._consecutive_failures > 0
            self._last_send_ok = True
            self._consecutive_failures = 0
        if recovered:
            print("[ALERTS] Phone reachable again.")

    def _record_failure(self, reason):
        now = time.time()
        with self._lock:
            self._last_send_ok = False
            self._consecutive_failures += 1
            n = self._consecutive_failures
            due = (now - self._last_failure_log) >= FAILURE_LOG_INTERVAL
            if due:
                self._last_failure_log = now
        if due:
            print(f"[ALERTS] Alert NOT delivered ({n} in a row): {reason}")

    def status(self):
        """
        ("NO PHONE" | "PHONE OK" | "PHONE FAIL", consecutive_failures)
        for the on-screen indicator. Cheap enough to call every frame.
        """
        with self._lock:
            if not self._phone_found:
                return "NO PHONE", 0
            if self._last_send_ok is False:
                return "PHONE FAIL", self._consecutive_failures
            return "PHONE OK", 0

    def send_alert(self, alert_type, timestamp=None):
        payload = {
            "type": alert_type,
            "timestamp": timestamp or time.time(),
        }
        self._queue.put(("/alert", payload))

    def send_clear(self):
        payload = {"timestamp": time.time()}
        self._queue.put(("/clear", payload))

    def shutdown(self):
        self._running = False
        self._thread.join(timeout=2.0)
