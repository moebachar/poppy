#!/usr/bin/env python
"""Live annotated view of what the face tracker sees, streamed to a browser.

    python 09_face_view.py --camera 1
    then open  http://<pi-ip>:8080  on the laptop

Green boxes = detected faces; the overlay shows per-stage timing:
cap (grab a frame), det (find faces), loop (full cycle rate the tracker
would run at). No motors are touched — vision only.
"""
import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

latest = {"jpg": None}

YUNET = Path(__file__).parent / "face_detection_yunet_2023mar.onnx"
_yunet = None


def detect(small, cascade):
    """Return face boxes [(x, y, w, h), ...] on the small frame.

    Uses the YuNet neural detector when its model file is present (much more
    tolerant of angles and lighting); falls back to the Haar cascade.
    """
    global _yunet
    if YUNET.exists():
        if _yunet is None:
            _yunet = cv2.FaceDetectorYN.create(
                str(YUNET), "", (small.shape[1], small.shape[0]), 0.6)
        _yunet.setInputSize((small.shape[1], small.shape[0]))
        _, faces = _yunet.detect(small)
        if faces is None:
            return []
        return [tuple(int(v) for v in f[:4]) for f in faces]
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    return list(cascade.detectMultiScale(gray, 1.1, 3, minSize=(24, 24)))


def open_camera(preferred):
    """The USB camera renumbers itself on every reconnect — probe until found."""
    for idx in [preferred] + [i for i in range(4) if i != preferred]:
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        for _ in range(5):
            ok, _f = cap.read()
            if ok:
                print(f"camera opened at index {idx}", flush=True)
                return cap
        cap.release()
    raise SystemExit("no camera found on indexes 0-3")


def capture_loop(cam_index, cascade):
    cap = open_camera(cam_index)
    t_last = time.time()
    fails = 0
    while True:
        t0 = time.time()
        ok, frame = cap.read()
        t1 = time.time()
        if not ok:
            fails += 1
            if fails >= 20:            # ~camera fell off USB: re-hunt for it
                print("camera lost — reprobing...", flush=True)
                cap.release()
                time.sleep(2)
                try:
                    cap = open_camera(cam_index)
                except SystemExit:
                    continue
                fails = 0
            time.sleep(0.1)
            continue
        fails = 0
        small = cv2.resize(frame, (320, 240))          # detect at half size (speed)
        faces = detect(small, cascade)
        t2 = time.time()
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (2 * x, 2 * y), (2 * (x + w), 2 * (y + h)),
                          (0, 255, 0), 2)
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            ex = (2 * (x + w / 2) - 320) / 320.0
            ey = (2 * (y + h / 2) - 240) / 240.0
            cv2.putText(frame, f"ex={ex:+.2f} ey={ey:+.2f}", (8, 470),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
        hz = 1.0 / max(1e-6, time.time() - t_last)
        t_last = time.time()
        cv2.putText(frame,
                    f"cap {1000*(t1-t0):3.0f}ms  det {1000*(t2-t1):3.0f}ms  "
                    f"loop {hz:4.1f} Hz", (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
        ok2, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok2:
            latest["jpg"] = jpg.tobytes()


class Stream(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                buf = latest["jpg"]
                if buf is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                self.wfile.write(buf)
                self.wfile.write(b"\r\n")
                time.sleep(0.03)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--http-port", type=int, default=8080)
    args = ap.parse_args()
    local = Path(__file__).parent / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(
        str(local) if local.exists()
        else cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        raise SystemExit("haar cascade not found")
    threading.Thread(target=capture_loop, args=(args.camera, cascade),
                     daemon=True).start()
    print(f"streaming on http://0.0.0.0:{args.http_port} — Ctrl+C to stop",
          flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.http_port), Stream).serve_forever()


if __name__ == "__main__":
    main()
