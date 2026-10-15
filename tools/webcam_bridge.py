"""
Stream this laptop's webcam into the Docker container, and find the phone.

Docker Desktop on Windows and macOS cannot pass a webcam into a container,
and the phone's UDP discovery broadcast never reaches one. This runs on the
laptop itself and covers both:

  * reads the camera with OpenCV and serves it as an MJPEG stream the
    container opens like any network camera (/video);
  * answers the phone's discovery broadcast exactly as the native detector
    does, so the phone learns the laptop's address (its video feed and
    calibrate screen work), and tells the container which phone it found
    (/phone), so PHONE_IP never has to be typed in.

    pip install opencv-python
    python tools\\webcam_bridge.py                       # camera 0
    python tools\\webcam_bridge.py --source 1 --backend msmf

then, in another terminal:

    $env:CAMERA_SOURCE = "http://host.docker.internal:8554/video"
    docker compose --profile headless up

Pick --source/--backend the same way as CAMERA_SOURCE/CAMERA_BACKEND in
config.py; tools\\list_cameras.py shows which pair is which camera.
"""
import argparse
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "drowsiness_detector"))
from discovery import PhoneDiscovery, DISCOVERY_TIMEOUT   # noqa: E402

BACKENDS = {
    "any": cv2.CAP_ANY,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
}

_latest = None
_latest_lock = threading.Lock()
_new_frame = threading.Condition(_latest_lock)

_phone = {}          # {"ip": ..., "port": ...} once the phone announces itself


DETECTOR_PORT = 8080   # the container's MJPEG feed + calibrate endpoint


def _detector_up():
    try:
        socket.create_connection(("127.0.0.1", DETECTOR_PORT), timeout=0.3).close()
        return True
    except OSError:
        return False


class BridgeDiscovery(PhoneDiscovery):
    """The detector's own discovery, minus its 'alerts are DISABLED' warning:
    here the listener keeps running and the phone can still turn up later."""

    _waiting_logged = False

    def _send_reply(self, addr):
        # The phone opens its video feed once, the moment it learns the
        # laptop's address, and does not retry. Natively the reply comes from
        # the detector itself, so the feed is always up by then. Here the
        # bridge usually starts first: hold the reply until the container is
        # serving, or the phone tries too early and shows no video. The phone
        # re-announces every 2s, so it gets the reply as soon as it's ready.
        if _detector_up():
            BridgeDiscovery._waiting_logged = False
            super()._send_reply(addr)
        elif not BridgeDiscovery._waiting_logged:
            BridgeDiscovery._waiting_logged = True
            print(f"[BRIDGE] Phone found — waiting for the detector on port "
                  f"{DETECTOR_PORT} before telling it this laptop's address "
                  f"(start: docker compose --profile headless up)")

    def _watchdog_timeout(self):
        deadline = time.monotonic() + DISCOVERY_TIMEOUT
        while self._running and time.monotonic() < deadline:
            if self._found_ip is not None:
                return
            time.sleep(0.2)
        if self._running and self._found_ip is None:
            print(f"[BRIDGE] No phone yet after {DISCOVERY_TIMEOUT:.0f}s — still "
                  f"listening. Is the alert app open and this laptop on the "
                  f"phone's hotspot? Windows Firewall must allow Python on UDP 9876.")


def _phone_found(ip, port):
    _phone.update(ip=ip, port=port)


def open_source(source, backend):
    if backend == "auto":
        backend = "dshow" if sys.platform == "win32" and isinstance(source, int) else "any"
    cap = cv2.VideoCapture(source, BACKENDS[backend])
    if not cap.isOpened():
        return None, backend
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    # Webcams often return nothing for the first frames while the sensor
    # starts; give it a moment before deciding the camera is unusable.
    for _ in range(30):
        ok, _frame = cap.read()
        if ok:
            return cap, backend
        time.sleep(0.1)
    cap.release()
    return None, backend


def capture_loop(cap, quality, loop_file):
    global _latest
    while True:
        ok, frame = cap.read()
        if not ok:
            if loop_file:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            time.sleep(0.05)
            continue
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok:
            with _new_frame:
                _latest = jpeg.tobytes()
                _new_frame.notify_all()
        if loop_file:
            time.sleep(1 / 30)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/phone":
            body = json.dumps(_phone).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/video":
            self.send_error(404, "use /video or /phone")
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        print(f"[BRIDGE] Client connected: {self.client_address[0]}")
        try:
            while True:
                with _new_frame:
                    _new_frame.wait(timeout=2.0)
                    jpeg = _latest
                if jpeg is None:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                 b"Content-Length: " + str(len(jpeg)).encode() +
                                 b"\r\n\r\n" + jpeg + b"\r\n")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            print(f"[BRIDGE] Client disconnected: {self.client_address[0]}")

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="0",
                    help="camera index, or a video file to loop (default 0)")
    ap.add_argument("--backend", default="auto", choices=["auto", *BACKENDS],
                    help="capture backend for a camera index (default auto)")
    ap.add_argument("--port", type=int, default=8554)
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (default: this laptop only)")
    ap.add_argument("--quality", type=int, default=80, help="JPEG quality")
    ap.add_argument("--no-discovery", action="store_true",
                    help="don't answer the phone's discovery broadcast")
    args = ap.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source
    cap, backend = open_source(source, args.backend)
    if cap is None:
        sys.exit(f"[BRIDGE] Cannot read from {source!r} via {backend}. "
                 f"Try another --source/--backend; tools\\list_cameras.py "
                 f"shows which is which.")
    print(f"[BRIDGE] Camera {source!r} opened via {backend}")

    threading.Thread(target=capture_loop,
                     args=(cap, args.quality, not isinstance(source, int)),
                     daemon=True).start()

    discovery = None
    if not args.no_discovery:
        discovery = BridgeDiscovery(on_phone_found=_phone_found)
        discovery.start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[BRIDGE] Streaming on http://{args.host}:{args.port}/video")
    print(f"[BRIDGE] In Docker use CAMERA_SOURCE=http://host.docker.internal:{args.port}/video")
    print("[BRIDGE] Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if discovery is not None:
            discovery.stop()
        cap.release()
        print("[BRIDGE] Stopped.")


if __name__ == "__main__":
    main()
