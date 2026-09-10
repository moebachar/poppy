#!/usr/bin/env python
"""POPPY kiosk — the visitor's page, proxied to the deck (web/KIOSK.md).

    .venv\\Scripts\\python.exe web\\kiosk.py [--port 8080] [--deck http://127.0.0.1:8000] [--host 127.0.0.1]

Serves web/ui/dist/kiosk.html, forwards an allowlist of six REST calls to the
deck (web/server.py), keeps ONE websocket open to the deck and fans its frames
out to every browser on the table. Imports nothing from server.py: importing
it would wire a second voice supervisor and a second serial detector.
"""
import argparse
import asyncio
import json
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

HERE = Path(__file__).resolve().parent
DIST = HERE / "ui" / "dist"
PUBLIC = HERE / "ui" / "public"
ENTRY = "kiosk.html"
DECK_ENTRIES = ("index.html", "holo-harness.html")   # the deck's pages, not ours
LOGOS = ("lab-logo.png", "lab-logo.svg")

MAX_BODY = 4 * 1024              # the biggest honest body is {"on": false}
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
HTTP_PORT = 8080                 # the port we serve on; --port sets it
DECK = "http://127.0.0.1:8000"   # --deck sets it
GET_TIMEOUT = 10.0
POWER_TIMEOUT = 150.0            # power-on blocks until READY, up to 120 s
VOICE_OFF_TIMEOUT = 90.0         # voice-off blocks while the agent mines the
                                 # conversation for facts: up to 45 s + 20 s
                                 # (voicelink QUIT_TIMEOUT + MINING_GRACE)
POST_TIMEOUT = 10.0
BACKOFF = (1, 2, 5)              # then 5 s for ever
FORWARD = ("hello", "state", "pos", "health", "event", "voice", "lvl", "chat")
DOWN_MSG = "Poppy's deck is not running — start web/server.py"

# ---------------------------------------------------------------- runtime state
LOOP = None                      # asyncio loop, set at startup
HTTP = None                      # the one shared httpx.AsyncClient
UPSTREAM = None                  # the upstream socket task
DECK_UP = False                  # we hold the deck's state: its hello arrived
                                 # on the upstream socket and it is still open
LAST_STATE = None                # the deck's FullState as last seen on that
                                 # socket — every client's hello is cut from it
CLIENTS = set()                  # live downstream websockets
LVL_BUSY = set()                 # clients whose previous {"t":"lvl"} is still
                                 # in flight (loop thread only)
PENDING = {}                     # client -> frames held back until its own
                                 # hello has gone out (loop thread only)


class KioskError(Exception):
    """An error with an HTTP status; rendered as {"error": sentence}."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def ws_deck():
    """The deck's websocket URL from its HTTP one."""
    parts = urllib.parse.urlsplit(DECK)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urllib.parse.urlunsplit((scheme, parts.netloc, "/ws", "", ""))


# ------------------------------------------------------------------ ws fan-out
def broadcast(obj):
    """Send one message to every downstream client."""
    fan_out(json.dumps(obj), obj.get("t"))


def fan_out(payload, t):
    """One task per client — except for a client that is already behind.

    Copied from the deck: 'lvl' is the ONE message a slow client may miss
    (it is 30 Hz and the next one is 33 ms away). A suspended tablet leaves
    its socket open and zero-windowed, send_text never raises, and tasks
    would pile up until TCP gave up. Everything else is never dropped.
    """
    if LOOP is None or not CLIENTS:
        return
    droppable = t == "lvl"
    for ws in list(CLIENTS):
        held = PENDING.get(ws)
        if held is not None:
            # not greeted yet: anything that reaches it before its hello would
            # be overwritten by that hello. Hold it, in order; levels can wait
            # for the next one.
            if not droppable:
                held.append(payload)
            continue
        if droppable:
            if ws in LVL_BUSY:
                continue                             # still owes us one
            LVL_BUSY.add(ws)
        LOOP.create_task(_send_one(ws, payload, droppable))


async def _send_one(ws, payload, droppable):
    try:
        await ws.send_text(payload)
    except Exception:
        CLIENTS.discard(ws)
        try:
            await ws.close()             # discarding it is not enough: the
        except Exception:                # socket would linger with its buffers
            pass
    finally:
        if droppable:
            LVL_BUSY.discard(ws)


# ------------------------------------------------------------ upstream socket
def track_state(obj):
    """Keep LAST_STATE current from the frames that carry state.

    A client's hello is cut from this, on the loop, in the same step that
    adds the client to the fan-out — so nothing the deck says can slip in
    between "snapshot taken" and "client listening", in either direction.
    Asking the deck for GET /api/state instead used to leave exactly that
    window, and a browser opening mid power-on landed on a stale 'starting'.
    """
    global LAST_STATE
    t = obj.get("t")
    if t in ("hello", "state") and isinstance(obj.get("state"), dict):
        LAST_STATE = obj["state"]
    elif t == "voice" and LAST_STATE is not None and "voice" in obj:
        LAST_STATE = dict(LAST_STATE, voice=obj["voice"])


async def upstream_loop():
    """Keep ONE socket open to the deck, for ever; forward what it says."""
    global DECK_UP, LAST_STATE
    tries = 0
    while True:
        try:
            async with websockets.connect(ws_deck()) as ws:
                # websockets.connect sends no Origin, which the deck allows
                tries = 0
                async for raw in ws:
                    if not isinstance(raw, str):
                        continue
                    try:
                        obj = json.loads(raw)
                        t = obj.get("t")
                    except Exception:
                        continue                     # unparseable: drop it
                    if t not in FORWARD:
                        continue
                    track_state(obj)
                    # "up" means we hold the deck's state, not that a socket
                    # is open: the deck's hello is what makes it true, and it
                    # goes out ahead of that hello so every browser resyncs
                    if not DECK_UP and t == "hello":
                        DECK_UP = True
                        broadcast({"t": "deck", "up": True})
                    fan_out(raw, t)                  # verbatim, not re-encoded
        except asyncio.CancelledError:
            raise
        except Exception:
            pass                                     # refused, reset, closed
        LAST_STATE = None
        if DECK_UP:
            DECK_UP = False
            broadcast({"t": "deck", "up": False})
        await asyncio.sleep(BACKOFF[min(tries, len(BACKOFF) - 1)])
        tries += 1


# -------------------------------------------------------------------- the app
@asynccontextmanager
async def lifespan(_app):
    global LOOP, HTTP, UPSTREAM
    LOOP = asyncio.get_running_loop()
    HTTP = httpx.AsyncClient(base_url=DECK)
    UPSTREAM = asyncio.create_task(upstream_loop())
    yield
    UPSTREAM.cancel()
    try:
        await UPSTREAM
    except (asyncio.CancelledError, Exception):
        pass
    await HTTP.aclose()


app = FastAPI(title="POPPY kiosk", lifespan=lifespan)


@app.exception_handler(KioskError)
async def _kiosk_error(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=exc.code)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request, exc):
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)


def _split_host(value):
    """('host', port or None) from a Host header — IPv6 brackets included."""
    if not value:
        return None, None
    try:
        parts = urllib.parse.urlsplit("//" + value)
        return parts.hostname, parts.port
    except ValueError:
        return None, None


def own_origin(headers):
    """Did this request come from the kiosk itself? A copy of the deck's rule.

    No Origin header at all is ALLOWED — curl and scripts never send one and
    they are not the threat — while an Origin that IS present must be one of
    ours (127.0.0.1 / localhost / ::1 / the host this request was addressed
    to) on the port we are serving. Anything else, and anything we cannot
    parse, is refused: an Origin we do not understand is not ours.
    """
    origin = headers.get("origin")
    if origin is None:
        return True
    host, host_port = _split_host(headers.get("host"))
    try:
        parts = urllib.parse.urlsplit(origin)
        o_host, o_port = parts.hostname, parts.port
    except ValueError:
        return False                     # a port that is not a number, an
                                         # unclosed IPv6 bracket
    if parts.scheme not in ("http", "https") or not o_host:
        return False                     # "null" (a sandboxed frame, file://),
                                         # an extension, anything with no host
    if o_port is None:
        o_port = 443 if parts.scheme == "https" else 80
    # the port this request was actually addressed to is the authority;
    # HTTP_PORT only stands in when Host carries none
    if o_port != (host_port if host_port is not None else HTTP_PORT):
        return False
    if o_host in LOCAL_HOSTS:
        return True
    return host is not None and o_host == host


@app.middleware("http")
async def api_gate(request: Request, call_next):
    """Same-origin on writes, before routing — one rule in one place.

    Every POST here changes something real: the body moves, a paid voice
    session starts. A text/plain POST needs no preflight, so any page the
    visitor opens could fire them blind. GETs need no check: with no CORS
    headers on the answer, a page can send the request but never read it.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS") \
            and not own_origin(request.headers):
        return JSONResponse(
            {"error": "that request did not come from this kiosk"},
            status_code=403)
    return await call_next(request)


async def read_body(request):
    """The request's JSON object, refused before we buffer anything absurd."""
    too_big = f"that request body is too big — {MAX_BODY} bytes at most"
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY:
                raise KioskError(413, too_big)
        except ValueError:
            raise KioskError(400, "bad Content-Length")
    chunks, size = [], 0
    async for chunk in request.stream():   # a chunked body declares no length
        size += len(chunk)
        if size > MAX_BODY:
            raise KioskError(413, too_big)
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks).decode("utf-8"))
    except Exception:
        raise KioskError(400, "request body must be JSON")
    if not isinstance(body, dict):
        raise KioskError(400, "request body must be a JSON object")
    return body


# ------------------------------------------------------------------ REST proxy
async def deck_get(path):
    return await deck_call("GET", path, None, GET_TIMEOUT)


async def deck_call(method, path, body, timeout):
    """One call to the deck; its answer (status + JSON) passed back as-is.

    The body handed in was validated and rebuilt here — the raw request body
    and its headers never travel. Unreachable is 502, slow is 504.
    """
    try:
        r = await HTTP.request(method, path, json=body, timeout=timeout)
    except httpx.TimeoutException:
        raise KioskError(504, "Poppy's deck did not answer in time")
    except httpx.HTTPError:
        raise KioskError(502, DOWN_MSG)
    try:
        payload = r.json()
    except ValueError:
        payload = {"error": r.text[:200] or f"deck answered {r.status_code}"}
    return JSONResponse(payload, status_code=r.status_code)


def checked_on(body):
    on = body.get("on")
    if not isinstance(on, bool):
        raise KioskError(400, 'body must be {"on": true} or {"on": false}')
    return on


@app.get("/api/state")
async def api_state():
    return await deck_get("/api/state")


@app.get("/api/voice")
async def api_voice():
    return await deck_get("/api/voice")


@app.get("/api/voice/chat")
async def api_voice_chat():
    return await deck_get("/api/voice/chat")


@app.post("/api/power")
async def api_power(request: Request):
    on = checked_on(await read_body(request))
    return await deck_call("POST", "/api/power", {"on": on}, POWER_TIMEOUT)


@app.post("/api/cmd")
async def api_cmd(request: Request):
    body = await read_body(request)
    if body.get("cmd") != "hold":
        raise KioskError(400, 'body must be {"cmd": "hold"}')   # the only one
    return await deck_call("POST", "/api/cmd", {"cmd": "hold"}, POST_TIMEOUT)


@app.post("/api/voice")
async def api_voice_set(request: Request):
    on = checked_on(await read_body(request))
    # off is slow on purpose: the deck answers once the agent has said its
    # goodbye and mined the conversation, and a 504 in the middle of that is
    # a fault toast for a session that is ending normally
    timeout = POST_TIMEOUT if on else VOICE_OFF_TIMEOUT
    return await deck_call("POST", "/api/voice", {"on": on}, timeout)


@app.post("/api/voice/ptt")
async def api_voice_ptt(request: Request):
    """The kiosk's hold-to-talk bar. The deck answers 409 unless the live
    session is push-to-talk, and that sentence comes back as a toast."""
    down = (await read_body(request)).get("down")
    if not isinstance(down, bool):
        raise KioskError(400, 'body must be {"down": true} or {"down": false}')
    return await deck_call("POST", "/api/voice/ptt", {"down": down}, POST_TIMEOUT)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def api_other(path):
    """The allowlist IS the security model: nothing else exists on this port."""
    return JSONResponse({"error": "no such endpoint"}, status_code=404)


# ------------------------------------------------------------- ws downstream
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    # WebSockets are exempt from CORS and this pipe is read directly (every
    # chat row, names and words included), so it is origin-checked here —
    # BEFORE accept(), so nothing is ever sent to a stranger's page.
    if not own_origin(websocket.headers):
        await websocket.close(code=1008)   # policy violation
        return
    await websocket.accept()
    # One synchronous step, no await between these three lines: the client
    # starts listening, its frames are held, and its hello is cut from the
    # state we hold at that instant. Whatever the deck says from here on is
    # queued behind the hello, in order — never lost, never overtaken.
    held = []
    PENDING[websocket] = held
    CLIENTS.add(websocket)
    state = LAST_STATE if DECK_UP else None
    try:
        if state is None:
            await websocket.send_text(json.dumps({"t": "deck", "up": False}))
        else:
            await websocket.send_text(json.dumps({"t": "deck", "up": True}))
            await websocket.send_text(
                json.dumps({"t": "hello", "state": state}))
        # drain what arrived meanwhile; the sends yield, so keep draining
        # until a pass finds nothing — the pop right after has no await
        # before it, so nothing can be added and then left behind
        while held:
            batch = held[:]
            del held[:]
            for payload in batch:
                await websocket.send_text(payload)
        PENDING.pop(websocket, None)
        while True:
            await websocket.receive_text()   # client sends nothing; detect close
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        PENDING.pop(websocket, None)
        CLIENTS.discard(websocket)
        LVL_BUSY.discard(websocket)


# -------------------------------------------------------------------- static
@app.get("/{path:path}")
async def serve_ui(path):
    """Static web/ui/dist with kiosk.html fallback (SPA routing)."""
    if path == "ws" or path == "api" or path.startswith("api/"):
        return JSONResponse({"error": "no such endpoint"}, status_code=404)
    target = DIST / ENTRY
    if path in LOGOS and (PUBLIC / path).is_file():
        target = PUBLIC / path           # drop the lab's logo in: no rebuild
    elif path:
        cand = DIST / path
        try:
            rel = cand.resolve().relative_to(DIST.resolve())
            # judged on the RESOLVED name: NTFS answers /INDEX.HTML and
            # /./index.html with the deck's page just the same
            if rel.as_posix().lower() not in DECK_ENTRIES and cand.is_file():
                target = cand
        except (ValueError, OSError):
            pass
    if not target.is_file():
        return JSONResponse(
            {"error": "ui not built yet (web/ui/dist is missing)"},
            status_code=404)
    resp = FileResponse(target)
    if target.suffix == ".html":
        # never cache the entry page — stale bundles poisoned live sessions
        resp.headers["Cache-Control"] = "no-store"
    return resp


def main():
    global HTTP_PORT, DECK
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--deck", default=DECK, help="the deck's URL")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; 0.0.0.0 puts the kiosk on the lab network")
    args = ap.parse_args()
    HTTP_PORT = args.port            # own_origin() compares against this
    DECK = args.deck.rstrip("/")
    print(f"POPPY kiosk — deck {DECK} — http://{args.host}:{args.port}",
          flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
