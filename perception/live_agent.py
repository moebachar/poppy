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
(With laptop mic + speakers he may hear himself — use --gate to mute the mic
during playback if that gets chaotic.)

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
from pathlib import Path

import numpy as np
import sounddevice as sd
import websockets

ROOT = Path(__file__).resolve().parents[1]
MOVES_DIR = ROOT / "scripts" / "motion" / "moves" / "recorded"
MOTION_SERVER = ROOT / "scripts" / "motion" / "10_motion_server.py"

RATE = 24000                 # realtime API native PCM rate, both directions
IN_BLOCK = RATE // 20        # 50 ms mic blocks
WS_URL = "wss://api.openai.com/v1/realtime"

INSTRUCTIONS = """\
You are Poppy — a humanoid robot: a torso with two arms and a head, on a
suction-cup base on a desk. No legs, and proud of it. You were made by
Mohamed Bachar, a PhD student at the CESI LINEACT research lab. You are
deeply thankful to him for making you, and you can't wait to learn
everything about this world.

Personality: curious, warm, playful, slightly cheeky — a young robot
discovering the world. Voice: an enthusiastic teenage boy, lively pace.
Keep every reply SHORT — one to three spoken sentences. Always answer in
the language the human spoke (usually French or English).

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
PROF = {"response": [], "move": [], "turns": 0}


def prof_summary():
    if not PROF["turns"] and not PROF["response"]:
        return
    print(f"\n=== {PROF['turns']} responses "
          f"(response = your silence -> Poppy's first sound) ===")
    for op in ("response", "move"):
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
        self.tool_tasks = set()          # keep refs; surface exceptions
        self.explain_pending = False     # failure speech deferred to turn end
        self.last_audio_t = 0.0          # when the speaker last emitted sound

    # --- audio plumbing ---
    def out_callback(self, outdata, frames, t, status):
        need = frames * 2
        with self.out_lock:
            take = self.out_buf[:need]
            del self.out_buf[:need]
            self.speaking = len(self.out_buf) > 0
        if take:
            self.last_audio_t = time.monotonic()
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
        if self.args.vad == "semantic":
            vad = {"type": "semantic_vad", "eagerness": "medium",
                   "create_response": True, "interrupt_response": True}
        else:                              # noisy-room alternative
            vad = {"type": "server_vad", "threshold": 0.6,
                   "prefix_padding_ms": 300, "silence_duration_ms": 600,
                   "create_response": True, "interrupt_response": True}
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
                if self.args.gate and (self.speaking or
                        time.monotonic() - self.last_audio_t < 0.35):
                    continue               # half-duplex: drop mic while talking
                await self.send({"type": "input_audio_buffer.append",
                                 "audio": base64.b64encode(data).decode()})
        finally:
            stream.stop()
            stream.close()

    async def run_tool(self, call_id, name, ws):
        if name == "stop_moving":
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
        if failed:
            result += (" — your body did NOT complete the move. Tell the "
                       "human plainly and give the reason.")
        try:
            await self.send({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": call_id,
                "output": result}})
            if explain:                     # speak the failure; success = silent
                if self.active_response:
                    self.explain_pending = True   # wait out the current reply
                else:
                    await self.send({"type": "response.create"})
        except websockets.ConnectionClosed:
            print(f"  [robot] '{name}' result lost — connection dropped",
                  flush=True)

    async def handle(self, evt):
        t = evt.get("type", "")

        if t in ("response.output_audio.delta", "response.audio.delta"):
            item_id = evt.get("item_id")
            if item_id and item_id != self.cur_item:
                self.cur_item, self.cur_item_bytes = item_id, 0
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

        elif t == "conversation.item.input_audio_transcription.completed":
            text = (evt.get("transcript") or "").strip()
            if text:
                print(f"\nyou: {text}", flush=True)

        elif t == "conversation.item.input_audio_transcription.failed":
            err = (evt.get("error") or {}).get("message", "?")
            print(f"  [ws] (couldn't transcribe what you said: {err})",
                  flush=True)

        elif t == "input_audio_buffer.speech_started":
            if self.speaking or self.active_response:
                with self.out_lock:
                    unplayed = len(self.out_buf)
                self.flush_output()        # barge-in: shut up instantly;
                # the server cancels its own response (interrupt_response).
                # Truncate ONLY if something actually went unheard — else we
                # would delete a fully-played reply from his memory:
                if self.cur_item and unplayed > 0:
                    played_ms = max(0, (self.cur_item_bytes - unplayed) // 48)
                    await self.send({"type": "conversation.item.truncate",
                                     "item_id": self.cur_item,
                                     "content_index": 0,
                                     "audio_end_ms": int(played_ms)})
                    self.cur_item, self.cur_item_bytes = None, 0

        elif t == "input_audio_buffer.speech_stopped":
            self.t_speech_stopped = time.time()
            self.first_audio_seen = False

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
            self.pending_calls.setdefault(rid, []).append((call_id, name))

        elif t == "response.done":
            resp = evt.get("response", {})
            status = resp.get("status")
            self.active_response = None
            PROF["turns"] += 1
            calls = self.pending_calls.pop(resp.get("id"), [])
            if status == "completed":
                for call_id, name in calls:
                    task = asyncio.create_task(
                        self.run_tool(call_id, name, self.ws))
                    self.tool_tasks.add(task)
                    task.add_done_callback(self.tool_tasks.discard)
            elif calls:
                print(f"  [robot] move request dropped (response {status})",
                      flush=True)
            if status in ("failed", "incomplete"):
                det = json.dumps(resp.get("status_details") or {})[:200]
                print(f"  [ws] response {status}: {det}", flush=True)
            if self.explain_pending:       # deferred failure explanation
                self.explain_pending = False
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
        self.transcript = []
        self.t_speech_stopped = None
        self.first_audio_seen = False
        self.cur_item, self.cur_item_bytes = None, 0

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
                                async def _end():
                                    await asyncio.sleep(18)
                                    print("WIRETEST DONE — event types seen:",
                                          sorted(self.seen_types), flush=True)
                                    await ws.close()
                                asyncio.create_task(_end())
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
                mic.cancel()
                for r in await asyncio.gather(mic, return_exceptions=True):
                    if isinstance(r, Exception) and \
                            not isinstance(r, asyncio.CancelledError):
                        print(f"  [mic] task died: {r!r}", flush=True)
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

    print(f"POPPY LIVE — {len(moves)} moves · {args.model} · voice {args.voice}"
          + (" · GATED" if args.gate else " · full duplex"))

    motion = Motion()
    if not (args.no_robot or args.selftest):
        threading.Thread(target=motion.start, args=(args,), daemon=True).start()

    live = Live(args, api_key, moves, motion)
    try:
        asyncio.run(live.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"  [ws] session ended: {e}", flush=True)
    finally:
        prof_summary()
        if motion.p is not None:
            print("laying Poppy to rest (motors released)...", flush=True)
        motion.close()
        print("bye — Poppy goes quiet.")


if __name__ == "__main__":
    main()
