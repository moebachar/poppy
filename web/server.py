#!/usr/bin/env python
"""POPPY/DECK bridge — FastAPI console server for the Poppy Torso.

    .venv\\Scripts\\python.exe web\\server.py [--robot-port COM7] [--http-port 8000]

Owns the lifecycle of scripts/motion/10_motion_server.py (spawned with
--telemetry), fans its stdout out to browsers over /ws, exposes the REST
surface from web/CONTRACT.md, and serves the built UI from web/ui/dist.
Never touches the serial port while the child is alive; the power-off-only
/api/scan opens it briefly and closes it.
"""
import argparse
import asyncio
import json
import re
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pypot.dynamixel
import serial.tools.list_ports
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MOTION = ROOT / "scripts" / "motion"
RECORDED = MOTION / "moves" / "recorded"
DIST = HERE / "ui" / "dist"

EXPECTED = {  # copied from scripts/motion/00_read_only.py
    33: "abs_z", 34: "bust_y", 35: "bust_x",
    36: "head_z", 37: "head_y",
    41: "l_shoulder_y", 42: "l_shoulder_x", 43: "l_arm_z", 44: "l_elbow_y",
    51: "r_shoulder_y", 52: "r_shoulder_x", 53: "r_arm_z", 54: "r_elbow_y",
}
SEAM_IDS = (41, 42, 44)          # multi-turn motors, see dxl_multiturn.py
NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
READY_TIMEOUT = 120
QUIT_TIMEOUT = 8

# ---------------------------------------------------------------- runtime state
STATE = {"power": "off", "port": None, "error": None,
         "playing": None, "recording": None}
FORCED_PORT = None               # set by --robot-port; disables re-detection
MOTORS = {i: {"id": i, "name": n, "model": "MX-28", "present": False,
              "ok": False, "pos": None, "temp": None, "volt": None}
          for i, n in EXPECTED.items()}
CHILD = None                     # subprocess.Popen of the motion server
LOOP = None                      # asyncio loop, set at startup
CLIENTS = set()                  # live websockets
READY_EVT = threading.Event()
BYE_EVT = threading.Event()
STATE_LOCK = threading.RLock()   # guards STATE / MOTORS / CHILD mutation
POWER_LOCK = threading.Lock()    # serializes power on/off and the offline scan
STDIN_LOCK = threading.Lock()    # one writer at a time on the child's stdin
PENDING_LOOSE = None             # loose map of the record_start in flight


class BridgeError(Exception):
    """An error with an HTTP status; rendered as {"error": sentence}."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def now_hms():
    return time.strftime("%H:%M:%S")


def venv_python():
    """The interpreter to spawn the motion server with."""
    for cand in (ROOT / ".venv" / "Scripts" / "python.exe",
                 ROOT / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def detect_port():
    """Best-guess the USB2AX serial port; never opens it."""
    ports = [p for p in serial.tools.list_ports.comports()
             if "bluetooth" not in (p.description or "").lower()]
    for p in ports:                                  # the USB2AX itself
        if p.vid == 0x16D0 and p.pid == 0x06A7:
            return p.device
    for p in ports:                                  # Linux: prefer ACM
        if p.device.startswith("/dev/ttyACM"):
            return p.device
    for p in ports:
        if "usb" in (p.description or "").lower():
            return p.device
    return None      # nothing USB-ish: better no port than a wrong one


def current_port():
    """Re-resolve on every use — the USB2AX drops off USB now and then."""
    STATE["port"] = FORCED_PORT or detect_port()
    return STATE["port"]


def list_moves():
    """Recorded moves as [{name, seconds, frames}], newest first."""
    rows = []
    try:
        paths = sorted(RECORDED.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return rows
    for p in paths:
        try:
            frames = json.loads(p.read_text())["frames"]
            secs = round(frames[-1]["t"] - frames[0]["t"], 1) if frames else 0.0
            rows.append({"name": p.stem, "seconds": secs, "frames": len(frames)})
        except Exception:
            continue                                 # unreadable file: skip
    return rows


def full_state():
    with STATE_LOCK:
        st = dict(STATE)
        st["motors"] = [dict(MOTORS[i]) for i in sorted(MOTORS)]
    st["moves"] = list_moves()
    return st


# ------------------------------------------------------------------ ws fan-out
def broadcast(obj):
    """Send one message to every websocket client (safe from any thread)."""
    if LOOP is None or not CLIENTS:
        return
    payload = json.dumps(obj)
    try:
        LOOP.call_soon_threadsafe(_fan_out, payload)
    except RuntimeError:
        pass                                         # loop already closed


def _fan_out(payload):
    for ws in list(CLIENTS):
        LOOP.create_task(_send_one(ws, payload))


async def _send_one(ws, payload):
    try:
        await ws.send_text(payload)
    except Exception:
        CLIENTS.discard(ws)


def set_phase(power, **extra):
    """Move the phase machine and broadcast the new FullState."""
    with STATE_LOCK:
        STATE["power"] = power
        for k, v in extra.items():
            STATE[k] = v
    broadcast({"t": "state", "state": full_state()})


# ---------------------------------------------------- child stdout: telemetry
def route_line(proc, line):
    """One child stdout line: telemetry updates state, the rest are events."""
    with STATE_LOCK:
        if CHILD is not proc:
            return                       # stale line from an old/killed child
    if line.startswith("POS "):
        pos = json.loads(line[4:])
        with STATE_LOCK:
            for k, v in pos.items():
                m = MOTORS.get(int(k))
                if m:
                    m["pos"] = v
        broadcast({"t": "pos", "pos": pos})
    elif line.startswith("HEALTH "):
        h = json.loads(line[7:])
        with STATE_LOCK:
            for k, d in h.get("motors", {}).items():
                m = MOTORS.get(int(k))
                if m:
                    m["temp"] = d.get("t")
                    m["volt"] = d.get("v")
        msg = {"t": "health"}
        msg.update(h)
        broadcast(msg)
    elif line.startswith("MOTORS "):
        present = set(json.loads(line[7:]).get("present", []))
        with STATE_LOCK:
            for i, m in MOTORS.items():
                m["present"] = m["ok"] = i in present
                if i not in present:
                    m["pos"] = m["temp"] = m["volt"] = None
    else:
        handle_event(line)


def handle_event(line):
    """Non-telemetry child line: forward verbatim, drive the phase machine."""
    global PENDING_LOOSE
    broadcast({"t": "event", "ts": now_hms(), "line": line})
    word = line.split(None, 1)[0]
    if word == "READY":
        set_phase("ready", playing=None)
        READY_EVT.set()
    elif word == "PLAY_START":
        parts = line.split()
        set_phase("playing", playing=parts[1] if len(parts) > 1 else None)
    elif word in ("PLAY_DONE", "PLAY_FAIL"):
        with STATE_LOCK:                 # a refusal ("PLAY_FAIL x recording")
            if STATE["power"] == "playing":  # must not flip other phases
                set_phase("ready", playing=None)
    elif word == "RECORD_START":
        with STATE_LOCK:
            loose = PENDING_LOOSE or {}
            PENDING_LOOSE = None
        set_phase("recording",
                  recording={"loose": loose, "started": now_hms()})
    elif word == "RECORD_FAIL":
        with STATE_LOCK:                 # child rejected the record_start
            PENDING_LOOSE = None
    elif word in ("RECORD_SAVED", "RECORD_ABORTED"):
        set_phase("ready", recording=None)
    elif word == "RELEASED":
        set_phase("released", playing=None, recording=None)
    elif word == "HOLDING":
        set_phase("ready")
    elif word == "TEMP_RELEASE":
        set_phase("cooling", playing=None, recording=None)
    elif word == "BYE":
        BYE_EVT.set()                    # phase flips to off on child exit
    elif word == "FATAL":
        set_phase("error", error=line)


def read_child(proc):
    """Reader thread: pump the child's stdout until EOF."""
    for raw in proc.stdout:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        try:
            route_line(proc, line)
        except Exception as e:
            broadcast({"t": "event", "ts": now_hms(),
                       "line": f"# bridge could not parse: {line!r} ({e})"})
    child_exited(proc)


def child_exited(proc):
    global CHILD
    with STATE_LOCK:
        if CHILD is not proc:
            return                       # stale reader from an older child
        CHILD = None
    BYE_EVT.set()
    # 'starting': power_on's own failure branch owns that transition
    if STATE["power"] not in ("off", "error", "starting"):
        set_phase("off", playing=None, recording=None)


# ------------------------------------------------------------ child lifecycle
def kill_child(proc):
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def power_on():
    """Spawn the motion server, block until READY (or fail loudly)."""
    global CHILD, PENDING_LOOSE
    with POWER_LOCK:
        if CHILD is not None and CHILD.poll() is None:
            return                       # already on: idempotent
        if not current_port():
            raise BridgeError(503, "no robot serial port found")
        READY_EVT.clear()
        BYE_EVT.clear()
        PENDING_LOOSE = None
        set_phase("starting", error=None, playing=None, recording=None)
        try:
            proc = subprocess.Popen(
                [venv_python(), "-u", str(MOTION / "10_motion_server.py"),
                 "--port", STATE["port"], "--telemetry"],
                cwd=str(MOTION), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1)
        except Exception as e:
            set_phase("error", error=f"could not spawn motion server: {e}")
            raise BridgeError(500, STATE["error"])
        with STATE_LOCK:
            CHILD = proc
        threading.Thread(target=read_child, args=(proc,), daemon=True).start()
        t0 = time.time()
        while time.time() - t0 < READY_TIMEOUT:
            if READY_EVT.wait(0.5):
                return
            if proc.poll() is not None:
                break                    # child died before READY
        if READY_EVT.is_set():
            return
        code = proc.poll()               # capture before kill_child masks it
        kill_child(proc)
        if STATE["power"] != "error":    # FATAL already set a better message
            if code is not None:
                set_phase("error", error=f"motion server exited (code {code}) "
                                         "before READY")
            else:
                set_phase("error", error="motion server did not reach READY "
                                         f"within {READY_TIMEOUT}s")
        raise BridgeError(500, STATE["error"] or "motion server failed")


def power_off():
    """Graceful quit (wait for BYE), then terminate. Idempotent."""
    global CHILD
    with POWER_LOCK:
        proc = CHILD
        if proc is None or proc.poll() is not None:
            if STATE["power"] != "off":
                set_phase("off", error=None, playing=None, recording=None)
            return
        BYE_EVT.clear()
        with STDIN_LOCK:
            try:
                proc.stdin.write("stop\n")   # abort a running play out-of-band
                proc.stdin.write("quit\n")   # ...so the quit gets processed
                proc.stdin.flush()
            except Exception:
                pass
        BYE_EVT.wait(QUIT_TIMEOUT)
        try:
            proc.wait(timeout=2)
        except Exception:
            kill_child(proc)
        with STATE_LOCK:
            if CHILD is proc:
                CHILD = None
        if STATE["power"] != "off":
            set_phase("off", error=None, playing=None, recording=None)


def send_line(line):
    """Write one command line to the child; 409 when the power is off."""
    proc = CHILD
    if proc is None or proc.poll() is not None:
        raise BridgeError(409, "power is off")
    with STDIN_LOCK:
        try:
            proc.stdin.write(line + "\n")
            proc.stdin.flush()
        except Exception as e:
            raise BridgeError(500, f"motion server unreachable: {e}")


# ----------------------------------------------------------- offline bus scan
ADDR_PRESENT = 36


def _read_reg(dxl, mid, addr, length=2):
    """Raw register read (mirrors dxl_multiturn.read_reg)."""
    sp = dxl._send_packet(dxl._protocol.DxlReadDataPacket(mid, addr, length))
    if sp is None:
        raise IOError(f"no answer from id {mid} reading addr {addr}")
    p = sp.parameters
    return (p[0] | (p[1] << 8)) if length == 2 else p[0]


def present_deg(dxl, mid):
    """Continuous multi-turn present position in raw degrees (dxl_multiturn)."""
    r = _read_reg(dxl, mid, ADDR_PRESENT)
    if r > 32767:
        r -= 65536
    return r * 360.0 / 4095.0 - 180.0


def do_scan():
    """Power-off bus survey: open the port briefly, ping every expected id."""
    with POWER_LOCK:
        if CHILD is not None and CHILD.poll() is None:
            raise BridgeError(409, "scan needs the power off")
        port = current_port()
        if not port:
            raise BridgeError(503, "no robot serial port found")
        try:
            dxl = pypot.dynamixel.DxlIO(port, baudrate=1_000_000)
        except Exception as e:
            raise BridgeError(500, f"could not open {port}: {e}")
        data = {}
        try:
            for mid in EXPECTED:
                for _ in range(3):               # one try + 2 retries
                    try:
                        if dxl.ping(mid):
                            data[mid] = {}
                            break
                    except Exception:
                        pass
            alive = sorted(data)
            if alive:
                try:
                    for i, t in zip(alive, dxl.get_present_temperature(alive)):
                        data[i]["temp"] = int(t)
                except Exception:
                    pass
                try:
                    for i, v in zip(alive, dxl.get_present_voltage(alive)):
                        data[i]["volt"] = round(float(v), 1)
                except Exception:
                    pass
                try:
                    for i, m in zip(alive, dxl.get_model(alive)):
                        data[i]["model"] = str(m)
                except Exception:
                    pass
                plain = [i for i in alive if i not in SEAM_IDS]
                if plain:
                    try:
                        for i, p in zip(plain, dxl.get_present_position(plain)):
                            data[i]["pos"] = round(float(p), 1)
                    except Exception:
                        pass
                for i in alive:
                    if i in SEAM_IDS:
                        try:
                            data[i]["pos"] = round(present_deg(dxl, i), 1)
                        except Exception:
                            pass
        finally:
            dxl.close()                          # release the port fast
    with STATE_LOCK:
        for i, m in MOTORS.items():
            m["present"] = m["ok"] = i in data
            if i in data:
                for k in ("pos", "temp", "volt", "model"):
                    if k in data[i]:
                        m[k] = data[i][k]
            else:
                m["pos"] = m["temp"] = m["volt"] = None


# -------------------------------------------------------------------- the app
@asynccontextmanager
async def lifespan(_app):
    global LOOP
    LOOP = asyncio.get_running_loop()
    yield
    await asyncio.to_thread(power_off)


app = FastAPI(title="POPPY/DECK bridge", lifespan=lifespan)


@app.exception_handler(BridgeError)
async def _bridge_error(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=exc.code)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request, exc):
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)


async def read_body(request):
    try:
        body = await request.json()
    except Exception:
        raise BridgeError(400, "request body must be JSON")
    if not isinstance(body, dict):
        raise BridgeError(400, "request body must be a JSON object")
    return body


def require_ready():
    if STATE["power"] != "ready":
        raise BridgeError(409, f"robot is {STATE['power']}, not ready")


def checked_name(body):
    name = body.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise BridgeError(400, "name must match [a-z0-9_-]{1,32}")
    return name


@app.get("/api/state")
async def api_state():
    return full_state()


@app.post("/api/power")
async def api_power(request: Request):
    body = await read_body(request)
    on = body.get("on")
    if not isinstance(on, bool):
        raise BridgeError(400, 'body must be {"on": true} or {"on": false}')
    await asyncio.to_thread(power_on if on else power_off)
    return full_state()


@app.post("/api/cmd")
async def api_cmd(request: Request):
    body = await read_body(request)
    cmd = body.get("cmd")
    if cmd not in ("hold", "release", "look", "stop"):
        raise BridgeError(400, "cmd must be hold, release, look or stop")
    send_line(cmd)
    return full_state()


@app.post("/api/play")
async def api_play(request: Request):
    name = checked_name(await read_body(request))
    require_ready()
    send_line(f"play {name}")
    return full_state()


@app.post("/api/record/start")
async def api_record_start(request: Request):
    global PENDING_LOOSE
    body = await read_body(request)
    loose = body.get("loose")
    if not isinstance(loose, dict) or not loose:
        raise BridgeError(400, 'body must be {"loose": {"41": 20, ...}}')
    clean = {}
    for k, v in loose.items():
        try:
            mid = int(k)
        except (TypeError, ValueError):
            raise BridgeError(400, f"bad motor id {k!r}")
        if mid not in EXPECTED:
            raise BridgeError(400, f"unknown motor id {mid}")
        if not isinstance(v, (int, float)) or isinstance(v, bool) \
                or not 0 <= v <= 100:
            raise BridgeError(400, f"torque for motor {mid} must be 0-100")
        clean[str(mid)] = v
    require_ready()
    with STATE_LOCK:
        if PENDING_LOOSE is not None:
            raise BridgeError(409, "record start already in flight")
        PENDING_LOOSE = clean
    try:
        send_line("record_start " + json.dumps(clean, separators=(",", ":")))
    except BridgeError:
        with STATE_LOCK:                 # never sent: nothing is in flight
            PENDING_LOOSE = None
        raise
    return full_state()


@app.post("/api/record/stop")
async def api_record_stop(request: Request):
    name = checked_name(await read_body(request))
    send_line(f"record_stop {name}")
    return full_state()


@app.post("/api/record/abort")
async def api_record_abort():
    send_line("record_abort")
    return full_state()


@app.get("/api/moves")
async def api_moves():
    return list_moves()


@app.post("/api/scan")
async def api_scan():
    if STATE["power"] != "off" or (CHILD is not None and CHILD.poll() is None):
        raise BridgeError(409, "scan only works with the power off")
    await asyncio.to_thread(do_scan)
    broadcast({"t": "state", "state": full_state()})
    return full_state()


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    CLIENTS.add(websocket)
    try:
        await websocket.send_text(
            json.dumps({"t": "hello", "state": full_state()}))
        while True:
            await websocket.receive_text()   # client sends nothing; detect close
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        CLIENTS.discard(websocket)


@app.get("/{path:path}")
async def serve_ui(path):
    """Static web/ui/dist with index.html fallback (SPA routing)."""
    if path == "ws" or path == "api" or path.startswith("api/"):
        return JSONResponse({"error": "no such endpoint"}, status_code=404)
    target = DIST / "index.html"
    if path:
        cand = DIST / path
        try:
            cand.resolve().relative_to(DIST.resolve())
            if cand.is_file():
                target = cand
        except (ValueError, OSError):
            pass
    if not target.is_file():
        return JSONResponse(
            {"error": "ui not built yet (web/ui/dist is missing)"},
            status_code=404)
    resp = FileResponse(target)
    if target.suffix == ".html":
        # never cache the entry pages — stale bundles poisoned live sessions
        resp.headers["Cache-Control"] = "no-store"
    return resp


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot-port",
                    help="serial port of the USB2AX (default: auto-detect)")
    ap.add_argument("--http-port", type=int, default=8000)
    args = ap.parse_args()
    global FORCED_PORT
    FORCED_PORT = args.robot_port
    current_port()
    print(f"POPPY/DECK bridge — robot port {STATE['port'] or 'NOT FOUND'} — "
          f"http://127.0.0.1:{args.http_port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.http_port, log_level="warning")


if __name__ == "__main__":
    main()
