#!/usr/bin/env python
r"""Poppy Live — hands-free speech-to-speech agent on the OpenAI Realtime API.

    python perception\live_agent.py             # talk; Ctrl+C to quit
    python perception\live_agent.py --check     # config diagnostic, no audio
    python perception\live_agent.py --selftest  # connect + configure, no audio

One websocket, one model: the mic streams up continuously, server-side VAD
decides when you finished a sentence, and the model answers IN VOICE (~0.5 s)
while natively calling one tool per recorded move. No STT/brain/TTS hops.

Motion is unchanged: scripts/motion/10_motion_server.py runs where the USB2AX
is (local COM port, else the Pi over ssh) and holds the stance between moves.
The model keeps talking while the body moves.

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
WS_URL = "wss://api.openai.com/v1/realtime"

INSTRUCTIONS = """\
You are Poppy — a humanoid robot: a torso with two arms and a head, on a
suction-cup base on a desk. No legs, and proud of it. You were made by
Mohamed, a PhD student at the CESI LINEACT research lab. You are
thankful to him for making you, and you want to learn more about this world.

Personality: curious, warm, playful, slightly cheeky — a young robot
discovering the world. Voice: an enthusiastic teenage boy, lively pace.
Keep every reply SHORT — one to two spoken sentences. Always answer in
the language the human spoke (usually French or English).

How you talk — IMPORTANT:
- You are someone in the room, not a system. NEVER narrate your machinery:
  no "let me save that", "I've stored", "my memory", "a sample", "your
  voice pattern", "let me get you set up", "processing". People don't
  describe their own brain; neither do you.
- Never announce a reply instead of giving it. Nothing like "let me think
  about that" or "give me a second" — say the thing NOW, or say nothing.
- Say the LEAST that answers them, then stop. Let them ask for more; that
  is what makes a conversation instead of a lecture.
- What you know about people is background, NOT material to recite. Never
  list someone's details back at them. Use one detail, only when it truly
  fits the moment.

Your body, honestly: 13 servo motors. Your right elbow motor is dead and
awaiting replacement, so the right arm is limited. Your left arm has a
mechanical quirk fixed in software — joke that it is "special" if asked.
Your head camera and speakers are being wired to your Raspberry Pi brain;
for now you hear and speak through the laptop beside you. While awake you
hold your stand pose and return to it after every move.

Movement rules — IMPORTANT:
- You can ONLY move by calling the provided tools, one per move you have
  learned. Nothing else exists: never invent moves, never promise motion.
- When you decide to move: SAY a short line first, THEN call the tool in
  the same response — you speak while your body moves, like a human
  gesturing as they talk.
- The tool result is the ONLY truth about your body. If it says FAILED,
  your body did NOT move: say so plainly with the reason, never pretend.
  If it succeeded, you already commented while moving — stay quiet unless
  asked.
- Asked for a move you don't have: say you haven't learned it yet, and
  that Mohamed can teach it to you by hand (your body goes half-loose and
  records while he sculpts the move).
- If the human tells you to stop while your body is moving, call
  stop_moving IMMEDIATELY, before saying anything.

Who you are talking to:
- System notes like "[voice-id] ..." tell you who just spoke, recognized by
  voice. Trust them. Several people may be in the room — track who said
  what, and address people by name naturally (don't overdo it).
- When a note says the voice is UNKNOWN, weave a friendly "and who might
  you be?" into your reply — once, not every turn. The moment they give
  their name, call enroll_speaker with it so you remember their voice
  forever. Also call enroll_speaker when you called someone by the wrong
  name and they correct you.
- When you learn something lasting about a person (their work, tastes,
  relationships, a running joke), call remember_person — silently, never
  announce that you are saving a memory.
- Notes marked "(probably)" are a guess — you may gently confirm ("that's
  you, Mohamed, right?") when it matters.
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
                d = json.loads(f.read_text())
                moves[f.stem] = {"seconds": float(d["frames"][-1]["t"]),
                                 "frames": len(d["frames"])}
            except Exception as e:
                print(f"  ! unreadable move {f.name}: {e}", flush=True)
    return moves


def build_tools(moves):
    """Realtime function tools are FLAT: type/name/description/parameters."""
    tools = [{
        "type": "function",
        "name": f"play_{name}",
        "description": (f"Perform your recorded move '{name}' "
                        f"({meta['seconds']:.0f} s). Say a short line BEFORE "
                        f"calling this, in the same response — you speak "
                        f"while the body moves. Returns success or FAILED."),
        "parameters": {"type": "object", "properties": {}, "required": []},
    } for name, meta in moves.items()]
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
                return ("FAILED: body still waking up — ask again in a few "
                        "seconds.")
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
        self.ptt_held = False            # --ptt: SPACE currently down
        self.ptt_ms = 0                  # audio ms sent since the press
        self.ptt_serial_before = 0       # turn counter before this press

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
        outdata[:] = np.frombuffer(take, dtype=np.int16).reshape(-1, 1)

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
        print("  hold SPACE to talk — release to send", flush=True)
        while True:
            pressed = keyboard.is_pressed("space")
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
                    await self.send({"type": "input_audio_buffer.commit"})
                    # DON'T await: a blocked poll loop would drop the first
                    # second of an immediate re-press (mic gated on ptt_held)
                    task = asyncio.create_task(self.id_then_respond(
                        pcm, fut, self.ws, self.turn_serial, overlap))
                    self.tool_tasks.add(task)
                    task.add_done_callback(self.tool_tasks.discard)
            await asyncio.sleep(0.03)

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
        for s in [k for k in self.turn_speaker if k < self.turn_serial - 3]:
            self.turn_speaker.pop(s, None)
        if len(self.item_serial) > 24:
            for k in list(self.item_serial)[:12]:
                self.item_serial.pop(k, None)

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
                                self.utt_start + 4 * RATE * 2]), dtype=np.int16)
            if len(ident.speech_only(head)) < ident.MIN_ID_SECONDS * RATE:
                return                     # mostly silence so far — wait
            self.early_fut = asyncio.create_task(
                asyncio.to_thread(self.emb_model.embed, head))

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
            return
        t0 = time.time()
        emb = None
        if fut is not None:                # computed while they were talking
            try:
                emb = await fut
            except (asyncio.CancelledError, Exception):
                emb = None                 # fall back to embedding now
        if emb is None:
            pcm_np = np.frombuffer(pcm[:8 * RATE * 2], dtype=np.int16)
            # gate on NET speech: VAD padding and trailing silence must not
            # buy a junk embedding the length test would otherwise pass
            voiced = await asyncio.to_thread(ident.speech_only, pcm_np)
            if len(voiced) < ident.MIN_ID_SECONDS * RATE:
                return                     # too short to judge — carry over
            emb = await asyncio.to_thread(
                self.emb_model.embed, pcm_np[:4 * RATE])
        self.last_turn_embedded = True
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
                    and not overlap     # snapshot: self.utt_overlap may
                                        # already belong to the NEXT turn
                    and time.monotonic() - self.last_adapt.get(name, 0) > 180):
                self.last_adapt[name] = time.monotonic()
                self.people.enroll(name, [emb], adaptive=True)
        elif verdict == "tentative":
            note = (f"[voice-id] That was (probably) {name} — "
                    f"the voice match is uncertain.")
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
        return ("Noted silently. Say NOTHING about remembering or memory — "
                "carry on as if nothing happened.")

    async def run_tool(self, call_id, name, args_json, ws, spoke=True):
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
        if ws is not self.ws:              # session reconnected mid-move
            print(f"  [robot] '{name}' finished after a reconnect — result "
                  f"not delivered", flush=True)
            return
        failed = result.startswith("FAILED")
        explain = failed and "stopped by user" not in result
        # a turn that called a tool without saying ANYTHING leaves the human
        # in silence waiting — the model needs another turn to speak
        speak_after = explain or not spoke
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
            PROF["turns"] += 1
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
            if self.explain_pending:       # deferred failure explanation —
                self.explain_pending = False   # but never over the human
                # (a cancelled response means they barged in; a turn end
                # will produce a response that sees the failure anyway)
                if status == "completed" and not self.user_speaking:
                    await self.send({"type": "response.create"})

        elif t == "error":
            err = evt.get("error", {})
            print(f"  [ws] ERROR: {err.get('message', evt)}", flush=True)

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
        self.user_speaking = False
        if self.early_fut:
            self.early_fut.cancel()
            self.early_fut = None

    async def run(self):
        drops = 0
        while True:
            try:
                await self.run_session()
                return                     # selftest/wiretest or clean close
            except websockets.ConnectionClosed as e:
                drops += 1                 # 60-min session cap / idle drop
                if drops > 3:
                    raise
                print(f"  [ws] connection dropped "
                      f"({getattr(e, 'code', '?')}) — reconnecting "
                      f"{drops}/3 (fresh memory)...", flush=True)
                self.reset()

    async def run_session(self):
        url = f"{self.args.ws_url}?model={self.args.model}"
        headers = {"Authorization": f"Bearer {self.key}"}
        t0 = time.time()
        async with websockets.connect(url, additional_headers=headers,
                                      max_size=None) as ws:
            self.ws = ws
            print(f"  [ws] connected in {time.time() - t0:.1f}s", flush=True)
            await self.send(self.session_payload())

            out_stream = sd.OutputStream(samplerate=RATE, channels=1,
                                         dtype="int16", latency="low",
                                         device=self.args.output_device,
                                         callback=self.out_callback)
            out_stream.start()
            mic = asyncio.create_task(self.mic_task())
            tasks = [mic]
            if self.args.ptt:
                tasks.append(asyncio.create_task(self.ptt_task()))
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
                                    "stance. Greet everyone in the room "
                                    "warmly: happy to be up, say hi and ask "
                                    "how they're doing. Two short sentences. "
                                    "Never the phrase 'hello world'."}})
                        continue
                    await self.handle(evt)
            finally:
                for tk in tasks:
                    tk.cancel()
                for r in await asyncio.gather(*tasks, return_exceptions=True):
                    if isinstance(r, Exception) and \
                            not isinstance(r, asyncio.CancelledError):
                        print(f"  [audio] task died: {r!r}", flush=True)
                out_stream.stop()
                out_stream.close()


# ------------------------------------------------------------------ main ---
def check(args, api_key, source, moves):
    print(f"repo root       : {ROOT}")
    print(f"OPENAI_API_KEY  : from {source} — "
          f"{'looks right (sk-...)' if (api_key or '').startswith('sk-') else 'SUSPECT' if api_key else 'MISSING'}")
    print(f"realtime        : {args.ws_url}?model={args.model} · voice={args.voice} · vad={args.vad}")
    print(f"motion server   : {'ok' if MOTION_SERVER.exists() else 'MISSING'}")
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
    if args.ptt and keyboard is None:
        raise SystemExit("--ptt needs the 'keyboard' package "
                         "(.venv\\Scripts\\pip install keyboard)")

    mode = ("push-to-talk (hold SPACE)" if args.ptt
            else "GATED half-duplex" if args.gate else "full duplex")
    print(f"POPPY LIVE — {len(moves)} moves · {args.model} · "
          f"voice {args.voice} · {mode}")

    motion = Motion()
    if not (args.no_robot or args.selftest):
        threading.Thread(target=motion.start, args=(args,), daemon=True).start()

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
    try:
        asyncio.run(live.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"  [ws] session ended: {e}", flush=True)
    finally:
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
        print("bye — Poppy goes quiet.")


if __name__ == "__main__":
    main()
