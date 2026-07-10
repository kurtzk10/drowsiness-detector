import json
import socket
import threading
import struct


PHONE_DISCOVERY_PORT = 9876


class PhoneDiscovery:
    """
    Listens for UDP broadcast packets from the Android app.
    When a phone announces itself, the callback is invoked with (ip, port).
    """

    def __init__(self, on_phone_found=None):
        self._on_phone_found = on_phone_found
        self._running = False
        self._thread = None
        self._sock = None
        self._found_ip = None
        self._found_port = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _listen(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Allow receiving broadcast messages
        if hasattr(socket, "SO_BROADCAST"):
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.settimeout(1.0)

        try:
            self._sock.bind(("0.0.0.0", PHONE_DISCOVERY_PORT))
        except OSError:
            print("[DISCOVERY] Could not bind to port 9876 — try running as admin or choose another port")
            return

        print(f"[DISCOVERY] Listening for phone broadcasts on UDP port {PHONE_DISCOVERY_PORT}...")

        while self._running:
            try:
                data, addr = self._sock.recvfrom(1024)
                message = json.loads(data.decode("utf-8"))
                if message.get("service") == "drowsiness-alert":
                    phone_ip = addr[0]
                    phone_port = message.get("port", 5000)
                    self._found_ip = phone_ip
                    self._found_port = phone_port
                    print(f"[DISCOVERY] Phone detected at {phone_ip}:{phone_port}")
                    if self._on_phone_found:
                        self._on_phone_found(phone_ip, phone_port)
            except socket.timeout:
                continue
            except json.JSONDecodeError:
                continue
            except Exception:
                continue

    @property
    def phone_ip(self):
        return self._found_ip

    @property
    def phone_port(self):
        return self._found_port

    @property
    def found(self):
        return self._found_ip is not None
