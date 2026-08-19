import json
import socket
import threading


PHONE_DISCOVERY_PORT = 9876


def _get_local_ip():
    """Get the PC's local IP address on the network where discovery runs."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class PhoneDiscovery:
    """
    Listens for UDP broadcast packets from the Android app.
    When a phone announces itself, replies with the PC's IP
    and invokes the callback with (phone_ip, phone_port).
    """

    def __init__(self, on_phone_found=None):
        self._on_phone_found = on_phone_found
        self._running = False
        self._thread = None
        self._sock = None
        self._found_ip = None
        self._found_port = None
        self._pc_ip = None

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
        if hasattr(socket, "SO_BROADCAST"):
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.settimeout(1.0)

        try:
            self._sock.bind(("0.0.0.0", PHONE_DISCOVERY_PORT))
        except OSError:
            print("[DISCOVERY] Could not bind to port 9876")
            return

        print(f"[DISCOVERY] Listening on UDP port {PHONE_DISCOVERY_PORT}...")

        while self._running:
            try:
                data, addr = self._sock.recvfrom(1024)
                message = json.loads(data.decode("utf-8"))
                if message.get("service") == "drowsiness-alert":
                    phone_ip = addr[0]
                    phone_port = message.get("port", 5000)

                    if phone_ip != self._found_ip:
                        self._found_ip = phone_ip
                        self._found_port = phone_port
                        self._pc_ip = _get_local_ip()
                        print(f"[DISCOVERY] Phone detected at {phone_ip}:{phone_port}, "
                              f"PC IP is {self._pc_ip}")

                        reply = json.dumps({
                            "service": "drowsiness-alert-reply",
                            "pc_ip": self._pc_ip,
                        }).encode()

                        try:
                            self._sock.sendto(reply, addr)
                        except Exception:
                            pass

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
    def pc_ip(self):
        return self._pc_ip

    @property
    def found(self):
        return self._found_ip is not None
