import threading
import json
import time
from queue import Queue, Empty

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
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def update_phone(self, ip, port=5000):
        with self._lock:
            self._base_url = f"http://{ip}:{port}"

    def _worker(self):
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
            except Empty:
                continue

            endpoint, payload = item
            with self._lock:
                url = f"{self._base_url}{endpoint}"
            try:
                if requests is not None:
                    requests.post(
                        url,
                        json=payload,
                        timeout=1.0,
                        headers={"Connection": "close"},
                    )
            except requests.exceptions.Timeout:
                pass
            except requests.exceptions.ConnectionError:
                pass
            except Exception:
                pass

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
