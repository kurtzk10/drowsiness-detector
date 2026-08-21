import ipaddress
import json
import socket
import threading
import time

from config import PHONE_IP, PHONE_PORT


PHONE_DISCOVERY_PORT = 9876
DISCOVERY_TIMEOUT = 10.0


def _usable_address(value):
    """Return `value` as an IPv4Address, or None if it cannot be a real peer.

    Loopback and link-local (169.254.x) addresses are rejected: a phone on the
    hotspot never holds one, so a packet carrying one came from a bystander
    adapter — a VPN tunnel, a hypervisor host-only network, an unconfigured NIC
    — rather than the link the phone is actually on.
    """
    try:
        addr = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, ValueError):
        return None
    if (addr.is_loopback or addr.is_link_local
            or addr.is_unspecified or addr.is_multicast):
        return None
    return addr


def _local_ipv4_addresses():
    """Every IPv4 address this machine holds, so we can ignore our own packets.

    A broadcast sent from this PC comes back to a socket bound to 0.0.0.0, and
    without this guard the detector would happily "discover" itself and aim
    every alert at its own address.
    """
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except Exception:
        pass
    return found


def _get_local_ip(peer=None):
    """Get the PC's local IP address on the network where discovery runs.

    Routing through `peer` (the phone's address) picks the interface the
    phone can actually reach — the hotspot adapter. Connecting to a public
    address like 8.8.8.8 instead can select a different adapter when the
    laptop has several live networks (e.g. Ethernet + hotspot), and it fails
    on isolated hotspot links that have no internet route, leaving 127.0.0.1
    behind for the phone to try and connect to.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(peer or ("8.8.8.8", 80))
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

    The first peer that passes validation is locked in. Announcements are
    broadcasts, so on a multi-homed PC one can arrive from a VPN or hypervisor
    adapter moments after the real phone was found; letting the newest packet
    win would silently retarget every alert at an address the phone cannot
    receive on.
    """

    def __init__(self, on_phone_found=None):
        self._on_phone_found = on_phone_found
        self._running = False
        self._thread = None
        self._watchdog = None
        self._sock = None
        self._found_ip = None
        self._found_port = None
        self._pc_ip = None
        self._fallback_ip = PHONE_IP
        self._fallback_port = PHONE_PORT
        self._accept_lock = threading.Lock()
        self._reported = set()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        self._watchdog = threading.Thread(
            target=self._watchdog_timeout, daemon=True)
        self._watchdog.start()

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

    def _log_once(self, key, message):
        """Print `message` the first time `key` is seen.

        Announcements repeat every 2s, so an unfiltered warning would scroll
        the console faster than the detector's own output.
        """
        if key in self._reported:
            return
        self._reported.add(key)
        print(message)

    def _send_reply(self, addr):
        reply = json.dumps({
            "service": "drowsiness-alert-reply",
            "pc_ip": self._pc_ip,
        }).encode()
        try:
            self._sock.sendto(reply, addr)
        except Exception:
            pass

    def _listen(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_BROADCAST"):
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.settimeout(1.0)

        try:
            self._sock.bind(("0.0.0.0", PHONE_DISCOVERY_PORT))
        except OSError:
            print(f"[DISCOVERY] Could not bind to port {PHONE_DISCOVERY_PORT} — "
                  f"another copy of the detector may already be running.")
            return

        local_addresses = _local_ipv4_addresses()
        print(f"[DISCOVERY] Listening on UDP port {PHONE_DISCOVERY_PORT}...")

        while self._running:
            try:
                data, addr = self._sock.recvfrom(1024)
                message = json.loads(data.decode("utf-8"))
                if message.get("service") != "drowsiness-alert":
                    continue

                phone_ip = addr[0]
                phone_port = message.get("port", 5000)

                # Already locked on: keep answering re-broadcasts so a phone
                # that missed the first reply still learns the PC's address,
                # but never re-target and never re-fire the callback.
                if self._found_ip is not None:
                    if phone_ip == self._found_ip:
                        self._send_reply(addr)
                    else:
                        self._log_once(
                            f"ignored:{phone_ip}",
                            f"[DISCOVERY] Ignoring announcement from {phone_ip}"
                            f" — already locked to {self._found_ip}")
                    continue

                if phone_ip in local_addresses:
                    self._log_once(
                        f"self:{phone_ip}",
                        f"[DISCOVERY] Ignoring our own broadcast echoed back "
                        f"from {phone_ip}")
                    continue

                if _usable_address(phone_ip) is None:
                    self._log_once(
                        f"unusable:{phone_ip}",
                        f"[DISCOVERY] Ignoring announcement from {phone_ip} "
                        f"— not a reachable phone address")
                    continue

                pc_ip = _get_local_ip(peer=addr)
                if _usable_address(pc_ip) is None:
                    self._log_once(
                        f"noroute:{phone_ip}",
                        f"[DISCOVERY] Phone at {phone_ip} announced, but this "
                        f"PC has no usable route back to it (got {pc_ip})")
                    continue

                with self._accept_lock:
                    if self._found_ip is not None:
                        continue
                    self._found_ip = phone_ip
                    self._found_port = phone_port
                    self._pc_ip = pc_ip

                print(f"[DISCOVERY] Phone detected at {phone_ip}:{phone_port}, "
                      f"PC IP is {pc_ip}")
                self._send_reply(addr)

                if self._on_phone_found:
                    self._on_phone_found(phone_ip, phone_port)
            except socket.timeout:
                continue
            except json.JSONDecodeError:
                continue
            except Exception:
                continue

    def _watchdog_timeout(self):
        """If no phone announces itself within DISCOVERY_TIMEOUT seconds, fall
        back to PHONE_IP/PHONE_PORT from config.

        With no fallback configured there is nothing to fall back *to*, so say
        so loudly rather than leaving the HTTP client pointed at nothing — that
        failure mode looks exactly like a working system that never alerts.
        """
        deadline = time.monotonic() + DISCOVERY_TIMEOUT
        while self._running and time.monotonic() < deadline:
            if self._found_ip is not None:
                return
            time.sleep(0.2)
        if not self._running:
            return

        with self._accept_lock:
            if self._found_ip is not None:
                return
            if self._fallback_ip is None:
                print(f"[DISCOVERY] WARNING: no phone found in "
                      f"{DISCOVERY_TIMEOUT:.0f}s and PHONE_IP is not set in "
                      f"config.py — phone alerts are DISABLED this session.")
                print("[DISCOVERY]   Check that the phone app is running, that "
                      "this PC is on the phone's hotspot, and that UDP 9876 is "
                      "allowed through the firewall.")
                return
            self._found_ip = self._fallback_ip
            self._found_port = self._fallback_port

        print(f"[DISCOVERY] No phone found in {DISCOVERY_TIMEOUT:.0f}s — "
              f"falling back to PHONE_IP={self._fallback_ip}")
        if self._on_phone_found:
            self._on_phone_found(self._fallback_ip, self._fallback_port)

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
