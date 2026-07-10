import io
import json
import select
import socket
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

STREAMER_PORT = 8080
MJPEG_BOUNDARY = b"FRAME_BOUNDARY"
MJPEG_HEADER = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: multipart/x-mixed-replace; boundary=FRAME_BOUNDARY\r\n"
    b"Cache-Control: no-cache\r\n"
    b"Connection: keep-alive\r\n"
    b"\r\n"
)
MJPEG_PREFIX = b"--FRAME_BOUNDARY\r\nContent-Type: image/jpeg\r\nContent-Length: "
MJPEG_SUFFIX = b"\r\n\r\n"


class _Handler(BaseHTTPRequestHandler):
    streamer = None

    def do_GET(self):
        if self.path == "/video_feed":
            self._serve_mjpeg()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/calibrate":
            self._serve_calibrate()
        else:
            self.send_error(404)

    def _serve_mjpeg(self):
        self.wfile.write(MJPEG_HEADER)
        while self.streamer and self.streamer._running:
            jpeg = self.streamer.get_jpeg()
            if jpeg is not None:
                try:
                    self.wfile.write(MJPEG_PREFIX)
                    self.wfile.write(str(len(jpeg)).encode())
                    self.wfile.write(MJPEG_SUFFIX)
                    self.wfile.write(jpeg)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    break
            time.sleep(0.1)

    def _serve_calibrate(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length:
            self.rfile.read(content_length)
        if self.streamer:
            result = self.streamer.request_calibration()
            if result:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            else:
                self.send_error(500, "Calibration failed")
        else:
            self.send_error(500)

    def log_message(self, fmt, *args):
        pass


class Streamer:
    def __init__(self, port=STREAMER_PORT):
        self.port = port
        self._running = False
        self._server = None
        self._thread = None
        self._jpeg = None
        self._jpeg_lock = threading.Lock()

        self._cal_request = threading.Event()
        self._cal_done = threading.Event()
        self._cal_result = None
        self._cal_lock = threading.Lock()

    def start(self):
        self._running = True
        _Handler.streamer = self
        self._server = ThreadingHTTPServer(("0.0.0.0", self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[STREAMER] MJPEG server on port {self.port}")

    def stop(self):
        self._running = False
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=3.0)

    def push_jpeg(self, jpeg_bytes):
        with self._jpeg_lock:
            self._jpeg = jpeg_bytes

    def get_jpeg(self):
        with self._jpeg_lock:
            return self._jpeg

    def request_calibration(self):
        self._cal_request.set()
        self._cal_done.clear()
        success = self._cal_done.wait(timeout=20.0)
        with self._cal_lock:
            return self._cal_result if success else None

    def complete_calibration(self, result):
        with self._cal_lock:
            self._cal_result = result
        self._cal_done.set()
        self._cal_request.clear()

    def calibration_pending(self):
        return self._cal_request.is_set()
