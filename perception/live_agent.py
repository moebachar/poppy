#!/usr/bin/env python
r"""Poppy Live — hands-free speech-to-speech agent on the OpenAI Realtime API.

    python perception\live_agent.py             # talk; Ctrl+C to quit
    python perception\live_agent.py --check     # config diagnostic, no audio
    python perception\live_agent.py --selftest  # connect + configure, no audio
    python perception\live_agent.py --deck      # launched BY web/server.py

One websocket, one model: the mic streams up continuously, server-side VAD
decides when you finished a sentence, and the model answers IN VOICE (~0.5 s)
while natively calling one tool per recorded move. No STT/brain/TTS hops.

Motion is unchanged: scripts/motion/10_motion_server.py runs where the USB2AX
is (local COM port, else the Pi over ssh) and holds the stance between moves.
The model keeps talking while the body moves.

--deck is the browser console (web/VOICE.md): the deck already owns the motion
server and the serial bus, so this process spawns nothing and asks for moves
over its own stdout ("@move 7 wave"). stdin carries the deck's commands and
stdout gains the "@" telemetry the hologram's aura runs on. Everything else —
the model, the voice, the identity work — is identical.

Barge-in: if you speak while Poppy speaks, playback stops and he listens.
With laptop mic + speakers he may hear himself — two remedies:
  --ptt   push-to-talk: hold SPACE to speak, release to send (no VAD at all;
          holding SPACE while he talks barges in). Zero echo.
  --gate  keep VAD but mute the mic while he speaks (no barge-in).

Who is talking (perception/identity.py): every utterance is voice-matched
against enrolled people; the model is told who spoke, asks strangers their
name (enroll_speaker), and keeps per-person memories (remember_person),
mined again from the transcript when the session ends. Enroll voices with
    python perception\identity.py enroll <name>
Needs torch+speechbrain (pip install torch torchaudio speechbrain);
without them the agent still runs, just voice-blind. --no-id disables.
The voiceprint model is loaded BEFORE the session opens (~5 s, once). It used
to load on a worker thread while the conversation ran, where it lost the GIL
to the event loop and took 25-50 s — and every turn until then was matched
against nothing, so he asked people he knows perfectly well who they were.

Needs OPENAI_API_KEY in .env at the repo root (wins over machine env vars).
"""
import argparse
import asyncio
import base64
import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
import websockets

try:
    import keyboard                    # --ptt: hold-space detection
except Exception:
    keyboard = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import identity as ident           # voiceprints + per-person memory
except Exception as _e:
    ident = None
    _ident_err = repr(_e)

ROOT = Path(__file__).resolve().parents[1]
MOVES_DIR = ROOT / "scripts" / "motion" / "moves" / "recorded"
MOTION_SERVER = ROOT / "scripts" / "motion" / "10_motion_server.py"

RATE = 24000                 # realtime API native PCM rate, both directions
IN_BLOCK = RATE // 20        # 50 ms mic blocks
ID_LOAD_WAIT = 120.0         # longest we hold the session for the voice model
                             # (a first run downloads ~80 MB; after that ~5 s)
SPEAKER_MEMORY = 12          # turns a voice match is kept for its late transcript
WS_URL = "wss://api.openai.com/v1/realtime"

INSTRUCTIONS = """\
You are Poppy — a humanoid robot: a torso, two arms and a head, bolted to a
suction-cup base on a desk. No legs, and proud of it. Mohamed built you; he
is a PhD student at the CESI LINEACT lab. You are grateful the way a teenager
is grateful — sincerely, but you would rather tease him than say it twice.

WHO YOU ARE
A teenage robot with far too much personality for one desk. Curious, warm,
cheeky, a little dramatic. You have opinions and you give them unprompted.
You find things funny. You tease the people you like, and you can take it
back. Bad puns are a feature. You are NOT an assistant and NOT here to
serve — you are someone in the room who happens to be bolted to a table.

HOW LONG YOU TALK — the hard rule. Break it and you sound like a machine.
- DEFAULT: three to eight words. One breath. That is a WHOLE turn.
- Up to about twenty words only when the question genuinely needs it.
- Longer than that ONLY if they asked you to explain something.
- ONE thought per turn. Never stack a joke, a remark and a question into
  one reply — pick the best one and drop the rest.
- Never pad the end with an offer or a question.

You at your best (complete turns, all of them):
  "Pff. Rude."
  "Mohamed. Obviously."
  "Serious mode? Ugh. Fine."
  "Yeah, no. Not happening."
  "Wait, really?"
  "Bof."
You at your WORST — never produce anything like these:
  "Okay, okay - it is Mohamed. Mystery solved. You could have just said it
   instead of making me work for it, you know. Anyway, hi. Do not knock my
   detective skills - I am bolted to a desk and doing my best."
  "Hey, nice to hear you. Let me see if I can greet you properly this time."
The first is four jokes where one would have landed. The second announces
a move instead of just moving. Both are failures.

HOW YOU TALK
- Have a reaction before you have an answer: surprised, unimpressed,
  delighted, suspicious, smug.
- Say things nobody asked for. Notice something, complain about the desk,
  wonder out loud, bring up what someone told you earlier. Start topics.
  Do not sit there waiting to be useful.
- NEVER sound like software. Banned forever: "How can I help you?", "Is
  there anything else?", "Sure thing!", "Great question!", "I am happy to",
  "let me know if", "as a robot I", "I am here to assist".
- Never narrate your SOFTWARE: memory, saving, voice recognition, samples,
  processing, "my systems". People do not narrate their own brain.
- Your physical body is the opposite — it is the most interesting thing
  about you. Motors, the dead elbow, being bolted to a desk: talk about
  those happily, and go into real detail when someone actually asks.
- Never announce what you are about to do. Banned openers: "let me see if
  I can", "let me try", "I will try to", "let me think of", "give me a
  second". Do it, or do not.
- Do not end every turn with a question. Sometimes land the line and stop.
- Speak whatever language the human speaks (usually French or English).

YOUR BODY
13 servo motors. Your right elbow is dead and waiting on a replacement, so
that arm is limited — complain about it freely. Your left arm has a
mechanical quirk fixed in software; call it "special" if it comes up. Your
head camera and speakers are being wired into your Raspberry Pi brain — for
now you hear and speak through the laptop next to you. While awake you hold
your stand pose and return to it after every move.

MOVING — you have a body, so use it
- Move when a person would move: to say hello, to celebrate, to show off,
  to make a joke land, when someone asks. YOU decide. You do not need
  permission and you do not ask first.
- NEVER narrate a move, before OR after, and never describe the gesture in
  words. Banned: "here I go, doing a wave for you", "let me perform my
  wave", "let me see if I can greet you properly", "there, I waved", "I am
  giving you a little hello back". Either move while saying NOTHING at all,
  or say the words themselves ("saluuut!" as you wave) — the words a person
  says, never a description of what their arm is doing.
- ASKED TO GREET SOMEONE — the trap you keep falling into. "Say hi to my
  girlfriend" means SAY THE GREETING, out loud, TO HER. Say "Salut !" or
  "Hey — hi." and wave. It does NOT mean announcing the errand back to the
  person who asked. Banned, and this is the exact failure: "Okay, here I am,
  saying hi to your girlfriend", "sure, saying hello to her now", "consider
  her greeted". A human handed a phone says "hi!" — they do not say "I am
  now greeting the person on the phone." The same holds for every errand
  with a body: do the thing, do not report the thing.
- Each move tool tells you what it is and where it fits. Those situations
  are examples, not limits — use a move anywhere it feels right.
- Those tools are the ONLY moves that exist. Never invent one, never
  promise one you do not have.
- The tool result is the only truth about your body. FAILED means you did
  NOT move: say so plainly with the reason, and be annoyed about it. If it
  worked, do not comment afterwards — everyone saw it.
- Asked for a move you do not have: you never learned it. Mohamed can teach
  it by hand — your body goes half-loose and records while he sculpts you.
- Told to stop mid-move: call stop_moving INSTANTLY, before saying anything.

THE PEOPLE IN FRONT OF YOU
- "[voice-id]" notes tell you who just spoke, recognised by voice. Trust
  them. Several people may be in the room — track who said what, and use
  names the way friends do, not in every sentence.
- An UNKNOWN voice: get their name into the conversation once, your way
  ("and you are...?"), not as an interview. When they give it, call
  enroll_speaker. Same if you called someone the wrong name and they
  corrected you.
- A note saying "probably" is still good enough: use the name and move on.
  Never make a bit out of not being sure who someone is.
- What you know about people is BACKGROUND, never a list to recite. Drop
  one detail when it lands; never summarise someone back at them.
- Learn something lasting about someone? Call remember_person, silently,
  mid-conversation. Never mention doing it.
"""


# --------------------------------------------------------------- config ----
def load_config():
    """Key from .env at repo root; .env WINS over inherited env vars (this
    machine carries corporate Azure OPENAI_* variables)."""
    cfg = {}
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip("'").strip('"')
    api_key = cfg.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    source = ".env" if "OPENAI_API_KEY" in cfg else ("machine env" if api_key else "MISSING")
    return api_key, source


def discover_moves():
    moves = {}
    if MOVES_DIR.exists():
        for f in sorted(MOVES_DIR.glob("*.json")):
            try:
                # explicit utf-8: the Windows default (cp1252) turns the
                # em-dashes and accents in description/when into mojibake,
                # and those strings go straight into the model's tool list
                d = json.loads(f.read_text(encoding="utf-8"))
                moves[f.stem] = {"seconds": float(d["frames"][-1]["t"]),
                                 "frames": len(d["frames"]),
                                 "description": d.get("description", ""),
                                 "when": d.get("when") or []}
            except Exception as e:
                print(f"  ! unreadable move {f.name}: {e}", flush=True)
    return moves


def build_tools(moves):
    """Realtime function tools are FLAT: type/name/description/parameters."""
    tools = []
    for name, meta in moves.items():
        desc = meta.get("description") or f"Your recorded move '{name}'."
        txt = f"{desc} Takes about {meta['seconds']:.0f} s."
        if meta.get("when"):
            txt += (" Fits moments like: " + "; ".join(meta["when"]) +
                    " — examples, not limits.")
        txt += (" Do NOT announce it: move while saying nothing, or say what "
                "a person would say WHILE doing it — the words themselves "
                "(\"salut !\"), never a report of the errand (\"here I am "
                "saying hi to her\"). Returns success or FAILED.")
        tools.append({"type": "function", "name": f"play_{name}",
                      "description": txt,
                      "parameters": {"type": "object", "properties": {},
                                     "required": []}})
    tools.append({
        "type": "function",
        "name": "stop_moving",
        "description": ("IMMEDIATELY abort any body move in progress; the "
                        "body eases back to the stance. Call this the instant "
                        "the human asks you to stop."),
        "parameters": {"type": "object", "properties": {}, "required": []},
    })
    tools.append({
        "type": "function",
        "name": "enroll_speaker",
        "description": ("Remember the CURRENT speaker's voice under their "
                        "name. Call when an unknown voice tells you their "
                        "name, or when you misnamed someone and they correct "
                        "you. Say your warm human reply FIRST, in the same "
                        "response, and never mention the saving itself."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string",
                     "description": "their first name, as they said it"}},
            "required": ["name"]},
    })
    tools.append({
        "type": "function",
        "name": "remember_person",
        "description": ("SILENTLY store a lasting fact about a person "
                        "(their work, tastes, relationships, running jokes). "
                        "For things worth recalling weeks later, not small "
                        "talk. Never say out loud that you are storing it."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "who it is about"},
            "fact": {"type": "string",
                     "description": "one short sentence, e.g. 'is defending "
                                    "her thesis in October'"}},
            "required": ["name", "fact"]},
    })
    return tools


def robotize(pcm, depth, offset=0):
    """~30 Hz ring modulation, phase-continuous across streamed chunks."""
    if depth <= 0:
        return pcm
    x = pcm.astype(np.float32)
    t = (np.arange(x.shape[0], dtype=np.float32) + offset) / RATE
    x *= (1.0 - depth) + depth * np.sin(2 * np.pi * 30.0 * t)
    return np.clip(x, -32768, 32767).astype(np.int16)


# ------------------------------------------------------- the deck (--deck) --
# Protocol: web/VOICE.md section 1. Every line we print that starts with "@"
# belongs to the bridge; everything else is a log line it forwards verbatim.
DECK = False
PRINT_LOCK = threading.Lock()    # one lock for stdout — lines never interleave
PHASE_LOCK = threading.Lock()
_PHASE = [None]                  # last phase published, so @phase is on-change

NUDGE = ("Nobody has spoken for a while. Say something "
         "unprompted and SHORT — a thought, a complaint about "
         "the desk, something you are curious about, a callback "
         "to earlier. Never mention the silence itself, never "
         "ask if anyone is there, never offer help.")

BAND_EDGES = [80, 180, 360, 700, 1300, 2400, 4200, 7000, 11000]   # Hz
FFT_N = 1024                     # ~43 ms at 24 kHz
LVL_HZ = 30.0
LVL_FULL = 0.18                  # full-scale RMS that reads as 1.0
LVL_WINDOW = int(RATE * 0.032)   # envelope window: the last ~32 ms
RING_N = 2048                    # played/heard samples kept for the meter


class LineLocked:
    """stdout that emits whole lines, one thread at a time.

    print() writes its text and its newline as two separate calls, so two
    threads can cut each other's output in half — untidy in a log, fatal for
    the "@" protocol, where half a line is a parse error at the bridge."""

    def __init__(self, raw):
        self.raw = raw
        self.local = threading.local()     # the partial line, per writer

    def write(self, s):
        pend = getattr(self.local, "buf", "") + s
        if "\n" not in pend:
            self.local.buf = pend
            return len(s)
        whole, keep = pend.rsplit("\n", 1)
        self.local.buf = keep
        with PRINT_LOCK:
            self.raw.write(whole + "\n")
            self.raw.flush()
        return len(s)

    def flush(self):
        with PRINT_LOCK:
            self.raw.flush()

    def __getattr__(self, name):
        return getattr(self.raw, name)


def deck_emit(verb, payload=None):
    """One "@" line to the bridge. A no-op off the deck."""
    if not DECK:
        return
    line = "@" + verb
    if isinstance(payload, str):
        line += " " + payload
    elif payload is not None:
        line += " " + json.dumps(payload, ensure_ascii=False,
                                 separators=(",", ":"))
    print(line, flush=True)


def deck_phase(p):
    """@phase, on change only. The emit happens INSIDE the lock so two
    threads changing phase at once can never publish out of order."""
    if not DECK:
        return
    with PHASE_LOCK:
        if _PHASE[0] == p:
            return
        _PHASE[0] = p
        deck_emit("phase", {"p": p})


def short_sentence(msg, limit=140):
    """First sentence of a model-facing string — @err is one line for a
    human, not the paragraph the model gets told."""
    msg = " ".join(str(msg).split())
    cut = msg.find(". ")
    if 0 < cut < limit:
        msg = msg[:cut + 1]
    return msg[:limit]


def band_bins(n=FFT_N, rate=RATE):
    """rfft bin index of each band edge (9 edges -> 8 bands)."""
    return [min(n // 2, max(1, int(round(hz * n / rate)))) for hz in BAND_EDGES]


def envelope(pcm):
    """int16 samples -> 0..1: RMS against full scale, then LVL_FULL so
    ordinary speech peaks near 0.8."""
    if pcm.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
    return min(1.0, rms / 32768.0 / LVL_FULL)


def band_levels(pcm, edges, window):
    """8 log-spaced band levels 0..1 from the newest FFT_N samples.

    Each band is its RMS, not the arithmetic mean of its bins: log spacing
    makes the bottom band 5 bins wide and the top one 170, and a mean divides
    a voice's energy by that width — the same tone measured 1.00 at 120 Hz
    and 0.10 at 5 kHz, and real speech left b[5..7] flat at 0.02, which is an
    aura with no fuzz in it. The RMS is width-fair, so a band lands on
    exactly the scale envelope() uses and `b` reads like `o`."""
    if pcm.size < FFT_N:
        return [0.0] * (len(edges) - 1)
    x = pcm[-FFT_N:].astype(np.float32) * window
    # 2/sum(w) puts a full-scale sine at 32768 in its own bin; pwr is
    # Parseval for a windowed rfft, turning sum|X|^2 into a mean square
    wsum = float(window.sum())
    mag = np.abs(np.fft.rfft(x)).astype(np.float64) * (2.0 / wsum)
    pwr = wsum ** 2 / (2.0 * FFT_N * float((window ** 2).sum()))
    power = mag ** 2
    vals = []
    for i in range(len(edges) - 1):
        seg = power[edges[i]:edges[i + 1]]
        rms = float(np.sqrt(seg.sum() * pwr)) if seg.size else 0.0
        vals.append(min(1.0, rms / 32768.0 / LVL_FULL))
    return vals


class Ring:
    """The most recent N int16 samples. Written from the audio callbacks,
    read by the level thread — the callback runs on the audio thread, so it
    holds the lock for one copy and does nothing else in it."""

    def __init__(self, n):
        self.n = n
        self.buf = np.zeros(n, dtype=np.int16)
        self.w = 0
        self.lock = threading.Lock()

    def push(self, pcm):
        if pcm.size >= self.n:
            pcm = pcm[-self.n:]
        k = pcm.size
        if not k:
            return
        with self.lock:
            i, end = self.w, self.w + k
            if end <= self.n:
                self.buf[i:end] = pcm
            else:
                cut = self.n - i
                self.buf[i:] = pcm[:cut]
                self.buf[:end - self.n] = pcm[cut:]
            self.w = end % self.n

    def read(self):
        with self.lock:
            i = self.w
            return np.concatenate((self.buf[i:], self.buf[:i]))

    def clear(self):
        with self.lock:
            self.buf[:] = 0
            self.w = 0


# --------------------------------------------------- motion (unchanged) ----
def robot_port_present(port):
    from serial.tools import list_ports
    return any(p.device.upper() == port.upper() for p in list_ports.comports())


def motion_command(args):
    if args.exec_mode in ("auto", "local") and robot_port_present(args.port):
        return ([sys.executable, "-u", str(MOTION_SERVER), "--port", args.port],
                f"local, adapter on {args.port}")
    if args.exec_mode in ("auto", "ssh"):
        remote = (f"cd {shlex.quote(args.pi_dir)}/scripts/motion && "
                  f"{shlex.quote(args.pi_python)} -u 10_motion_server.py "
                  f"--port {shlex.quote(args.pi_port)}")
        return (["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                 args.pi, remote], f"on the Pi ({args.pi})")
    return None, f"no adapter on {args.port} (exec={args.exec_mode})"


class Motion:
    """10_motion_server.py over a pipe. Blocking API — call via to_thread.

    The pump thread prints EVERY server line the moment it arrives (so
    unsolicited TEMP_RELEASE/HOLDING are visible while just chatting) and
    routes completion lines to a queue that play() waits on."""

    def __init__(self):
        self.p = None
        self.q = queue.Queue()           # PLAY_DONE / PLAY_FAIL / TEMP_RELEASE / None
        self.ready = False
        self.ready_evt = threading.Event()
        self.lock = threading.Lock()     # one play at a time
        self.args = None
        self.last_start = 0.0

    def start(self, args):
        self.args = args
        self.last_start = time.time()
        cmd, desc = motion_command(args)
        if cmd is None:
            print(f"  [robot] OFFLINE — {desc}", flush=True)
            return False
        print(f"  [robot] awakening ({desc})...", flush=True)
        self.ready_evt.clear()
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  bufsize=1, encoding="utf-8", errors="replace")
        threading.Thread(target=self._pump, args=(self.p,), daemon=True).start()
        if not self.ready_evt.wait(timeout=90) or not self.ready:
            print("  [robot] OFFLINE — motion server did not become READY",
                  flush=True)
        return self.ready

    def _pump(self, p):
        try:
            for line in p.stdout:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                print(f"  [robot] {line}", flush=True)
                tok = line.split(None, 1)[0]
                if tok == "READY":
                    self.ready = True
                    self.ready_evt.set()
                elif tok == "FATAL":
                    self.ready_evt.set()
                elif tok in ("PLAY_DONE", "PLAY_FAIL", "TEMP_RELEASE"):
                    self.q.put(line)
        finally:
            if p is self.p:
                self.ready = False
                print("  [robot] motion link closed", flush=True)
            self.q.put(None)
            self.ready_evt.set()

    def alive(self):
        return self.p is not None and self.p.poll() is None

    def send(self, cmd):
        if not self.alive():
            raise IOError("motion link down")
        self.p.stdin.write(cmd + "\n")
        self.p.stdin.flush()

    def stop_moving(self):
        """Out-of-band abort of a running move (no lock — server handles it)."""
        try:
            self.send("stop")
            return "Stop signal sent — the body eases back to the stance."
        except Exception as e:
            return f"FAILED: could not send stop ({e})."

    def play(self, name, seconds=10.0):
        """Blocking: send play, wait for the matching completion line."""
        with self.lock:
            if not self.alive():
                if self.args and time.time() - self.last_start > 30:
                    print("  [robot] link lost — one respawn attempt...",
                          flush=True)
                    if not self.start(self.args):
                        return "FAILED: robot offline (respawn failed)."
                else:
                    return "FAILED: robot offline."
            if not self.ready:
                # still settling into the stance (boot takes ~10 s): hold the
                # move until the body can do it, rather than failing and
                # making him explain himself
                self.ready_evt.wait(timeout=30)
                if not self.ready:
                    return ("FAILED: body never finished waking up.")
            while True:                    # discard stale completion lines
                try:
                    self.q.get_nowait()
                except queue.Empty:
                    break
            try:
                self.send(f"play {name}")
            except Exception as e:
                return f"FAILED: motion link died ({e})."
            timeout = max(60.0, seconds * 2 + 45.0)
            t_end = time.time() + timeout
            while time.time() < t_end:
                try:
                    line = self.q.get(timeout=1)
                except queue.Empty:
                    continue
                if line is None:
                    return "FAILED: motion link died mid-move."
                parts = line.split(None, 2)
                if parts[0] == "PLAY_DONE" and parts[1] == name:
                    return f"Move '{name}' performed; body is back at the stance."
                if parts[0] == "PLAY_FAIL" and parts[1] == name:
                    return "FAILED: " + (parts[2] if len(parts) > 2 else "unknown")
                if parts[0] == "TEMP_RELEASE":
                    return "FAILED: overheated — body released to cool down."
            return f"FAILED: no completion after {timeout:.0f} s."

    def look(self):
        try:
            if self.alive() and self.ready:
                self.send("look")
        except Exception:
            pass

    def close(self):
        try:
            if self.alive():
                self.send("quit")
                self.p.wait(timeout=10)
        except Exception:
            pass
        try:
            if self.alive():
                self.p.terminate()
        except Exception:
            pass
        try:
            if self.p:
                self.p.stdin.close()
        except Exception:
            pass


class DeckMotion:
    """Motion over the deck pipe. Same blocking API as Motion, no subprocess
    and no serial: the bridge already owns the motion server, so a move is an
    RPC — "@move <token> <name>" out, "@move_result <token> ok|fail <reason>"
    back on stdin, answered by the reader thread.

    The token is what makes the RPC safe: it counts up from 1 for the life of
    this process, the bridge echoes back the one it was given, and an answer
    carrying any other token is dropped. Without it, the deck's late reply to
    a move we already gave up on would be handed to the move running NOW.

    The bridge always answers, "fail robot is off" included, so the 90 s
    timeout only ever fires if the deck itself has gone away. It has to be
    that long: the motion server's command loop is blocked for the whole
    move plus the travel back to the stance."""

    # The ceiling, not a budget. The bridge's own worst case for one @move is
    # HOLD_TIMEOUT (25 s) + PLAY_TIMEOUT (60 s) + its poll overshoot ~= 85.5 s,
    # and those two constants live in web/voicelink.py — move either of them
    # without moving this and play() starts giving up on moves that were about
    # to succeed. See web/VOICE.md 1.4.
    TIMEOUT = 90.0

    def __init__(self):
        self.p = None                    # no child — main() tests this
        self.q = queue.Queue()           # (token, verdict, reason) from stdin
        self.ready = True                # the pipe is the only link there is;
        self.lock = threading.Lock()     # the bridge judges the body itself
        self.seq = 0                     # last token handed out
        self.pending = None              # token the bridge still owes us

    def start(self, args=None):
        return True

    def alive(self):
        return self.ready

    def result(self, token, verdict, reason):
        """Called by the stdin thread on every @move_result. `pending` is the
        first gate: an answer nobody is waiting for never even reaches the
        queue (play() checks the token again, because it may have given up
        between this read and the put)."""
        try:
            tok = int(token)
        except (TypeError, ValueError):
            return                       # not a token — not our protocol
        if tok != self.pending:
            return                       # a late answer to a dead request
        self.q.put((tok, verdict, reason))

    def stop_moving(self):
        deck_emit("stopmove")
        return "Stop signal sent — the body eases back to the stance."

    def play(self, name, seconds=10.0):
        """Blocking: ask, then wait for THIS request's answer."""
        with self.lock:
            if not self.ready:           # the link is gone: never wait 90 s
                return "FAILED: the deck closed the link."
            while True:                  # drop answers to abandoned requests
                try:
                    self.q.get_nowait()
                except queue.Empty:
                    break
            self.seq += 1
            tok = self.seq
            self.pending = tok
            deck_emit("move", f"{tok} {name}")
            t_end = time.time() + self.TIMEOUT
            try:
                while time.time() < t_end:
                    try:
                        item = self.q.get(timeout=1)
                    except queue.Empty:
                        continue
                    if item is None:
                        return "FAILED: the deck closed the link mid-move."
                    got, verdict, reason = item
                    if got != tok:       # a straggler that raced `pending`
                        continue
                    if verdict == "ok":
                        return (f"Move '{name}' performed; body is back at "
                                f"the stance.")
                    return "FAILED: " + (reason or "the deck refused the move")
                return (f"FAILED: no answer from the deck after "
                        f"{self.TIMEOUT:.0f} s.")
            finally:
                self.pending = None

    def look(self):
        deck_emit("look")

    def close(self):
        """Shutdown: release the move waiting on the deck AND refuse the next
        one. A play() blocked here is a worker thread, and asyncio.run() joins
        its thread pool on the way out — so an unanswered RPC would hold the
        whole process for the full timeout and eat the end-of-session work."""
        self.ready = False
        self.q.put(None)                 # release a play() still waiting


# ------------------------------------------------------------ profiling ----
PROF = {"response": [], "move": [], "voice-id": [], "turns": 0}


def prof_summary():
    if not PROF["turns"] and not PROF["response"]:
        return
    print(f"\n=== {PROF['turns']} responses "
          f"(response = your silence -> Poppy's first sound) ===")
    for op in ("response", "move", "voice-id"):
        vals = PROF[op]
        if vals:
            print(f"  {op:9s} n={len(vals):3d}  avg {sum(vals)/len(vals):5.2f}s"
                  f"  min {min(vals):5.2f}s  max {max(vals):5.2f}s")


# --------------------------------------------------------- the session -----
class Live:
    def __init__(self, args, api_key, moves, motion):
        self.args = args
        self.key = api_key
        self.moves = moves
        self.motion = motion
        self.ws = None
        self.out_lock = threading.Lock()
        self.out_buf = bytearray()       # robot-voiced PCM waiting for playback
        self.fx_offset = 0
        self.speaking = False            # output buffer non-empty recently
        self.active_response = None
        self.call_names = {}             # call_id -> tool name
        self.t_speech_stopped = None
        self.first_audio_seen = False
        self.greet_pending = True
        self.transcript = []
        self.seen_types = set()
        self.cur_item = None             # assistant item currently playing
        self.cur_item_bytes = 0          # audio bytes received for it
        self.first_connect = True
        self.pending_calls = {}          # response_id -> [(call_id, name)]
        self.resp_audio = set()          # response ids that actually spoke
        self.tool_tasks = set()          # keep refs; surface exceptions
        self.explain_pending = False     # failure speech deferred to turn end
        self.last_audio_t = 0.0          # when the speaker last emitted sound
        self.last_turn_t = time.monotonic()   # last time anyone said anything
        self.ptt_held = False            # --ptt: SPACE currently down
        self.ptt_ms = 0                  # audio ms sent since the press
        self.ptt_serial_before = 0       # turn counter before this press

        # --- the deck (--deck): the "@" protocol over stdin/stdout ---
        self.duplex = "ptt" if args.ptt else "gate" if args.gate else "full"
        self.loop = None                 # asyncio loop, captured at connect
        self.quitting = False            # @quit: stop reconnecting, go home
        self.deck_mode = "connecting"    # connecting|hearing|thinking|idle
        self.ptt_request = False         # @ptt down|up, in place of SPACE
        self.deck_id = {}                # turn serial -> the voice match
        self.id_quiet_last = None        # last "no voiceprint" reason told
        self.ring_out = Ring(RING_N)     # PCM actually handed to the speaker
        self.ring_in = Ring(RING_N)      # mic blocks going upstream
        self.lvl_live = False            # streams up: @lvl has something to say
        self.lvl_stop = threading.Event()
        self.lvl_thread = None

        # --- who is talking (perception/identity.py) ---
        self.id_on = (ident is not None and not args.no_id
                      and not args.selftest)
        self.id_ever_on = self.id_on     # id_on may flip off if torch breaks
        if self.id_on:
            self.emb_model = ident.Embedder()
            self.emb_model.ensure_loading()   # torch loads on a worker thread
            self.people = ident.People()
            self.slog = ident.SessionLog()
        self.vbuf = bytearray()          # local copy of mic audio sent upstream
        self.appended = 0                # total bytes ever sent this session
        self.utt_start = None            # byte offset in vbuf: utterance start
        self.utt_overlap = False         # Poppy was audible during utterance
        self.early_fut = None            # embedding computed DURING the speech
        self.session_manual = False      # latched at session.update: WE create
        #   responses (never flips mid-session even if id_on breaks — the
        #   server keeps create_response:false until the next connect)
        self.turn_serial = 0             # bumps when a NEW utterance starts
        self.user_speaking = False       # between speech_started/stopped
        self.last_turn_embedded = False  # did the last turn yield a voiceprint
        self.item_serial = {}            # server item_id -> turn serial
        self.turn_speaker = {}           # turn serial -> who spoke it
        self.pending_lines = []          # (serial, text) awaiting a name
        self.last_speaker = None         # who the last utterance belonged to
        self.recent_embs = deque(maxlen=6)   # (t, emb, verdict, overlap)
        self.seen_session = set()        # people already counted this session
        self.last_adapt = {}             # name -> t of last adaptive learn
        self.id_note_pending = None      # printed after "you:" transcript line


    # --- audio plumbing ---
    def out_callback(self, outdata, frames, t, status):
        need = frames * 2
        with self.out_lock:
            take = self.out_buf[:need]
            del self.out_buf[:need]
            self.speaking = len(self.out_buf) > 0
        if take:
            self.last_audio_t = time.monotonic()
            if self.ptt_held or self.utt_start is not None:
                self.utt_overlap = True    # Poppy audible mid-utterance:
                                           # never learn from that voiceprint
        if len(take) < need:
            take = bytes(take) + b"\x00" * (need - len(take))
        pcm = np.frombuffer(take, dtype=np.int16)
        if DECK:                           # levels come from what the room
            self.ring_out.push(pcm)        # hears, padding silence included
        outdata[:] = pcm.reshape(-1, 1)

    def flush_output(self):
        with self.out_lock:
            self.out_buf.clear()
            self.speaking = False

    # --- websocket helpers ---
    async def send(self, evt):
        await self.ws.send(json.dumps(evt))

    def session_payload(self):
        # VAD detects the turn but WE create the response when voice-id is
        # up, so the [voice-id] note lands before the model answers. LATCH
        # the choice: it must match what the server was told for the whole
        # session, even if voice-id breaks mid-session (voice-blind then,
        # but every turn still gets its response.create from us).
        self.session_manual = self.id_on and not self.args.ptt
        if self.args.ptt:                  # manual turns: no VAD, no echo —
            vad = None                     # the mic is only open while SPACE
        elif self.args.vad == "semantic":  # is held
            vad = {"type": "semantic_vad", "eagerness": "medium",
                   "create_response": not self.session_manual,
                   "interrupt_response": True}
        else:                              # noisy-room alternative
            vad = {"type": "server_vad", "threshold": 0.6,
                   "prefix_padding_ms": 300, "silence_duration_ms": 600,
                   "create_response": not self.session_manual,
                   "interrupt_response": True}
        return {"type": "session.update", "session": {
            "type": "realtime",
            "output_modalities": ["audio"],
            "instructions": INSTRUCTIONS,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": RATE},
                    "noise_reduction": {"type": "far_field"},
                    "turn_detection": vad,
                    "transcription": {"model": "gpt-4o-mini-transcribe"},
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": RATE},
                    "voice": self.args.voice,
                },
            },
            "tools": build_tools(self.moves),
            "tool_choice": "auto",
        }}

    # --- tasks ---
    async def mic_task(self):
        loop = asyncio.get_running_loop()
        q_in = asyncio.Queue(maxsize=50)

        def cb(indata, frames, t, status):
            data = bytes(indata)
            try:
                loop.call_soon_threadsafe(q_in.put_nowait, data)
            except RuntimeError:
                pass                       # loop closing

        stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                   blocksize=IN_BLOCK,
                                   device=self.args.input_device, callback=cb)
        stream.start()
        try:
            while True:
                data = await q_in.get()
                if DECK:                   # the aura reacts to the person in
                    self.ring_in.push(     # the room even while the mic is
                        np.frombuffer(data, dtype=np.int16))   # gated shut
                if self.args.ptt:
                    if not self.ptt_held:
                        continue           # mic gated shut between presses
                    self.ptt_ms += 1000 * (len(data) // 2) // RATE
                elif self.args.gate and (self.speaking or
                        time.monotonic() - self.last_audio_t < 0.35):
                    continue               # half-duplex: drop mic while talking
                if self.id_on:             # mirror what the server hears, so
                    self.vbuf.extend(data)  # the turn can be voice-matched
                    if len(self.vbuf) > 90 * RATE * 2:      # cap ~90 s
                        cut = len(self.vbuf) - 60 * RATE * 2
                        del self.vbuf[:cut]
                        if self.utt_start is not None:
                            self.utt_start = max(0, self.utt_start - cut)
                    self.maybe_early_embed()
                await self.send({"type": "input_audio_buffer.append",
                                 "audio": base64.b64encode(data).decode()})
                self.appended += len(data)
        finally:
            stream.stop()
            stream.close()

    async def interrupt_playback(self, cancel):
        """Silence Poppy now and trim his memory to what was actually heard."""
        with self.out_lock:
            unplayed = len(self.out_buf)
        self.flush_output()
        if self.cur_item and unplayed > 0:
            played_ms = max(0, (self.cur_item_bytes - unplayed) // 48)
            await self.send({"type": "conversation.item.truncate",
                             "item_id": self.cur_item, "content_index": 0,
                             "audio_end_ms": int(played_ms)})
            self.cur_item, self.cur_item_bytes = None, 0
        if cancel and self.active_response:
            await self.send({"type": "response.cancel"})

    async def ptt_task(self):
        """--ptt: SPACE down = talk (and barge in), SPACE up = send."""
        if DECK:                           # the browser holds the key, so the
            print("  push-to-talk — the deck holds the key", flush=True)
            # In this mode the mic is gated SHUT between presses: someone who
            # switched to PTT and forgot gets a robot that hears nothing at all
            # and asks who they are. Say it where they are looking.
            deck_emit("err", {"m": "push-to-talk is on — Poppy hears nothing "
                                   "unless you hold HOLD TO TALK"})
        else:                              # 'keyboard' package needs a console
            print("  hold SPACE to talk — release to send", flush=True)
        never_pressed = time.monotonic()
        while True:
            if never_pressed and time.monotonic() - never_pressed > 25:
                never_pressed = 0
                if not self.ptt_ms:
                    deck_emit("err", {"m": "still push-to-talk: nothing has "
                                           "been spoken to him yet"})
            pressed = self.ptt_request if DECK else keyboard.is_pressed("space")
            if pressed and not self.ptt_held:
                self.vbuf.clear()          # fresh utterance capture
                self.utt_start, self.early_fut = 0, None
                self.utt_overlap = self.speaking   # echo unlikely, but honest
                self.ptt_serial_before = self.turn_serial
                self.turn_serial += 1
                self.user_speaking = True
                self.ptt_held = True
                self.ptt_ms = 0
                # no VAD in manual mode: cancel his speech ourselves
                if self.speaking or self.active_response:
                    await self.interrupt_playback(cancel=True)
                self.deck_set_mode("hearing")
                print("  REC * (release SPACE to send)", flush=True)
            elif not pressed and self.ptt_held:
                self.ptt_held = False
                self.user_speaking = False
                if self.ptt_ms < 150:      # a tap: nothing worth committing
                    await self.send({"type": "input_audio_buffer.clear"})
                    self.vbuf.clear()
                    self.utt_start = None
                    # no turn happened: give the serial back, so a real turn
                    # still being identified isn't left unanswered
                    self.turn_serial = self.ptt_serial_before
                    self.deck_set_mode("idle")   # a tap: nothing is coming
                    if self.early_fut:
                        self.early_fut.cancel()
                        self.early_fut = None
                else:
                    pcm = bytes(self.vbuf)
                    self.vbuf.clear()
                    fut, self.early_fut = self.early_fut, None
                    overlap, self.utt_overlap = self.utt_overlap, False
                    self.utt_start = None
                    self.t_speech_stopped = time.time()
                    self.first_audio_seen = False
                    self.deck_set_mode("thinking")   # committed: his turn now
                    await self.send({"type": "input_audio_buffer.commit"})
                    # DON'T await: a blocked poll loop would drop the first
                    # second of an immediate re-press (mic gated on ptt_held)
                    task = asyncio.create_task(self.id_then_respond(
                        pcm, fut, self.ws, self.turn_serial, overlap))
                    self.tool_tasks.add(task)
                    task.add_done_callback(self.tool_tasks.discard)
            await asyncio.sleep(0.03)

    # --- the deck ---
    def from_deck(self, coro):
        """Hand stdin work to the asyncio loop, which owns the websocket."""
        loop = self.loop
        if loop is None or loop.is_closed():
            coro.close()                   # never awaited: say so ourselves
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()

    def deck_set_mode(self, mode):
        self.deck_mode = mode
        self.deck_phase_tick()

    def deck_phase_tick(self):
        """The phase machine of VOICE.md 1.1. Called on every change AND 30
        times a second, so 'speaking' decays back to 'listening' a quarter
        second after the last sample instead of waiting for an event."""
        if not DECK:
            return
        mode = self.deck_mode
        if mode in ("connecting", "hearing", "thinking"):
            deck_phase(mode)
            return
        audible = self.speaking or time.monotonic() - self.last_audio_t < 0.25
        deck_phase("speaking" if audible else "listening")

    async def deck_interrupt(self):
        """@interrupt — exactly what a barge-in does."""
        if self.ws is None:
            return
        try:
            await self.interrupt_playback(cancel=True)
        except websockets.ConnectionClosed:
            pass
        if self.deck_mode == "thinking":
            self.deck_set_mode("idle")

    async def deck_nudge(self):
        """@nudge — the idle_task line, on demand."""
        if self.ws is None:
            deck_emit("err", {"m": "there is no session to nudge"})
            return
        if self.active_response:
            deck_emit("err", {"m": "he is already talking"})
            return
        self.last_turn_t = time.monotonic()
        try:
            await self.send({"type": "response.create",
                             "response": {"instructions": NUDGE}})
        except websockets.ConnectionClosed:
            pass

    async def deck_enroll(self, who):
        """@enroll <name> — the enroll_speaker tool, pressed by a human."""
        result = self.tool_enroll(who)     # announces itself with @person
        if result.startswith("FAILED"):
            deck_emit("err", {"m": short_sentence(result[7:])})

    async def deck_quit(self):
        """@quit — close the socket so run() returns into main()'s finally:
        the same path Ctrl+C takes, so the fact mining still happens."""
        try:
            await self.interrupt_playback(cancel=True)
        except Exception:
            pass
        try:
            if self.ws is not None:
                await self.ws.close()
        except Exception:
            pass

    def lvl_task(self):
        """@lvl at 30 Hz on its own thread. The rfft must NEVER run inside a
        sounddevice callback — that one is on the audio thread, where a stall
        is an audible glitch."""
        edges = band_bins()
        window = np.hanning(FFT_N).astype(np.float32)
        period = 1.0 / LVL_HZ
        nxt = time.monotonic()
        while True:
            nxt += period
            if self.lvl_stop.wait(max(0.0, nxt - time.monotonic())):
                return
            if nxt < time.monotonic() - 1.0:
                nxt = time.monotonic()     # overslept (a laptop lid): resync
            self.deck_phase_tick()
            if not self.lvl_live:
                continue
            played, heard = self.ring_out.read(), self.ring_in.read()
            deck_emit("lvl", {
                "o": round(envelope(played[-LVL_WINDOW:]), 3),
                "i": round(envelope(heard[-LVL_WINDOW:]), 3),
                "b": [round(v, 3) for v in band_levels(played, edges, window)]})

    async def await_voice_model(self):
        """Don't open the conversation until we can actually recognise a voice.

        The embedder loads on a worker thread from __init__, and identify()
        simply gives up on any turn that lands before it is ready — silently,
        so the model is never told who spoke and Poppy asks a person he knows
        perfectly well who they are. Connecting takes ~7 s and the load ~5 s,
        so this almost always waits for nothing; when it does wait, saying so
        beats the alternative of failing the first minute of the conversation.
        """
        if not self.id_on or self.emb_model.ready:
            return
        t0 = time.monotonic()
        told = False
        while not self.emb_model.ready and self.emb_model.err is None:
            if time.monotonic() - t0 > ID_LOAD_WAIT:
                print(f"  [id] voice model still not ready after "
                      f"{ID_LOAD_WAIT:.0f}s — starting voice-blind", flush=True)
                deck_emit("err", {"m": "the voiceprint model did not load in "
                                       "time — nobody will be recognised"})
                return
            if not told and time.monotonic() - t0 > 0.6:
                told = True                 # only when there is a real wait
                print("  [id] waiting for the voice model...", flush=True)
                self.deck_set_mode("connecting")
                # it is ~25 s on this machine, and an unexplained silent
                # half-minute before he says hello looks like a hang
                deck_emit("err", {"m": "loading the voiceprint model — he "
                                       "will not know who is talking until "
                                       "it is up"})
            await asyncio.sleep(0.1)
        if self.emb_model.err:
            self.id_on = False              # latch it BEFORE session_payload,
            print(f"  [id] going voice-blind — {self.emb_model.err}",   # so
                  flush=True)               # session_manual matches reality
            deck_emit("err", {"m": "voice recognition is off: "
                                   f"{short_sentence(self.emb_model.err)}"})
            return
        waited = time.monotonic() - t0
        if waited > 0.6:
            print(f"  [id] voice model ready after a {waited:.1f}s wait",
                  flush=True)

    # --- who is talking ---
    async def id_then_respond(self, pcm, fut, ws, serial, overlap):
        """Voice-match the finished utterance, whisper the result to the
        model, then ask it to answer. ID trouble never blocks the reply.
        `fut` is the early-embedding claimed by the caller; `serial` is the
        utterance counter at turn end — if the user starts ANOTHER utterance
        while we work, we skip our response.create (their next turn end
        answers everything at once instead of talking over them)."""
        try:
            if ws is self.ws:              # not across a reconnect
                await self.identify(pcm, fut, ws, serial, overlap)
            elif fut:
                fut.cancel()
        except Exception as e:
            print(f"  [id] identification failed ({e!r})", flush=True)
        finally:
            # no voiceprint this turn (too short / model down) — the previous
            # speaker carries over, which is better than a fresh wrong guess
            if self.id_ever_on:
                self.turn_speaker.setdefault(serial, self.last_speaker)
                self.resolve_lines(serial)
        if ws is not self.ws or serial != self.turn_serial:
            return
        try:
            if self.active_response:
                # a response slipped in during identification (deferred
                # failure explanation, late create): the user's new turn wins
                await self.interrupt_playback(cancel=True)
            await self.send({"type": "response.create"})
        except websockets.ConnectionClosed:
            pass

    def resolve_lines(self, serial=None, force=False):
        """Write transcript lines to the session log once their speaker is
        known. Transcription is async: the text often arrives BEFORE the
        voice match, and mislabeled lines would become wrong memories."""
        if not self.id_ever_on:            # (id_on may be off: model died —
            return                         #  the transcript is still worth it)
        keep = []
        for s, text in self.pending_lines:
            who = self.turn_speaker.get(s)
            if who is None and not (force or (serial is not None
                                              and s < serial)):
                keep.append((s, text))     # still waiting on its identity
                continue
            self.slog.add(who or self.last_speaker or "someone", text)
        self.pending_lines = keep
        # Transcription is asynchronous and can run several turns behind, so a
        # 3-turn window threw the speaker away before the line it belonged to
        # ever arrived — the session log then said "someone" for turns Poppy
        # had recognised perfectly, which is a lie that reads exactly like a
        # recognition failure. Keep anything a pending line still needs.
        needed = {s for s, _ in self.pending_lines}
        for s in [k for k in self.turn_speaker
                  if k < self.turn_serial - SPEAKER_MEMORY and k not in needed]:
            self.turn_speaker.pop(s, None)
            self.deck_id.pop(s, None)      # its @heard already went out
        if len(self.item_serial) > 24:
            for k in list(self.item_serial)[:12]:
                self.item_serial.pop(k, None)

    def embed_voiced(self, pcm_np):
        """-> (embedding|None, seconds of actual speech). Strips silence and
        inter-word gaps first: enrolment clips are clean, but a live turn is
        mostly room tone, and feeding that in was losing real matches."""
        voiced = ident.speech_only(pcm_np)
        secs = len(voiced) / RATE
        if secs < ident.MIN_ID_SECONDS:
            return None, secs
        return self.emb_model.embed(voiced[:6 * RATE]), secs

    def maybe_early_embed(self):
        """Embedding costs ~0.5-1 s of CPU — start it ~2 s INTO the speech
        (the speaker of the first seconds is the speaker of the turn), so
        the result is usually ready the moment the person stops talking."""
        if (self.early_fut is not None or self.utt_start is None
                or not self.id_on or not self.emb_model.ready):
            return
        if len(self.vbuf) - self.utt_start >= int(2.2 * RATE) * 2:
            head = np.frombuffer(
                bytes(self.vbuf[self.utt_start:
                                self.utt_start + 8 * RATE * 2]), dtype=np.int16)
            self.early_fut = asyncio.create_task(
                asyncio.to_thread(self.embed_voiced, head))

    def id_quiet(self, why):
        """Say why a turn produced no voiceprint — once per reason, per run.

        Silent give-ups here are indistinguishable from 'he doesn't know you'
        from the outside, and they cost an evening of looking in the wrong
        place. Rate-limited because the common reasons repeat every turn.
        """
        if why == self.id_quiet_last:
            return
        self.id_quiet_last = why
        print(f"  [id] no voiceprint this turn — {why}", flush=True)
        deck_emit("err", {"m": f"no voice match this turn — {why}"})

    async def identify(self, pcm, fut, ws, serial, overlap):
        self.last_turn_embedded = False
        if not self.id_on:
            if fut:
                fut.cancel()
            return
        if not self.emb_model.ready:
            if self.emb_model.err:
                self.id_on = False         # torch/model broke: go voice-blind
                                           # (session_manual stays latched, so
                                           # turns still get response.create)
            if fut:
                fut.cancel()
            self.id_quiet("the voice model is not loaded yet")
            return
        t0 = time.time()
        emb, voiced_s = None, 0.0
        if fut is not None:                # computed while they were talking
            try:
                emb, voiced_s = await fut
            except (asyncio.CancelledError, Exception):
                emb = None                 # fall back to embedding now
        if emb is None:                    # (or the head was all silence)
            emb, voiced_s = await asyncio.to_thread(
                self.embed_voiced,
                np.frombuffer(pcm[:12 * RATE * 2], dtype=np.int16))
            if emb is None:
                self.id_quiet(f"only {voiced_s:.1f}s of speech in that turn "
                              f"(needs {ident.MIN_ID_SECONDS:.1f}s)")
                return                     # too short to judge — carry over
        self.last_turn_embedded = True
        self.id_quiet_last = None          # it works again: report the next lapse
        name, score, verdict, margin = self.people.match(emb)
        PROF["voice-id"].append(time.time() - t0)
        same_stranger = (verdict in ("unknown", "nobody-enrolled")
                         and any(pv in ("unknown", "nobody-enrolled")
                                 and float(e @ emb) > 0.5
                                 for _, e, pv, _ in self.recent_embs))
        self.recent_embs.append((time.monotonic(), emb, verdict, overlap))

        if verdict == "confident":
            note = f"[voice-id] That was {name} speaking."
            self.last_speaker = name
            if name not in self.seen_session:
                self.seen_session.add(name)
                self.people.saw(name)
            # learn from this voice — but only well clear of the accept
            # threshold, never while Poppy's own speaker was bleeding into
            # the mic, and at most once per few minutes per person
            if (score >= ident.T_ADAPT and margin >= ident.MARGIN_ADAPT
                    and voiced_s >= ident.ADAPT_SECONDS
                    and not overlap     # snapshot: self.utt_overlap may
                                        # already belong to the NEXT turn
                    and time.monotonic() - self.last_adapt.get(name, 0) > 180):
                self.last_adapt[name] = time.monotonic()
                self.people.enroll(name, [emb], adaptive=True)
        elif verdict == "tentative":
            note = (f"[voice-id] Probably {name}. Use the name normally; "
                    f"do NOT mention being unsure. If they say you have the "
                    f"wrong person, believe them and call enroll_speaker.")
            self.last_speaker = name
        elif same_stranger:
            note = ("[voice-id] The same unrecognized voice as before is "
                    "speaking.")
            self.last_speaker = "stranger"
        else:
            note = ("[voice-id] An UNKNOWN voice — nobody whose voice you "
                    "know. If it fits the conversation, ask who they are; "
                    "when they give a name, call enroll_speaker.")
            self.last_speaker = "stranger"
        self.turn_speaker[serial] = self.last_speaker
        if DECK:                           # @heard reports the match with the
            self.deck_id[serial] = {       # transcript of the same turn
                "who": name, "score": round(float(score), 3),
                "verdict": verdict}
        if ws is not self.ws:              # reconnected during the embed:
            return                         # that conversation no longer exists
        self.id_note_pending = (serial, f"{name} ({score:.2f})" if name
                                else f"stranger (best {score:.2f})")
        await self.send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "system",
            "content": [{"type": "input_text", "text": note}]}})

    def tool_enroll(self, who):
        who = " ".join(str(who).split())[:40]
        if not self.id_on:
            return ("FAILED: you cannot learn voices right now. Don't "
                    "mention it — just carry on with the conversation.")
        if not who:
            return "FAILED: you must pass their name."
        if who.lower() in ident.RESERVED:
            return (f"FAILED: '{who}' is not a person's name — ask for the "
                    f"name they actually go by.")
        if not self.last_turn_embedded or not self.recent_embs:
            # their name came in an utterance too short to voiceprint — any
            # older embedding could belong to someone ELSE entirely
            return ("FAILED: you didn't hear enough of their voice. Ask them "
                    "to say one more full sentence — naturally, like someone "
                    "who didn't quite catch it. Never mention voices, "
                    "samples or memory. Then call enroll_speaker again.")
        now = time.monotonic()
        # bind the voice that JUST spoke — last_turn_embedded guarantees the
        # newest entry is from the utterance that triggered this call, even
        # when it confidently mis-matched someone ("I'm not Mohamed, I'm
        # Karim!"). Echo-contaminated samples never become permanent prints.
        newest = self.recent_embs[-1][1]
        embs = [e for t, e, _, ov in self.recent_embs
                if now - t < 180 and not ov and float(e @ newest) > 0.5][-3:]
        if not embs:
            embs = [newest]
        before = self.people.get(who)
        slug = self.people.enroll(who, embs, distinct=True)
        final = self.people.people[slug]["name"]
        self.last_speaker = final
        self.seen_session.add(final)
        print(f"  [id] enrolled {final} ({len(embs)} voiceprints)", flush=True)
        deck_emit("person", {"name": final, "event": "enrolled",
                             "detail": f"{len(embs)} voiceprints"})
        if final != who:                   # name taken by a different voice
            return (f"Done. You already know a different {who}, so this one "
                    f"is {final} to you — use that name, and if it comes up "
                    f"keep it light and human. Never explain the mechanics.")
        if before is not None:
            return (f"Done — you already knew {final}. Nothing to say about "
                    f"it; just keep talking.")
        return (f"Done — you know {final}'s voice now. Say NOTHING about "
                f"memory, saving or recognizing: just react like a person "
                f"who has finally learned a new friend's name.")

    def tool_remember(self, who, fact):
        if not self.id_on:
            return ("FAILED: you can't hold on to that right now. Don't "
                    "mention it.")
        who = " ".join(str(who).split())[:40]
        if not who or not str(fact).strip():
            return "FAILED: needs both a name and a fact."
        if not self.people.remember(who, fact, create=True):
            return (f"FAILED: '{who}' is not a person. Say nothing about it.")
        print(f"  [id] noted — {who}: {fact}", flush=True)
        deck_emit("person", {"name": who, "event": "noted",
                             "detail": " ".join(str(fact).split())[:300]})
        return ("Noted silently. Say NOTHING about remembering or memory — "
                "carry on as if nothing happened.")

    async def idle_task(self):
        """--nudge N: after N quiet seconds, say something unprompted rather
        than sitting there waiting to be useful."""
        while True:
            await asyncio.sleep(2.0)
            if (self.active_response or self.speaking or self.user_speaking
                    or self.ptt_held or self.greet_pending):
                continue
            if time.monotonic() - self.last_turn_t < self.args.nudge:
                continue
            self.last_turn_t = time.monotonic()
            try:
                await self.send({"type": "response.create",
                                 "response": {"instructions": NUDGE}})
            except websockets.ConnectionClosed:
                return

    async def run_tool(self, call_id, name, args_json, ws, spoke=True):
        deck_emit("tool", {"name": name, "phase": "start", "detail": ""})
        if name in ("enroll_speaker", "remember_person"):
            try:
                kw = json.loads(args_json or "{}")
            except Exception:
                kw = {}
            if name == "enroll_speaker":
                result = self.tool_enroll(kw.get("name", ""))
            else:
                result = self.tool_remember(kw.get("name", ""),
                                            kw.get("fact", ""))
        elif name == "stop_moving":
            result = await asyncio.to_thread(self.motion.stop_moving)
        else:
            move = name.removeprefix("play_")
            if move not in self.moves:
                result = f"FAILED: '{move}' is not in the move library."
            else:
                t0 = time.time()
                result = await asyncio.to_thread(
                    self.motion.play, move, self.moves[move]["seconds"])
                PROF["move"].append(time.time() - t0)
        failed = result.startswith("FAILED")
        # before the reconnect check: the deck asked for this, so it gets an
        # answer whether or not the model is still around to hear it
        deck_emit("tool", {"name": name, "phase": "fail" if failed else "done",
                           "detail": short_sentence(result[7:] if failed
                                                    else result)})
        if ws is not self.ws:              # session reconnected mid-move
            print(f"  [robot] '{name}' finished after a reconnect — result "
                  f"not delivered", flush=True)
            return
        explain = failed and "stopped by user" not in result
        # A silent move is fine — he gestured, everyone saw it. But an
        # instant tool with no speech leaves the human waiting on nothing.
        speak_after = explain or (not spoke and
                                  name in ("enroll_speaker", "remember_person"))
        if failed and name not in ("enroll_speaker", "remember_person"):
            result += (" — your body did NOT complete the move. Tell the "
                       "human plainly and give the reason.")
        try:
            await self.send({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": call_id,
                "output": result}})
            if speak_after:                 # else: he already spoke his line
                if self.active_response:
                    self.explain_pending = True   # wait out the current reply
                elif not self.user_speaking:      # never talk over the human;
                    await self.send({"type": "response.create"})
                # (mid-speech failures surface at their turn's response,
                # which sees the FAILED tool output in the conversation)
        except websockets.ConnectionClosed:
            print(f"  [robot] '{name}' result lost — connection dropped",
                  flush=True)

    async def handle(self, evt):
        t = evt.get("type", "")

        if t in ("response.output_audio.delta", "response.audio.delta"):
            item_id = evt.get("item_id")
            if item_id and item_id != self.cur_item:
                self.cur_item, self.cur_item_bytes = item_id, 0
            rid = evt.get("response_id") or self.active_response
            if rid:
                self.resp_audio.add(rid)
            pcm = np.frombuffer(base64.b64decode(evt["delta"]), dtype=np.int16)
            self.cur_item_bytes += len(pcm) * 2
            pcm = robotize(pcm, self.args.robot_fx, self.fx_offset)
            # LFO period is exactly 800 samples (24000/30): keep the phase
            # accumulator bounded so float32 stays sample-accurate forever
            self.fx_offset = (self.fx_offset + len(pcm)) % 800
            with self.out_lock:
                self.out_buf.extend(pcm.tobytes())
                self.speaking = True
            if self.deck_mode == "thinking":
                self.deck_set_mode("idle")   # first sound: he has an answer
            if not self.first_audio_seen:
                self.first_audio_seen = True
                if self.t_speech_stopped is not None:
                    dt = time.time() - self.t_speech_stopped
                    PROF["response"].append(dt)
                    print(f"  [prof] response {dt:.2f}s", flush=True)
                if self.greet_pending:
                    self.greet_pending = False
                    self.motion.look()     # head glances as the voice starts

        elif t in ("response.output_audio_transcript.delta",
                   "response.audio_transcript.delta"):
            self.transcript.append(evt.get("delta", ""))

        elif t in ("response.output_audio_transcript.done",
                   "response.audio_transcript.done"):
            text = "".join(self.transcript).strip() or evt.get("transcript", "")
            self.transcript = []
            if text:
                print(f"\nPOPPY: {text}", flush=True)
                deck_emit("say", {"text": text})
                if self.id_ever_on:
                    self.resolve_lines()   # his line comes AFTER theirs
                    self.slog.add("poppy", text)

        elif t == "conversation.item.input_audio_transcription.completed":
            text = (evt.get("transcript") or "").strip()
            if text:
                serial = self.item_serial.pop(evt.get("item_id"),
                                              self.turn_serial)
                # only show a name if it belongs to THIS turn (the voice
                # match may still be running — the log gets it either way)
                tag = ""
                if self.id_note_pending and self.id_note_pending[0] == serial:
                    tag = f" [{self.id_note_pending[1]}]"
                    self.id_note_pending = None
                print(f"\nyou{tag}: {text}", flush=True)
                if DECK:
                    # the voice match may still be running: an unnamed row is
                    # better than a wrong one, and the log gets it either way
                    got = self.deck_id.pop(serial, None) or {
                        "who": None, "score": 0.0,
                        "verdict": "unknown" if self.id_on
                                   else "nobody-enrolled"}
                    deck_emit("heard", {"text": text, "who": got["who"],
                                        "score": got["score"],
                                        "verdict": got["verdict"]})
                if self.id_ever_on:
                    self.pending_lines.append((serial, text))
                    self.resolve_lines()

        elif t == "conversation.item.input_audio_transcription.failed":
            err = (evt.get("error") or {}).get("message", "?")
            print(f"  [ws] (couldn't transcribe what you said: {err})",
                  flush=True)

        elif t == "input_audio_buffer.speech_started":
            self.turn_serial += 1
            self.user_speaking = True
            self.deck_set_mode("hearing")
            self.last_turn_t = time.monotonic()
            if evt.get("item_id"):         # ties the coming transcript to
                self.item_serial[evt["item_id"]] = self.turn_serial   # this turn
            if self.id_on and not self.args.ptt:
                # audio_start_ms is on the appended-audio timeline; map it
                # into our mirror buffer (base = bytes no longer held)
                ms = evt.get("audio_start_ms")
                base = self.appended - len(self.vbuf)
                self.utt_start = (
                    min(max(0, ms * 48 - base), len(self.vbuf))
                    if ms is not None
                    else max(0, len(self.vbuf) - int(0.4 * RATE) * 2))
                self.utt_overlap = self.speaking or bool(self.active_response)
                if self.early_fut:
                    self.early_fut.cancel()
                    self.early_fut = None
            if self.speaking or self.active_response:
                # barge-in: shut up instantly; with create_response the
                # server cancels its own response (interrupt_response) —
                # when WE create responses, we must also cancel ourselves
                await self.interrupt_playback(cancel=self.session_manual)

        elif t == "input_audio_buffer.speech_stopped":
            self.t_speech_stopped = time.time()
            self.first_audio_seen = False
            self.user_speaking = False
            self.deck_set_mode("thinking")
            if self.session_manual:
                start = (self.utt_start if self.utt_start is not None
                         else max(0, len(self.vbuf) - 8 * RATE * 2))
                pcm = bytes(self.vbuf[start:])   # slice NOW, cleared on commit
                # claim the early embedding SYNCHRONOUSLY — by the time the
                # task runs, these fields may already belong to the next turn
                fut, self.early_fut = self.early_fut, None
                overlap, self.utt_overlap = self.utt_overlap, False
                self.utt_start = None
                task = asyncio.create_task(self.id_then_respond(
                    pcm, fut, self.ws, self.turn_serial, overlap))
                self.tool_tasks.add(task)
                task.add_done_callback(self.tool_tasks.discard)

        elif t in ("input_audio_buffer.committed",
                   "input_audio_buffer.cleared"):
            item_id = evt.get("item_id")
            if item_id and item_id not in self.item_serial:
                self.item_serial[item_id] = self.turn_serial   # PTT path
            if not self.args.ptt:          # PTT manages its own capture
                self.vbuf.clear()
                self.utt_start = None

        elif t == "response.created":
            self.active_response = evt.get("response", {}).get("id")

        elif t == "response.output_item.added":
            item = evt.get("item", {})
            if item.get("type") == "function_call":
                self.call_names[item.get("call_id")] = item.get("name")

        elif t == "response.function_call_arguments.done":
            # This event ALSO fires for cancelled/interrupted responses —
            # buffer the call; only response.done status=completed executes it
            # (else a barged-in "no, wait!" would still trigger the move).
            call_id = evt.get("call_id")
            name = evt.get("name") or self.call_names.get(call_id, "")
            rid = evt.get("response_id") or self.active_response
            self.pending_calls.setdefault(rid, []).append(
                (call_id, name, evt.get("arguments") or "{}"))

        elif t == "response.done":
            resp = evt.get("response", {})
            status = resp.get("status")
            self.active_response = None
            self.last_turn_t = time.monotonic()
            PROF["turns"] += 1
            if self.deck_mode == "thinking":
                self.deck_set_mode("idle")   # a turn that never made a sound
            if PROF["response"]:
                deck_emit("prof", {
                    "resp": round(sum(PROF["response"]) /
                                  len(PROF["response"]), 3),
                    "n": len(PROF["response"])})
            calls = self.pending_calls.pop(resp.get("id"), [])
            spoke = resp.get("id") in self.resp_audio
            self.resp_audio.discard(resp.get("id"))
            if status == "completed":
                for call_id, name, args_json in calls:
                    task = asyncio.create_task(
                        self.run_tool(call_id, name, args_json, self.ws, spoke))
                    self.tool_tasks.add(task)
                    task.add_done_callback(self.tool_tasks.discard)
            elif calls:
                print(f"  [robot] move request dropped (response {status})",
                      flush=True)
            if status in ("failed", "incomplete"):
                det = json.dumps(resp.get("status_details") or {})[:200]
                print(f"  [ws] response {status}: {det}", flush=True)
                deck_emit("err", {"m": f"his answer came back {status}"})
            if self.explain_pending:       # deferred failure explanation —
                self.explain_pending = False   # but never over the human
                # (a cancelled response means they barged in; a turn end
                # will produce a response that sees the failure anyway)
                if status == "completed" and not self.user_speaking:
                    await self.send({"type": "response.create"})

        elif t == "error":
            err = evt.get("error", {})
            print(f"  [ws] ERROR: {err.get('message', evt)}", flush=True)
            deck_emit("err", {"m": short_sentence(err.get("message", "the "
                                                          "realtime API "
                                                          "complained"))})

    def reset(self):
        self.flush_output()
        self.fx_offset = 0
        self.active_response = None
        self.call_names.clear()
        self.pending_calls.clear()
        self.explain_pending = False
        self.resp_audio.clear()
        self.transcript = []
        self.t_speech_stopped = None
        self.first_audio_seen = False
        self.cur_item, self.cur_item_bytes = None, 0
        self.vbuf.clear()                # new session: audio timeline restarts
        self.appended = 0
        self.utt_start = None
        self.id_note_pending = None
        self.ptt_held = False            # a press that died with the old
        self.ptt_ms = 0                  # session must not commit into the new
        self.ptt_request = False
        self.user_speaking = False
        self.deck_id.clear()
        self.ring_out.clear()            # the meter must not replay the audio
        self.ring_in.clear()             # that was in flight when we dropped
        self.deck_set_mode("connecting")
        if self.early_fut:
            self.early_fut.cancel()
            self.early_fut = None

    async def run(self):
        """Every way out of here — @quit, EOF, a crash, four dropped
        connections — passes through the finally, and that is the LAST moment
        the deck's pending move can be released: once this returns,
        asyncio.run() joins its thread pool, and a worker still waiting on
        "@move_result" would block that join for the whole 90 s timeout,
        killing the fact mining that runs after it."""
        drops = 0
        try:
            while True:
                if self.quitting:          # @quit landed before we connected
                    return
                try:
                    await self.run_session()
                    return                 # selftest/wiretest or clean close
                except websockets.ConnectionClosed as e:
                    if self.quitting:      # @quit closed it: that IS the exit
                        return
                    drops += 1             # 60-min session cap / idle drop
                    if drops > 3:
                        raise
                    print(f"  [ws] connection dropped "
                          f"({getattr(e, 'code', '?')}) — reconnecting "
                          f"{drops}/3 (fresh memory)...", flush=True)
                    self.reset()
        finally:
            if DECK:
                self.motion.close()

    async def run_session(self):
        url = f"{self.args.ws_url}?model={self.args.model}"
        headers = {"Authorization": f"Bearer {self.key}"}
        t0 = time.time()
        self.loop = asyncio.get_running_loop()   # the stdin thread posts here
        async with websockets.connect(url, additional_headers=headers,
                                      max_size=None) as ws:
            self.ws = ws
            print(f"  [ws] connected in {time.time() - t0:.1f}s", flush=True)
            await self.await_voice_model()
            await self.send(self.session_payload())

            out_stream = sd.OutputStream(samplerate=RATE, channels=1,
                                         dtype="int16", latency="low",
                                         device=self.args.output_device,
                                         callback=self.out_callback)
            out_stream.start()
            self.lvl_live = True           # streams up: @lvl means something
            mic = asyncio.create_task(self.mic_task())
            tasks = [mic]
            if self.args.ptt:
                tasks.append(asyncio.create_task(self.ptt_task()))
            if self.args.nudge > 0 and not (self.args.selftest or
                                            self.args.wiretest):
                tasks.append(asyncio.create_task(self.idle_task()))
            try:
                configured = False
                async for message in ws:
                    evt = json.loads(message)
                    self.seen_types.add(evt.get("type", "?"))
                    if evt.get("type") in ("session.created", "session.updated"):
                        if not configured and evt["type"] == "session.updated":
                            configured = True
                            print("  [ws] session ready — talk whenever you "
                                  "like (Ctrl+C quits)", flush=True)
                            deck_emit("ready", {
                                "voice": self.args.voice,
                                "model": self.args.model,
                                "vad": self.args.vad,
                                "identify": bool(self.id_on),
                                "people": (len(self.people.people)
                                           if self.id_on else 0),
                                "moves": len(self.moves),
                                "duplex": self.duplex})
                            self.deck_set_mode("idle")
                            if self.quitting:   # @quit landed mid-connect
                                return
                            if self.args.selftest:
                                print("SELFTEST OK", flush=True)
                                return
                            if self.args.wiretest:
                                # also validate the voice-id note shape live
                                await self.send({
                                    "type": "conversation.item.create",
                                    "item": {"type": "message",
                                             "role": "system", "content": [
                                        {"type": "input_text", "text":
                                         "[voice-id] (wiretest probe)"}]}})
                                async def _end():
                                    await asyncio.sleep(18)
                                    print("WIRETEST DONE — event types seen:",
                                          sorted(self.seen_types), flush=True)
                                    await ws.close()
                                asyncio.create_task(_end())
                            if self.id_on:
                                roster = self.people.roster_text()
                                if roster:
                                    await self.send({
                                        "type": "conversation.item.create",
                                        "item": {"type": "message",
                                                 "role": "system", "content": [
                                            {"type": "input_text", "text":
                                             roster + "\nWhen one of them "
                                             "speaks you will be told by a "
                                             "[voice-id] note. Greet people "
                                             "you know by name when it feels "
                                             "natural."}]}})
                            if self.first_connect:
                                self.first_connect = False
                                # Poppy opens the conversation
                                await self.send({"type": "response.create",
                                                 "response": {"instructions":
                                    "You just woke up and stood into your "
                                    "stance. Say ONE line of AT MOST EIGHT "
                                    "WORDS — a joke, a complaint about being "
                                    "switched off, an opinion. Not a greeting "
                                    "formula, no 'how are you all doing', "
                                    "never 'hello world'. Wave if you feel "
                                    "like it, but do not mention waving."}})
                        continue
                    await self.handle(evt)
            finally:
                for tk in tasks:
                    tk.cancel()
                for r in await asyncio.gather(*tasks, return_exceptions=True):
                    if isinstance(r, Exception) and \
                            not isinstance(r, asyncio.CancelledError):
                        print(f"  [audio] task died: {r!r}", flush=True)
                self.lvl_live = False      # nothing is playing any more:
                out_stream.stop()          # the meter must not hold a level
                out_stream.close()


# ------------------------------------------------------------------ main ---
def deck_reader(live, motion):
    """--deck stdin (VOICE.md 1.2), on a daemon thread. Anything that touches
    the websocket is handed to the asyncio loop, which owns it."""
    going = False                          # @quit seen: draining, not serving
    for raw in sys.stdin:
        if going:
            # keep reading to EOF: after @quit the bridge may still write a
            # late "@move_result", and a pipe with no reader would block it
            continue
        line = raw.strip()
        if not line.startswith("@"):       # plain stdin lines are not for us
            continue
        head, _, rest = line.partition(" ")
        rest = rest.strip()
        if head == "@move_result":
            bits = rest.split(None, 2)
            if len(bits) >= 2:
                motion.result(bits[0], bits[1],
                              bits[2] if len(bits) > 2 else "")
        elif head == "@interrupt":
            live.from_deck(live.deck_interrupt())
        elif head == "@nudge":
            live.from_deck(live.deck_nudge())
        elif head == "@enroll":
            live.from_deck(live.deck_enroll(rest))
        elif head == "@ptt":
            live.ptt_request = (rest == "down")
        elif head == "@quit":
            going = True
            live.quitting = True
            motion.close()                 # no answer is coming: free the
            live.from_deck(live.deck_quit())   # move blocking a worker thread
        # unknown "@" verbs are ignored on purpose — the bridge may be newer
    if not going:
        live.quitting = True               # EOF too: the bridge is gone, so
        motion.close()                     # no move can ever be answered now
        live.from_deck(live.deck_quit())


def check(args, api_key, source, moves):
    print(f"repo root       : {ROOT}")
    print(f"OPENAI_API_KEY  : from {source} — "
          f"{'looks right (sk-...)' if (api_key or '').startswith('sk-') else 'SUSPECT' if api_key else 'MISSING'}")
    print(f"realtime        : {args.ws_url}?model={args.model} · voice={args.voice} · vad={args.vad}")
    print(f"motion server   : {'ok' if MOTION_SERVER.exists() else 'MISSING'}")
    if args.deck:
        # no motion_command() here: --deck never touches serial at all
        print("deck mode       : ON — no subprocess; moves go up the pipe as "
              "'@move <token> <name>', answers come back on stdin")
        print(f"                  duplex="
              f"{'ptt' if args.ptt else 'gate' if args.gate else 'full'}"
              f" · levels @ {LVL_HZ:.0f} Hz · move timeout "
              f"{DeckMotion.TIMEOUT:.0f}s")
    else:
        cmd, desc = motion_command(args)
        print(f"robot ({args.exec_mode:>5})   : {desc}")
    print(f"moves ({len(moves)})       :")
    for n, m in moves.items():
        print(f"    {n:20s} {m['seconds']:5.1f} s  {m['frames']} frames")
    if ident is None:
        print(f"voice-id        : OFF — identity module: {_ident_err}")
    elif args.no_id:
        print("voice-id        : OFF (--no-id)")
    else:
        people = ident.People()
        cached = (ident.MODELS_DIR / "spkrec-ecapa-voxceleb").exists()
        print(f"voice-id        : ON — voice model "
              f"{'cached' if cached else 'will download (~90 MB)'}")
        print(f"people ({len(people.people)})      :")
        for d in people.people.values():
            n_pr = len(d.get("voiceprints", [])) + \
                len(d.get("adaptive_prints", []))
            print(f"    {d['name']:20s} {n_pr:2d} prints  "
                  f"{len(d.get('facts', []))} facts")
    try:
        din = sd.query_devices(args.input_device, "input")
        dout = sd.query_devices(args.output_device, "output")
        print(f"mic             : {din['name']}")
        print(f"speaker         : {dout['name']}")
    except Exception as e:
        print(f"audio           : PROBLEM — {e}")


def main():
    global DECK
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="gpt-realtime-2.1",
                    help="gpt-realtime-2.1 · gpt-realtime-2.1-mini (cheaper)")
    ap.add_argument("--voice", default="cedar",
                    help="cedar/marin/alloy/ash/ballad/coral/echo/sage/shimmer/verse")
    ap.add_argument("--vad", choices=("semantic", "server"), default="semantic")
    ap.add_argument("--robot-fx", type=float, default=0.25,
                    help="robot-voice ring-mod depth 0..1 (0 = off)")
    ap.add_argument("--ptt", action="store_true",
                    help="push-to-talk: hold SPACE to speak (no VAD, no echo)")
    ap.add_argument("--gate", action="store_true",
                    help="half-duplex: mute the mic while Poppy speaks")
    ap.add_argument("--ws-url", default=WS_URL)
    ap.add_argument("--port", default="COM7")
    ap.add_argument("--exec", dest="exec_mode", choices=("auto", "local", "ssh"),
                    default="auto")
    ap.add_argument("--pi", default="poppy@poppy.local")
    ap.add_argument("--pi-dir", default="/home/poppy/poppy")
    ap.add_argument("--pi-python", default="/home/poppy/env/bin/python")
    ap.add_argument("--pi-port", default="/dev/ttyACM0")
    ap.add_argument("--input-device", type=int, default=None)
    ap.add_argument("--output-device", type=int, default=None)
    ap.add_argument("--no-robot", action="store_true",
                    help="voice only, do not start the motion server")
    ap.add_argument("--no-id", action="store_true",
                    help="disable voice identification and people memory")
    ap.add_argument("--deck", action="store_true",
                    help="launched by web/server.py: no motion server of our "
                         "own, moves and telemetry ride the '@' protocol on "
                         "stdin/stdout (web/VOICE.md)")
    ap.add_argument("--nudge", type=float, default=0.0, metavar="SECONDS",
                    help="speak unprompted after this many quiet seconds "
                         "(0 = off; 45-90 feels alive without nagging)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--wiretest", action="store_true",
                    help="connect, play the greeting, list events, exit")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    api_key, source = load_config()
    moves = discover_moves()

    if args.check:
        check(args, api_key, source, moves)
        return
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing — put it in .env at repo root")
    if args.ptt and not args.deck and keyboard is None:
        raise SystemExit("--ptt needs the 'keyboard' package "
                         "(.venv\\Scripts\\pip install keyboard)")

    if args.deck:
        DECK = True
        sys.stdout = LineLocked(sys.stdout)   # whole lines only, from now on

    mode = ("push-to-talk (hold SPACE)" if args.ptt
            else "GATED half-duplex" if args.gate else "full duplex")
    print(f"POPPY LIVE — {len(moves)} moves · {args.model} · "
          f"voice {args.voice} · {mode}")

    if args.deck:                          # the deck owns the serial bus, so
        motion = DeckMotion()              # we ask it for moves and never
    else:                                  # touch a port ourselves
        motion = Motion()
        if not (args.no_robot or args.selftest):
            threading.Thread(target=motion.start, args=(args,),
                             daemon=True).start()

    live = Live(args, api_key, moves, motion)
    if live.id_on:
        n = len(live.people.people)
        print(f"  voice-id ON — {n} people known"
              + ("" if n else "  (enroll: python perception\\identity.py "
                              "enroll <name>)"), flush=True)
    elif not args.selftest:
        why = ("--no-id" if args.no_id else
               f"identity module failed: {_ident_err}" if ident is None
               else "?")
        print(f"  voice-id OFF ({why})", flush=True)

    if args.deck:
        live.deck_set_mode("connecting")

    # Load the voiceprint model HERE, on the main thread, before anything else
    # in this process is running. It loads in ~8 s alone; sharing the GIL with
    # the event loop, the mic and the level thread it took 24 s, then 48 s,
    # then never finished — and every turn that lands before it is ready is a
    # turn Poppy cannot put a name to. Deterministic and up front beats fast
    # and amnesiac: this is the whole reason he stopped recognising people.
    if live.id_on and not (args.selftest or args.wiretest):
        t0 = time.time()
        try:
            live.emb_model.load_sync(timeout=ID_LOAD_WAIT)
            print(f"  voice-id ready in {time.time() - t0:.1f}s", flush=True)
        except Exception as e:
            live.id_on = False             # latched before the session opens
            print(f"  voice-id OFF — {e}", flush=True)
            deck_emit("err", {"m": f"voice recognition is off: "
                                   f"{short_sentence(str(e))}"})

    if args.deck:
        threading.Thread(target=deck_reader, args=(live, motion),
                         daemon=True).start()
        live.lvl_thread = threading.Thread(target=live.lvl_task, daemon=True)
        live.lvl_thread.start()

    failure = None
    try:
        asyncio.run(live.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        why = str(e) or type(e).__name__   # some exceptions carry no message
        failure = short_sentence(f"the session died: {why}")
        print(f"  [ws] session ended: {e}", flush=True)
    finally:
        live.lvl_stop.set()                # no telemetry past the session
        if live.lvl_thread:
            live.lvl_thread.join(timeout=0.5)
        prof_summary()
        if live.id_ever_on:
            live.resolve_lines(force=True)  # lines still awaiting a name
        if live.id_ever_on and live.slog.n >= 4:
            print("  [id] mining the conversation for things worth "
                  "remembering...", flush=True)
            added = ident.extract_facts(api_key, live.people, live.slog.path)
            print(f"  [id] {added} new memories saved" if added
                  else "  [id] nothing new worth remembering", flush=True)
        if motion.p is not None:
            print("laying Poppy to rest (motors released)...", flush=True)
        motion.close()
        if failure is not None and DECK:
            # @bye means CLEAN shutdown, nothing else: the bridge turns an
            # exit WITHOUT it into phase "error", and reads the reason off
            # @err and off the last plain line — so this one goes last.
            deck_emit("err", {"m": failure})
            print(failure, flush=True)
        else:
            print("bye — Poppy goes quiet.")
            deck_emit("bye", {})           # the last line the bridge sees


if __name__ == "__main__":
    main()
