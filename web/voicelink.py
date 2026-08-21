#!/usr/bin/env python
r"""Poppy Live supervisor — the bridge side of the '@' line protocol.

Owns perception/live_agent.py --deck: spawns it, reads its '@' lines, answers
its move requests through the motion server the BRIDGE owns (the agent never
touches the serial port), keeps the last 80 chat rows for a browser reload,
and serves the people / guided-enrolment REST surface.

web/server.py wires this module once at import time and delegates the new
routes into it; this module never imports server.py back. See web/VOICE.md §2.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PREFS_PATH = HERE / "voice_prefs.json"

VOICES = ("alloy", "ash", "ballad", "cedar", "coral", "echo", "marin",
          "sage", "shimmer", "verse")
MODELS = ("gpt-realtime-2.1", "gpt-realtime-2.1-mini")
VADS = ("semantic", "server")
DUPLEXES = ("full", "gate", "ptt")
PHASES = ("connecting", "listening", "hearing", "thinking", "speaking")
PREF_KEYS = ("voice", "model", "vad", "fx", "nudge", "duplex", "identify",
             "input", "output")
DEFAULTS = {"voice": "cedar", "model": "gpt-realtime-2.1", "vad": "semantic",
            "fx": 0.25, "nudge": 0, "duplex": "full", "identify": True,
            "input": None, "output": None}

CHAT_MAX = 80
# @quit -> @bye. The child's shutdown ends with identity.extract_facts, which
# sits on a urlopen(timeout=25); killing it there loses the mined memories for
# good. It prints "mining the conversation..." first, and that line buys the
# grace on top — so the long wait only happens when there is something to lose.
QUIT_TIMEOUT = 45
MINING_GRACE = 20
HOLD_TIMEOUT = 25            # released -> ready before a move can play
PLAY_TIMEOUT = 60            # the move itself, travel back to the stance
# The bridge's worst case for one @move is HOLD_TIMEOUT + PLAY_TIMEOUT plus the
# 0.2 s / 0.25 s poll overshoot ~= 85.5 s. That MUST stay under DeckMotion's
# 90 s ceiling in perception/live_agent.py: the bridge always answers first, so
# the agent's timeout only ever fires when the deck itself has gone away.
BAD_LINE_QUIET = 5           # seconds between "could not parse" complaints
LOAD_TIMEOUT = 240           # enrolment stuck 'loading': torch + an 80 MB pull
RECORD_STALE = 40            # enrolment stuck 'recording': 8 s of mic + slack
ENROLL_SECONDS = 8.0
MIC_RATE = 24000             # identity.MIC_RATE — the rate voiceprints expect
LVL_HZ = 30
STAMP_RE = re.compile(r"^[0-9]{8}-[0-9]{6}\.jsonl$")
TOKEN_RE = re.compile(r"^[0-9]+$")      # the @move correlation token

# ---------------------------------------------------------------- wiring ----
_broadcast = None            # server.broadcast — thread-safe fan-out
_send_motion = None          # server.send_line — one line to the motion server
_power = None                # () -> server STATE["power"]
_python = None               # () -> interpreter to spawn the agent with

# ------------------------------------------------------------------ state ----
_LOCK = threading.RLock()    # guards _STATE / _PREFS / _CHAT / _CHILD
_STDIN_LOCK = threading.Lock()      # one writer at a time on the child's stdin
_SESSION_LOCK = threading.Lock()    # serializes start / stop
_MOVE_LOCK = threading.Lock()       # one move RPC at a time
_ENROLL_LOCK = threading.RLock()    # guards the guided enrolment
_PEOPLE_LOCK = threading.Lock()     # one writer at a time in perception/people
# The motion bus has exactly ONE arbiter and this is it. _BUS_LOCK is held for
# a few statements at a time and NEVER while a server function is called, so it
# can never invert against server.STATE_LOCK — voicelink takes no server lock.
_BUS_LOCK = threading.Lock()

_STATE = {"on": False, "phase": "off", "error": None, "started": None,
          "people": None, "moves": None, "resp": None}
_PREFS = dict(DEFAULTS)
_CHILD = None                # subprocess.Popen of live_agent.py --deck
_STOPPING = False            # a stop() we asked for: not an error on exit
_BYE = threading.Event()
_MINING = threading.Event()  # he said he is mining the transcript on the way
_TAIL = deque(maxlen=6)      # last plain child lines — the death message
_CHAT = deque(maxlen=CHAT_MAX)
_ROW_N = 0
_BAD = {"n": 0, "at": 0.0}   # malformed child lines: counted, rarely spoken
_BUS = None                  # the play that owns the motion bus right now
_LIVE_DUPLEX = None          # what the RUNNING child was launched with
_ENROLL = None               # guided-enrolment session, as sent to the deck
_ENROLL_AT = 0.0             # when its current status began — staleness clock
_GEN = 0                     # enrolment generation — a clip that comes back
                             # under an older one is somebody else's voice
_SAVING = False              # enroll_finish is writing: nothing else may touch
_EMBEDDER = None             # identity.Embedder for that enrolment
_CLIPS = []                  # embeddings collected so far
_IDENT = None                # perception/identity.py, imported on demand


class VoiceError(Exception):
    """An error with an HTTP status; rendered as {"error": sentence}."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def wire(broadcast, send_motion, power, python, root):
    """Called once by server.py: hand us the bridge's own plumbing."""
    global _broadcast, _send_motion, _power, _python, ROOT
    _broadcast = broadcast
    _send_motion = send_motion
    _power = power
    _python = python
    ROOT = Path(root)
    _load_prefs()


# ------------------------------------------------------------------ helpers --
def _hms():
    return time.strftime("%H:%M:%S")


def _emit(obj):
    if _broadcast is not None:
        _broadcast(obj)


def _event(line):
    """Into the deck's event log, verbatim behind a recognisable prefix."""
    _emit({"t": "event", "ts": _hms(), "line": line})


def _push_voice():
    _emit({"t": "voice", "voice": voice_state()})


def _alive():
    p = _CHILD
    return p is not None and p.poll() is None


def _require_on():
    if not _alive():
        raise VoiceError(409, "no voice session is running")


def _people_dir():
    return ROOT / "perception" / "people"


def _sessions_dir():
    return _people_dir() / "_sessions"


def _count_people():
    try:
        return len(list(_people_dir().glob("*.json")))
    except OSError:
        return 0


def _count_moves():
    try:
        return len([p for p in
                    (ROOT / "scripts" / "motion" / "moves" / "recorded")
                    .glob("*.json") if not p.stem.startswith("_")])
    except OSError:
        return 0


def _api_key():
    """Same rule as live_agent.load_config: .env at the repo root wins.

    The key itself never leaves this function — only whether there is one.
    """
    key = None
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "OPENAI_API_KEY":
                    key = v.strip().strip("'").strip('"')
    except OSError:
        pass
    return key or os.environ.get("OPENAI_API_KEY")


def _identity():
    """perception/identity.py, imported on demand (it pulls numpy in)."""
    global _IDENT
    if _IDENT is None:
        path = str(ROOT / "perception")
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            import identity
        except Exception as e:
            raise VoiceError(503, f"the identity module will not load: {e}")
        _IDENT = identity
    return _IDENT


def _unit(v):
    """A level clamped to 0..1. Anything else is 0.0.

    A string or a NaN from a malformed '@lvl' would reach the aura's shader as
    a NaN uniform and collapse its shell for the rest of the session.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0.0
    v = float(v)
    if v != v:                            # NaN compares unequal to itself
        return 0.0
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _bands(v):
    """Exactly 8 levels: a short list reaches the shader as undefined."""
    if not isinstance(v, list) or len(v) != 8:
        return [0.0] * 8
    return [_unit(x) for x in v]


def _count(v):
    """A non-negative whole number, or None — types.ts promises a number."""
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        return None
    return v


def _checked_person(name):
    """A person's name: any script, but one clean line of it."""
    if not isinstance(name, str):
        raise VoiceError(400, "name must be text")
    name = " ".join(name.split())        # also kills the newlines that would
    if not name or len(name) > 40:       # break the '@' line protocol
        raise VoiceError(400, "name must be 1-40 characters")
    return name


# ------------------------------------------------------------- preferences --
def _number(v, lo, hi, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise VoiceError(400, f"{what} must be a number")
    if not lo <= v <= hi:
        raise VoiceError(400, f"{what} must be between {lo:g} and {hi:g}")
    return float(v)


def _validate_prefs(body):
    """Only the preference keys present in the body, every one checked."""
    out = {}
    for k in PREF_KEYS:
        if k not in body:
            continue
        v = body[k]
        if k == "voice":
            if v not in VOICES:
                raise VoiceError(400, "voice must be one of " + ", ".join(VOICES))
        elif k == "model":
            if v not in MODELS:
                raise VoiceError(400, "model must be " + " or ".join(MODELS))
        elif k == "vad":
            if v not in VADS:
                raise VoiceError(400, 'vad must be "semantic" or "server"')
        elif k == "duplex":
            if v not in DUPLEXES:
                raise VoiceError(400, 'duplex must be "full", "gate" or "ptt"')
        elif k == "fx":
            v = round(_number(v, 0.0, 1.0, "fx"), 3)
        elif k == "nudge":
            v = _number(v, 0.0, 600.0, "nudge")
            v = int(v) if v.is_integer() else round(v, 1)
        elif k == "identify":
            if not isinstance(v, bool):
                raise VoiceError(400, "identify must be true or false")
        elif v is not None:              # input / output: a device index
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise VoiceError(400, f"{k} must be null or a device index")
        out[k] = v
    return out


def _load_prefs():
    """web/voice_prefs.json over the defaults, one key at a time.

    Per key so a single hand-edited mistake cannot wipe the whole file.
    """
    global _PREFS
    prefs = dict(DEFAULTS)
    try:
        doc = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except Exception:
        doc = {}
    if isinstance(doc, dict):
        for k, v in doc.items():
            try:
                prefs.update(_validate_prefs({k: v}))
            except VoiceError:
                continue
    with _LOCK:
        _PREFS = prefs


def _save_prefs():
    with _LOCK:
        doc = dict(_PREFS)
    try:
        PREFS_PATH.write_text(json.dumps(doc, indent=1, ensure_ascii=False),
                              encoding="utf-8")
    except OSError as e:
        _event(f"[voice] could not save the preferences: {e}")


# ------------------------------------------------------------------- state ---
def voice_state():
    """VoiceState — preferences included, running or not (VOICE.md §2.1)."""
    with _LOCK:
        st = dict(_STATE)
        prefs = dict(_PREFS)
    with _ENROLL_LOCK:
        enroll = dict(_ENROLL) if _ENROLL else None
    return {"on": st["on"], "phase": st["phase"], "error": st["error"],
            "started": st["started"],
            "voice": prefs["voice"], "model": prefs["model"],
            "vad": prefs["vad"], "fx": prefs["fx"], "nudge": prefs["nudge"],
            "duplex": prefs["duplex"], "identify": prefs["identify"],
            "input": prefs["input"], "output": prefs["output"],
            "people": st["people"] if st["people"] is not None
            else _count_people(),
            "moves": st["moves"] if st["moves"] is not None else _count_moves(),
            "resp": st["resp"], "enroll": enroll}


def _chat(kind, text, who=None, score=None, verdict=None, ok=None):
    """One transcript row, kept for a reload and pushed to the open decks."""
    global _ROW_N
    with _LOCK:
        _ROW_N += 1
        row = {"n": _ROW_N, "ts": _hms(), "kind": kind, "who": who,
               "text": text, "score": score, "verdict": verdict, "ok": ok}
        _CHAT.append(row)
    _emit({"t": "chat", "row": row})


def _note(text, who=None):
    _chat("note", text, who=who)


def chat_rows():
    with _LOCK:
        return {"rows": list(_CHAT)}


# --------------------------------------------------- child stdout: '@' lines --
def _read_child(proc):
    """Reader thread: pump the agent's stdout (stderr is merged in) to EOF."""
    for raw in proc.stdout:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        try:
            _route(proc, line)
        except Exception as e:
            _parse_failed(line, e)
    _child_exited(proc)


def _parse_failed(line, e):
    """Complain about a malformed child line at most once every few seconds.

    '@lvl' arrives 30 times a second: one bad line used to broadcast an event
    (and a store write) 30x/s for the rest of the session, which is the exact
    re-render storm VOICE.md 4.1 exists to prevent.
    """
    now = time.time()
    _BAD["n"] += 1
    if now - _BAD["at"] < BAD_LINE_QUIET:
        return
    _BAD["at"] = now
    more = f" — {_BAD['n']} bad lines so far" if _BAD["n"] > 1 else ""
    _event(f"[voice] bridge could not parse: {line!r} ({e}){more}")


def _route(proc, line):
    """One line from the agent. '@' lines are protocol, the rest is news."""
    global _LIVE_DUPLEX
    if _CHILD is not proc:
        return                            # stale line from a killed child
    if not line.startswith("@"):
        _TAIL.append(line)
        if "mining the conversation" in line:
            _MINING.set()                 # stop() gives him the extra grace
        _event("[voice] " + line)
        return
    verb, _, rest = line.partition(" ")
    verb, rest = verb[1:], rest.strip()

    if verb == "lvl":                     # 30 Hz: cheapest branch first
        try:
            d = json.loads(rest)
        except ValueError:
            return
        if not isinstance(d, dict):       # a bare list/number would make .get
            return                        # raise 30 times a second
        _emit({"t": "lvl", "o": _unit(d.get("o")), "i": _unit(d.get("i")),
               "b": _bands(d.get("b"))})
        return
    if verb == "move":
        # "@move <token> <name>" — the token correlates the answer, so a late
        # reply to a request that already timed out cannot resolve the next one
        bits = rest.split()
        token = bits[0] if bits and TOKEN_RE.match(bits[0]) else None
        if token is None:
            # we echo the token we were given and never invent one, so a move
            # line without one is unanswerable: say so instead of replying
            _event(f"[voice] ignoring a move with no token: {line!r}")
            return
        # on a worker: the reply can take a minute and the reader must keep
        # draining stdout or the agent blocks on its own 30 Hz levels
        threading.Thread(target=_serve_move,
                         args=(proc, token, bits[1] if len(bits) > 1 else ""),
                         daemon=True).start()
        return
    if verb == "stopmove":
        _motion("stop")
        return
    if verb == "look":
        _motion("look")
        return
    if verb == "bye":
        _BYE.set()
        return

    payload = {}
    if rest:
        try:
            payload = json.loads(rest)
        except ValueError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}

    if verb == "phase":
        p = payload.get("p")
        if p in PHASES:
            with _LOCK:
                # 'starting' holds until @ready (VOICE.md 2.1); after that the
                # child owns the phase — 'connecting' means a RECONNECT
                if _STATE["phase"] == "starting":
                    return
                _STATE["phase"] = p
            _push_voice()
    elif verb == "ready":
        duplex = payload.get("duplex")
        _LIVE_DUPLEX = duplex if duplex in DUPLEXES else None
        with _LOCK:
            # None falls back to counting the files, which beats sending the
            # deck a string where it renders a number
            _STATE["people"] = _count(payload.get("people"))
            _STATE["moves"] = _count(payload.get("moves"))
            if _STATE["phase"] == "starting":
                _STATE["phase"] = "listening"
        _push_voice()
    elif verb == "say":
        _chat("say", str(payload.get("text") or ""), who="poppy")
    elif verb == "heard":
        _chat("heard", str(payload.get("text") or ""),
              who=payload.get("who"), score=payload.get("score"),
              verdict=payload.get("verdict"))
    elif verb == "tool":
        ph = payload.get("phase")
        _chat("tool", str(payload.get("name") or "?"),
              ok=True if ph == "done" else False if ph == "fail" else None)
        detail = str(payload.get("detail") or "").strip()
        if ph == "fail" and detail:
            _note(detail)      # the row carries the verdict, the note the WHY
    elif verb == "person":
        name = payload.get("name")
        _note(str(payload.get("detail") or
                  f"{payload.get('event') or 'noted'} {name}"), who=name)
        _emit({"t": "people"})            # the roster just changed
    elif verb == "prof":
        avg, n = payload.get("resp"), payload.get("n")
        # the panel prints avg to two decimals: half a @prof must stay null
        if isinstance(avg, (int, float)) and not isinstance(avg, bool) \
                and isinstance(n, int) and not isinstance(n, bool):
            with _LOCK:
                _STATE["resp"] = {"avg": round(float(avg), 3), "n": n}
            _push_voice()
    elif verb == "err":
        m = str(payload.get("m") or "")
        _note(m)
        _event("[voice] " + m)


def _child_exited(proc):
    """The agent is gone: release any move RPC, then say why."""
    global _CHILD
    with _LOCK:
        if _CHILD is not proc:
            return                        # stale reader from an older child
        _CHILD = None
    _bus_fail("voice", "fail the voice session ended")
    if _STOPPING or _BYE.is_set():
        _note("session ended")
        _off_state()
        return
    why = _TAIL[-1] if _TAIL else f"the voice agent stopped (exit {proc.poll()})"
    with _LOCK:
        _STATE.update(on=False, phase="error", error=why, started=None,
                      people=None, moves=None)
    _note("session ended — " + why)
    _push_voice()


def _off_state():
    with _LOCK:
        if not _STATE["on"] and _STATE["phase"] == "off":
            return
        _STATE.update(on=False, phase="off", error=None, started=None,
                      people=None, moves=None, resp=None)
    _push_voice()


def _write(proc, line):
    """One line to the agent's stdin; False when the pipe is gone."""
    if proc is None or proc.poll() is not None:
        return False
    with _STDIN_LOCK:
        try:
            proc.stdin.write(line + "\n")
            proc.stdin.flush()
            return True
        except Exception:
            return False


# --------------------------------------------------------------- @move RPC ---
def _motion(line):
    """One line to the motion server; False when the power is off."""
    if _send_motion is None:
        return False
    try:
        _send_motion(line)
        return True
    except Exception:
        return False                      # BridgeError: power off / pipe gone


# ---- the motion bus: one claim per play, deck's and model's alike ----------
# Correlating on the move NAME alone was not enough: the deck's POST /api/play
# and a model move landing in the same millisecond both saw power=="ready" (it
# only flips on PLAY_START coming back), both sent "play wave", and the first
# PLAY_DONE answered the wrong one. Every play now takes this claim first, so
# each completion line belongs to exactly one request.
def _bus_claim(who, name, seconds):
    """Take the motion bus, or None when a play already owns it."""
    global _BUS
    with _BUS_LOCK:
        held = _BUS
        if held is not None:
            if time.time() < held["expires"]:
                return None
            # the motion server never answered this one: release its waiter
            # rather than wedge the bus until the next power cycle
            if held["result"] is None:
                held["result"] = "fail the move never finished"
                held["done"].set()
        _BUS = {"who": who, "name": name, "done": threading.Event(),
                "result": None, "expires": time.time() + seconds}
        return _BUS


def _bus_release(claim):
    global _BUS
    with _BUS_LOCK:
        if _BUS is claim:
            _BUS = None


def _bus_fail(who, reason):
    """Answer whatever `who` has on the bus — the body will never finish it."""
    global _BUS
    with _BUS_LOCK:
        claim = _BUS
        if claim is None or (who is not None and claim["who"] != who):
            return
        if claim["result"] is None:
            claim["result"] = reason
            claim["done"].set()
        if claim["who"] == "deck":        # nobody waits to release a deck play
            _BUS = None


def claim_motion(name):
    """server.api_play: take the bus for a deck-initiated play.

    -> a claim, or None when a move already owns the bus. Fire-and-forget for
    the UI: it is released by the PLAY_DONE/PLAY_FAIL that answers it, by
    on_motion_exit(), or by its own deadline.
    """
    return _bus_claim("deck", name, PLAY_TIMEOUT)


def release_motion(claim):
    """server.api_play: the 'play' line never went out after all."""
    _bus_release(claim)


def on_motion_exit():
    """server.child_exited: the motion server is gone, mid-move or not.

    Without this the RPC waits out the whole PLAY_TIMEOUT — a minute of dead
    air with an unanswered function_call and POWER OFF on the deck.
    """
    _bus_fail(None, "fail the robot went off mid-move")


def on_motion_event(word, line):
    """Every non-telemetry motion-server line, from server.handle_event."""
    global _BUS
    if word not in ("PLAY_DONE", "PLAY_FAIL"):
        return
    parts = line.split(None, 2)
    name = parts[1] if len(parts) > 1 else ""
    with _BUS_LOCK:
        claim = _BUS
        if claim is None or claim["result"] is not None:
            return
        if name and name != claim["name"]:
            return                        # a stale line from an expired play
        if word == "PLAY_DONE":
            claim["result"] = "ok"
        else:
            claim["result"] = "fail " + (parts[2] if len(parts) > 2
                                         else "it failed")
        claim["done"].set()
        if claim["who"] == "deck":        # nobody is waiting to release it
            _BUS = None


def _wait_ready(proc, seconds):
    """Wait for the body to reach 'ready'; give up if the agent dies."""
    t0 = time.time()
    while time.time() - t0 < seconds:
        power = _power() if _power else "off"
        if power == "ready":
            return True
        if power in ("off", "error") or proc.poll() is not None:
            return False
        time.sleep(0.2)
    return (_power() if _power else "off") == "ready"


def _wait(evt, seconds, proc):
    """Wait on an event, cutting it short if the agent or the BODY dies.

    The move runs in the motion server, not in the agent: when that child dies
    there is no completion line at all, and polling only the (perfectly
    healthy) agent burned the whole PLAY_TIMEOUT as dead air.
    """
    t0 = time.time()
    while time.time() - t0 < seconds:
        if evt.wait(0.25):
            return True
        if proc.poll() is not None:
            return False
        if (_power() if _power else "off") in ("off", "error"):
            return False
    return evt.is_set()


def _serve_move(proc, token, name):
    """Answer one '@move <token> <name>' — ALWAYS, or the agent hangs 90 s."""
    if not name:
        _write(proc, f"@move_result {token} fail no move name")
        return
    if not _MOVE_LOCK.acquire(blocking=False):
        _write(proc, f"@move_result {token} fail already moving")
        return
    try:
        verdict = _run_move(proc, name)
    except Exception as e:
        verdict = f"fail the bridge could not play it ({e})"
    finally:
        _MOVE_LOCK.release()
    # one line, always: a reason carrying a newline would reach the agent as
    # half a protocol line and the other half as noise
    verdict = " ".join(verdict.split())
    _write(proc, f"@move_result {token} {verdict}")
    if verdict != "ok":
        _event(f"[voice] move '{name}' refused — {verdict[5:]}")


def _run_move(proc, name):
    """-> 'ok' or 'fail <reason the model can say out loud>'."""
    power = _power() if _power else "off"
    if power == "recording":
        return "fail he is being taught a move right now"
    if power == "playing":
        return "fail already moving"
    if power == "cooling":
        # the motion watchdog released him at >=52 C. 'hold' here would stiffen
        # all 13 motors and travel to the stance WHILE HOT, and the in-move
        # watchdog would just release him again: the cool-down is not the
        # model's to cancel. 'released' below is an operator decision, so it is.
        return "fail he is too hot right now — the body is cooling down"
    # the claim covers the stand-up too: the body is busy for all of it
    claim = _bus_claim("voice", name, HOLD_TIMEOUT + PLAY_TIMEOUT)
    if claim is None:
        return "fail already moving"
    try:
        if power == "released":
            # a loose body cannot play: stand it up first, then let it settle
            if not _motion("hold"):
                return "fail robot is off"
            if not _wait_ready(proc, HOLD_TIMEOUT):
                return "fail he could not stand up in time"
        elif power != "ready":
            return "fail robot is off"    # off / starting / error / unknown
        if not _motion(f"play {name}"):
            return "fail robot is off"
        if not _wait(claim["done"], PLAY_TIMEOUT, proc):
            if (_power() if _power else "off") in ("off", "error"):
                return "fail the robot went off mid-move"
            return "fail the move never finished"
        return claim["result"] or "fail the move never finished"
    finally:
        _bus_release(claim)


# ------------------------------------------------------------ child lifecycle -
def _agent_args():
    """live_agent.py flags for the current preferences (see its argparse)."""
    with _LOCK:
        p = dict(_PREFS)
    args = ["--deck", "--model", p["model"], "--voice", p["voice"],
            "--vad", p["vad"], "--robot-fx", str(p["fx"])]
    if p["duplex"] == "gate":
        args.append("--gate")
    elif p["duplex"] == "ptt":
        args.append("--ptt")
    if p["nudge"]:
        args += ["--nudge", str(p["nudge"])]
    if not p["identify"]:
        args.append("--no-id")
    if p["input"] is not None:
        args += ["--input-device", str(p["input"])]
    if p["output"] is not None:
        args += ["--output-device", str(p["output"])]
    return args


def start():
    """Spawn the agent. 409 when it is already up, 503 without a key."""
    global _CHILD, _STOPPING, _ROW_N, _LIVE_DUPLEX
    with _SESSION_LOCK:
        if _alive():
            raise VoiceError(409, "a voice session is already running")
        busy = _enroll_blocking()
        if busy:
            raise VoiceError(409, busy)
        agent = ROOT / "perception" / "live_agent.py"
        if not agent.is_file():
            raise VoiceError(500, "perception/live_agent.py is missing")
        if not _api_key():
            raise VoiceError(503, "OPENAI_API_KEY is missing — put it in .env "
                                  "at the repo root")
        with _LOCK:
            _CHAT.clear()                 # a session starts with a clean panel
            _ROW_N = 0
            _STATE.update(on=True, phase="starting", error=None,
                          started=_hms(), people=None, moves=None, resp=None)
        _TAIL.clear()
        _BYE.clear()
        _MINING.clear()
        _BAD.update(n=0, at=0.0)
        _STOPPING = False
        _LIVE_DUPLEX = None
        interp = _python() if _python else sys.executable
        try:
            proc = subprocess.Popen(
                [interp, "-u", str(agent)] + _agent_args(),
                cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1)
        except Exception as e:
            with _LOCK:
                _STATE.update(on=False, phase="error",
                              error=f"could not start the voice agent: {e}")
            _push_voice()
            raise VoiceError(500, f"could not start the voice agent: {e}")
        with _LOCK:
            _CHILD = proc
        threading.Thread(target=_read_child, args=(proc,), daemon=True).start()
        _push_voice()


def stop():
    """@quit, wait for @bye, then terminate. Idempotent; used at shutdown."""
    global _CHILD, _STOPPING
    with _SESSION_LOCK:
        proc = _CHILD
        if proc is None or proc.poll() is not None:
            _off_state()
            return
        _STOPPING = True
        _BYE.clear()
        _write(proc, "@interrupt")        # stop him mid-sentence, then leave
        _write(proc, "@quit")
        _BYE.wait(QUIT_TIMEOUT)           # he mines the transcript before @bye
        if not _BYE.is_set() and _MINING.is_set():
            # he printed "mining the conversation...": that is a 25 s urlopen
            # in flight and killing it now throws the new memories away
            _BYE.wait(MINING_GRACE)
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        with _LOCK:
            if _CHILD is proc:
                _CHILD = None
        _off_state()


# ------------------------------------------------------------------- REST ----
def set_voice(body):
    """POST /api/voice — persist the preferences, then start or stop."""
    on = body.get("on")
    if on is not None and not isinstance(on, bool):
        raise VoiceError(400, 'the "on" field must be true or false')
    if on is True and _alive():
        raise VoiceError(409, "a voice session is already running")
    prefs = _validate_prefs(body)
    if prefs:
        with _LOCK:
            _PREFS.update(prefs)
        _save_prefs()
    if on is True:
        start()
    elif on is False:
        stop()
    elif prefs:
        _push_voice()                     # config-only write: echo it back
    return voice_state()


def command(body):
    """POST /api/voice/cmd — interrupt him, or make him say something."""
    cmd = body.get("cmd")
    if cmd not in ("interrupt", "nudge"):
        raise VoiceError(400, 'cmd must be "interrupt" or "nudge"')
    _require_on()
    # a 200 here used to mean "the pipe accepted it", not "we wrote it"
    if not _write(_CHILD, "@" + cmd):
        raise VoiceError(409, "the voice session is closing — it did not take "
                              f"the {cmd}")
    return voice_state()


def ptt(body):
    """POST /api/voice/ptt — the browser's push-to-talk button."""
    down = body.get("down")
    if not isinstance(down, bool):
        raise VoiceError(400, 'body must be {"down": true} or {"down": false}')
    _require_on()
    # what the RUNNING agent was launched with, not what the panel now says
    if (_LIVE_DUPLEX or _PREFS["duplex"]) != "ptt":
        raise VoiceError(409, "this session is not in push-to-talk")
    if not _write(_CHILD, "@ptt " + ("down" if down else "up")):
        raise VoiceError(409, "the voice session is closing — it did not take "
                              "the button")
    return voice_state()


def tag(body):
    """POST /api/voice/tag — enrol whoever just spoke, without interrupting."""
    name = _checked_person(body.get("name"))
    _require_on()
    # the deck closes its name field on a 200: it must mean the name landed
    if not _write(_CHILD, f"@enroll {name}"):
        raise VoiceError(409, "the voice session is closing — the name was not "
                              "tagged")
    return voice_state()


# ----------------------------------------------------------------- people ----
def _model_state(ident):
    d = ident.MODELS_DIR / "spkrec-ecapa-voxceleb"
    try:
        return "cached" if any(d.iterdir()) else "missing"
    except OSError:
        return "missing"


def _facts(d):
    """[(raw index, rendered row)] for every fact the deck actually shows.

    people_list() and people_fact_delete() MUST agree on which entries count:
    the deck deletes by position in the list it was sent, so one non-object in
    a hand-edited file would shift every index after it and delete the wrong
    fact. One function, one rule.
    """
    rows = []
    raw = d.get("facts")
    if isinstance(raw, list):
        for i, f in enumerate(raw):
            # every string stays a string: a file missing a key would
            # otherwise send null where the deck renders text
            if isinstance(f, dict):
                rows.append((i, {"t": str(f.get("t") or ""),
                                 "text": str(f.get("text") or "")}))
    return rows


def people_list():
    """GET /api/people — read the files fresh, newest encounter first."""
    ident = _identity()
    people = ident.People()               # deliberately a fresh read: the deck
    rows = []                             # edits land in the agent next session
    for slug, d in people.people.items():
        facts = [row for _, row in _facts(d)]
        rows.append({"name": d.get("name") or slug, "slug": slug,
                     "prints": len(d.get("voiceprints") or []),
                     "adaptive": len(d.get("adaptive_prints") or []),
                     "encounters": d.get("encounters") or 0,
                     "created": str(d.get("created") or ""),
                     "last_seen": str(d.get("last_seen") or ""),
                     "facts": facts})
    rows.sort(key=lambda r: r["last_seen"] or "", reverse=True)
    return {"people": rows, "model": _model_state(ident), "voice_on": _alive()}


def _person(people, name):
    d = people.get(name)
    if d is None:
        raise VoiceError(404, f"Poppy does not know anyone called '{name}'")
    return d


def people_fact(body):
    """POST /api/people/fact — one more thing Poppy remembers about them."""
    ident = _identity()
    name = _checked_person(body.get("name"))
    fact = body.get("fact")
    if not isinstance(fact, str) or not fact.strip():
        raise VoiceError(400, "fact must be text")
    if len(fact) > 300:
        raise VoiceError(400, "a fact is 300 characters at most")
    with _PEOPLE_LOCK:                    # read-modify-write: one at a time
        people = ident.People()
        d = _person(people, name)
        clean = [dict(row) for _, row in _facts(d)]
        if d.get("facts") != clean:
            # identity.remember() re-reads the file, then subscripts
            # d["facts"] and reads f["text"] on every entry: a person file
            # with no 'facts' key (or junk in the list) came back as a bare
            # KeyError 500 instead of the {"error": sentence} shape. Repair it
            # ON DISK first, to exactly what the deck was shown (_facts()).
            d["facts"] = clean
            people._save(ident._slug(name))
        people.remember(name, fact)
    _emit({"t": "people"})
    return people_list()


def people_fact_delete(body):
    """POST /api/people/fact/delete — facts are cheap, no confirmation."""
    ident = _identity()
    name = _checked_person(body.get("name"))
    index = body.get("index")
    if isinstance(index, bool) or not isinstance(index, int):
        raise VoiceError(400, "index must be a whole number")
    with _PEOPLE_LOCK:
        people = ident.People()
        d = _person(people, name)
        rows = _facts(d)                  # the SAME list the deck indexed into
        if not 0 <= index < len(rows):
            raise VoiceError(404, "no fact at that index")
        d["facts"].pop(rows[index][0])
        people._save(ident._slug(name))   # identity owns the file format
    _emit({"t": "people"})
    return people_list()


def people_rename(body):
    """POST /api/people/rename — same voiceprints, new name (and new slug)."""
    ident = _identity()
    src = _checked_person(body.get("from"))
    dst = _checked_person(body.get("to"))
    with _PEOPLE_LOCK:                    # two renames onto one name used to
        people = ident.People()           # both pass and delete a person
        src_slug, dst_slug = ident._slug(src), ident._slug(dst)
        if src_slug not in people.people:
            raise VoiceError(404, f"Poppy does not know anyone called '{src}'")
        # on DISK, not in the snapshot: People() skips a file it cannot parse,
        # and overwriting a merely unreadable person is not a rename
        if dst_slug != src_slug and \
                (ident.PEOPLE_DIR / (dst_slug + ".json")).exists():
            raise VoiceError(409, f"someone is already called '{dst}'")
        d = people.people.pop(src_slug)
        d["name"] = dst
        people.people[dst_slug] = d
        people._save(dst_slug)
        if dst_slug != src_slug:
            (ident.PEOPLE_DIR / (src_slug + ".json")).unlink(missing_ok=True)
    _emit({"t": "people"})
    return people_list()


def people_forget(body):
    """POST /api/people/forget — deletes the person file, prints and all."""
    ident = _identity()
    name = _checked_person(body.get("name"))
    with _PEOPLE_LOCK:
        people = ident.People()
        if not people.forget(name):
            raise VoiceError(404, f"Poppy does not know anyone called '{name}'")
    _emit({"t": "people"})
    return people_list()


# -------------------------------------------------------- guided enrolment ---
def _enroll_set(**kw):
    """Update the enrolment and restart its staleness clock (lock held)."""
    global _ENROLL_AT
    _ENROLL.update(**kw)
    _ENROLL_AT = time.time()


def _enroll_blocking():
    """The sentence to refuse with while an enrolment owns the mic, else None.

    'an enrolment is using the microphone' never said WHAT was wrong, and a
    'loading' whose worker died (no torch, no network) held the microphone for
    ever with no way out but restarting the bridge — so a status that has sat
    far past its own budget no longer counts as owning anything.
    """
    with _ENROLL_LOCK:
        if _ENROLL is None or (_ENROLL["status"] == "done" and not _SAVING):
            return None
        status, name, saving = _ENROLL["status"], _ENROLL["name"], _SAVING
        age = time.time() - _ENROLL_AT
    if status == "loading":
        if age > LOAD_TIMEOUT:
            return None                   # abandoned: torch never came up
        return (f"the enrolment for {name} is still loading the voice model — "
                f"cancel it to free the microphone")
    if status == "recording":
        if age > RECORD_STALE:
            return None                   # abandoned: the clip never returned
        return (f"the enrolment for {name} is recording — wait for it or "
                f"cancel it")
    if saving:
        return f"the enrolment for {name} is being saved — a moment"
    return (f"the enrolment for {name} still has the microphone — save or "
            f"cancel it")


def enroll_start(body):
    """POST /api/people/enroll/start — 4 prompts on the laptop mic."""
    global _ENROLL, _EMBEDDER, _CLIPS, _GEN
    name = _checked_person(body.get("name"))
    ident = _identity()
    with _ENROLL_LOCK:                    # RLock: _enroll_blocking re-enters
        busy = _enroll_blocking()
        if busy:
            raise VoiceError(409, busy)
        if _alive():
            raise VoiceError(409, "the voice session is using the microphone — "
                                  "stop it first")
        try:
            import sounddevice                      # noqa: F401
        except Exception as e:
            raise VoiceError(503, f"no microphone available: {e}")
        # a new generation: an 8 s clip still running for the PREVIOUS person
        # used to land in this one's list and hand Poppy the wrong voice
        _GEN += 1
        gen = _GEN
        _EMBEDDER = ident.Embedder()
        _CLIPS = []
        _ENROLL = {}
        _enroll_set(name=name, step=0, of=len(ident.ENROLL_PROMPTS),
                    status="loading", prompt=ident.ENROLL_PROMPTS[0],
                    note=None, clips=0)
        emb = _EMBEDDER
    # torch + speechbrain take seconds, and ~80 MB on the very first run
    threading.Thread(target=_load_embedder, args=(emb, gen),
                     daemon=True).start()
    _push_voice()
    return voice_state()


def _load_embedder(emb, gen):
    try:
        emb.load_sync()
        status, note = "ready", None
    except Exception as e:
        # nothing to record into: end the flow with the reason in plain words
        status, note = "done", f"the voice model did not load — {e}"
    with _ENROLL_LOCK:
        if _ENROLL is None or _GEN != gen or _EMBEDDER is not emb:
            return                        # cancelled while we were loading
        _enroll_set(status=status, note=note)
    _push_voice()


def _record_clip():
    """8 s from the mic, streaming the envelope to the deck at 30 Hz."""
    import numpy as np
    import sounddevice as sd
    blocks = []
    live = {"i": 0.0}

    def cb(indata, frames, t, status):    # keep this cheap: no FFT, no I/O
        block = indata.copy().reshape(-1)
        blocks.append(block)
        x = block.astype(np.float32) / 32768.0
        live["i"] = float(np.sqrt(float((x * x).mean()))) if x.size else 0.0

    with _LOCK:
        device = _PREFS["input"]
    stream = sd.InputStream(samplerate=MIC_RATE, channels=1, dtype="int16",
                            blocksize=MIC_RATE // LVL_HZ, device=device,
                            callback=cb)
    end = time.time() + ENROLL_SECONDS
    with stream:
        while time.time() < end:
            time.sleep(1.0 / LVL_HZ)
            _emit({"t": "lvl", "o": 0.0,
                   "i": round(min(1.0, live["i"] / 0.18), 3),
                   "b": [0.0] * 8})       # same scaling as the agent's levels
    _emit({"t": "lvl", "o": 0.0, "i": 0.0, "b": [0.0] * 8})
    if not blocks:
        raise RuntimeError("the microphone returned no audio")
    return np.concatenate(blocks)


def _short(e):
    """An exception as one clean line the deck can print."""
    return " ".join(f"{e}".split()) or type(e).__name__


def _enroll_back(gen, note):
    """Put OUR generation back on 'ready' with a reason. Never a wedge."""
    with _ENROLL_LOCK:
        if _ENROLL is not None and _GEN == gen:
            _enroll_set(status="ready", note=note)
    _push_voice()


def enroll_record():
    """POST /api/people/enroll/record — one 8 s clip; weak ones do not count."""
    import numpy as np
    ident = _identity()
    with _ENROLL_LOCK:
        if _ENROLL is None:
            raise VoiceError(409, "no enrolment is running")
        if _alive():
            raise VoiceError(409, "the voice session is using the microphone — "
                                  "stop it first")
        status = _ENROLL["status"]
        if status == "loading":
            raise VoiceError(409, "the voice model is still loading")
        if status == "recording":
            raise VoiceError(409, "already recording")
        if status == "done":
            raise VoiceError(409, "this enrolment is finished")
        if _SAVING:                       # finish() is writing the file
            raise VoiceError(409, "this enrolment is being saved")
        if _ENROLL["step"] >= _ENROLL["of"]:
            raise VoiceError(409, "that is enough clips — save it")
        emb = _EMBEDDER
        if emb is None or not emb.ready:
            # embed() on a model of None raises AttributeError, which used to
            # escape as a bare 500 and leave the status on 'recording' — every
            # later record and start then 409'd and the deck was wedged
            raise VoiceError(409, "the voice model is not loaded")
        gen = _GEN
        _enroll_set(status="recording", note=None)
    _push_voice()
    try:
        pcm = _record_clip()
    except Exception as e:
        why = f"the microphone is not available — {_short(e)}"
        _enroll_back(gen, why)
        raise VoiceError(503, why)        # unplugged device: not a bridge bug
    try:
        level = float(np.abs(pcm.astype(np.float32)).mean())
        voiced = (len(ident.speech_only(pcm, ident.MIC_RATE))
                  / float(ident.MIC_RATE))
        note = None
        if level < 40:
            note = "that was almost silence — do it again"
        elif voiced < 2.0:
            note = (f"only {voiced:.1f} s of actual speech in there — "
                    f"do it again")
        vec = None if note else emb.embed(pcm, ident.MIC_RATE)
    except Exception as e:
        why = f"the clip could not be processed — {_short(e)}"
        _enroll_back(gen, why)
        raise VoiceError(500, why)
    with _ENROLL_LOCK:
        # the clip took 8 s outside the lock: it belongs to the enrolment that
        # asked for it and to no other, whatever happened meanwhile
        if _ENROLL is None or _GEN != gen:
            return voice_state()          # cancelled while the clip ran
        if vec is not None:
            _CLIPS.append(vec)
            _ENROLL["step"] += 1
            _ENROLL["clips"] = len(_CLIPS)
        _enroll_set(status="ready", note=note,
                    prompt=ident.ENROLL_PROMPTS[
                        min(_ENROLL["step"], _ENROLL["of"] - 1)])
    _push_voice()
    return voice_state()


def enroll_finish():
    """POST /api/people/enroll/finish — write the voiceprints. Idempotent."""
    global _SAVING
    import numpy as np
    ident = _identity()
    with _ENROLL_LOCK:
        if _ENROLL is None:
            raise VoiceError(409, "no enrolment is running")
        # a second SAVE click (or a UI retry of a slow POST) used to enrol the
        # same clips twice: 8 identical prints, the centroid dragged onto them
        # and MAX_ENROLLED evicting the genuinely diverse older ones
        if _ENROLL["status"] == "done":
            return voice_state()
        if _SAVING:
            raise VoiceError(409, "this enrolment is already being saved")
        if _ENROLL["status"] == "recording":
            raise VoiceError(409, "still recording")
        if len(_CLIPS) < 2:
            raise VoiceError(409, "record at least two clips first")
        # claim the flow BEFORE the slow write: a record arriving during it
        # would otherwise pass and overwrite the 'done' we are about to set
        _SAVING = True
        gen, name, clips = _GEN, _ENROLL["name"], list(_CLIPS)
    try:
        sims = [float(np.dot(clips[i], clips[j]))
                for i in range(len(clips)) for j in range(i + 1, len(clips))]
        with _PEOPLE_LOCK:                # serialised with every other write
            ident.People().enroll(name, clips)
    except Exception as e:
        with _ENROLL_LOCK:
            _SAVING = False
        why = f"the voiceprints could not be saved — {_short(e)}"
        _enroll_back(gen, why)            # still recordable: he can retry
        raise VoiceError(500, why)
    note = f"saved — self-consistency {min(sims):.2f}..{max(sims):.2f}"
    if min(sims) < ident.T_TENTATIVE:
        note += " (the clips disagree — worth redoing)"
    with _ENROLL_LOCK:
        _SAVING = False
        if _ENROLL is not None and _GEN == gen:
            _enroll_set(status="done", note=note)
    _emit({"t": "people"})
    _push_voice()
    return voice_state()


def enroll_cancel():
    """POST /api/people/enroll/cancel — nothing is written."""
    global _ENROLL, _EMBEDDER, _CLIPS, _GEN
    with _ENROLL_LOCK:
        _GEN += 1                         # a clip still recording is now stale
        _ENROLL = None
        _EMBEDDER = None
        _CLIPS = []
    _push_voice()
    return voice_state()


# ------------------------------------------------------ devices & sessions ---
def audio_devices():
    """GET /api/audio/devices — query only, never opens a stream."""
    empty = {"input": [], "output": [],
             "default": {"input": None, "output": None}}
    try:
        import sounddevice as sd
        devices = sd.query_devices()
    except Exception:
        return empty
    ins, outs = [], []
    for i, d in enumerate(devices):
        name = str(d.get("name") or f"device {i}")
        if d.get("max_input_channels", 0) > 0:
            ins.append({"i": i, "name": name})
        if d.get("max_output_channels", 0) > 0:
            outs.append({"i": i, "name": name})
    default = {"input": None, "output": None}
    try:
        pair = list(sd.default.device)          # (input, output); -1 = none
        for k, v in zip(("input", "output"), pair):
            default[k] = v if isinstance(v, int) and v >= 0 else None
    except Exception:
        pass
    return {"input": ins, "output": outs, "default": default}


def _stamp_when(stem):
    """20260821-104900 -> 2026-08-21 10:49 (the file name IS the clock)."""
    try:
        return time.strftime("%Y-%m-%d %H:%M",
                             time.strptime(stem, "%Y%m%d-%H%M%S"))
    except ValueError:
        return stem


def sessions_list():
    """GET /api/sessions — past conversations, newest first, 30 at most."""
    rows = []
    try:
        paths = sorted(_sessions_dir().glob("*.jsonl"), reverse=True)
    except OSError:
        return rows
    for p in paths[:30]:
        who, n = [], 0
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            n += 1
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            w = rec.get("who")
            if w and w not in who:
                who.append(w)
        rows.append({"file": p.name, "when": _stamp_when(p.stem),
                     "lines": n, "who": who})
    return rows


def session_rows(name):
    """GET /api/sessions/{file} — one transcript, read-only."""
    if not isinstance(name, str) or not STAMP_RE.match(name):
        raise VoiceError(400, "that is not a session file name")
    path = _sessions_dir() / name
    if not path.is_file():
        raise VoiceError(404, "no such session")
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise VoiceError(500, f"session unreadable: {e}")
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        # never null: the deck uppercases `who` the moment it renders the row
        rows.append({"t": str(rec.get("t") or ""),
                     "who": str(rec.get("who") or "?"),
                     "text": str(rec.get("text") or "")})
    return {"rows": rows}


_load_prefs()
