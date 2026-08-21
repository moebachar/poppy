#!/usr/bin/env python
"""Poppy voice agent — talk to Poppy; it answers out loud and can move its body.

    python perception\voice_agent.py                 # the voice loop
    python perception\voice_agent.py --check         # config diagnostic, no audio
    python perception\voice_agent.py --list-devices  # audio device indexes

Talk by HOLDING the space bar — your words are transcribed live while you
speak; releasing sends them to Poppy. T = type a message instead, Q = quit.
On launch Poppy wakes up: stands into his stance, glances around, and greets
you first.

Pipeline (all OpenAI, needs OPENAI_API_KEY in env or in a .env at repo root):
    mic -> Whisper STT -> chat model with one tool per recorded move -> TTS

Audio + AI always run on the laptop. On launch the agent starts the
persistent motion server (scripts/motion/10_motion_server.py) where the
USB2AX is (--exec auto: laptop COM port if present, else over SSH on the Pi):
the robot AWAKENS — stiffens, travels into the stand stance and holds it
while you talk. Each move is a single command on the open link (fast), Poppy
speaks WHILE the body moves, and the body returns to the stance afterwards.
Quitting releases the motors (soft). Robot unreachable -> voice-only chat.

Ctrl+C during a move stops it — the replay script always releases the motors.
"""
import argparse
import io
import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

try:
    import keyboard                    # hold-space push-to-talk
except Exception:
    keyboard = None
try:
    import msvcrt                      # console key handling (Windows)
except ImportError:
    msvcrt = None

ROOT = Path(__file__).resolve().parents[1]
MOVES_DIR = ROOT / "scripts" / "motion" / "moves" / "recorded"
MOTION_SERVER = ROOT / "scripts" / "motion" / "10_motion_server.py"

TTS_INSTRUCTIONS = ("You are Poppy, a young curious humanoid robot. Voice of "
                    "an enthusiastic teenage boy: bright, warm, clearly "
                    "articulated, with a hint of mechanical charm. Match the "
                    "language of the text. Speak at a lively pace — about 15% "
                    "faster than a normal narrator.")


def load_config():
    """API config. Values in .env at the repo root WIN over inherited env vars:
    this machine carries corporate Azure OpenAI variables (OPENAI_BASE_URL,
    OPENAI_API_KEY, ...) that would silently redirect the SDK to Azure. The
    inherited OPENAI_BASE_URL is always ignored — unless .env sets one, we go
    straight to api.openai.com."""
    cfg = {}
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip("'").strip('"')
    api_key = cfg.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = cfg.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    source = ".env" if "OPENAI_API_KEY" in cfg else ("machine env" if api_key else "MISSING")
    return api_key, base_url, source


def discover_moves():
    moves = {}
    if MOVES_DIR.exists():
        for f in sorted(MOVES_DIR.glob("*.json")):
            if f.stem.startswith("_"):
                continue          # unnamed take, still being christened
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                moves[f.stem] = {"seconds": float(d["frames"][-1]["t"]),
                                 "frames": len(d["frames"]),
                                 "description": d.get("description", ""),
                                 "when": d.get("when") or []}
            except Exception as e:
                print(f"  ! unreadable move {f.name}: {e}", flush=True)
    return moves


def build_tools(moves):
    return [{
        "type": "function",
        "function": {
            "name": f"play_{name}",
            "description": (f"Perform your recorded move '{name}' "
                            f"({meta['seconds']:.0f} s). Reports success or "
                            f"failure when the move ends."),
            "parameters": {
                "type": "object",
                "properties": {
                    "say": {
                        "type": "string",
                        "description": (
                            f"What you speak out loud WHILE the move plays, in "
                            f"the human's language. The move lasts "
                            f"{meta['seconds']:.0f} s — size your speech to "
                            f"fill it: about {max(8, int(meta['seconds'] * 3))} "
                            f"words (2-4 short sentences). Self-contained — it "
                            f"is your whole comment on the move."),
                    },
                },
                "required": ["say"],
            },
        },
    } for name, meta in moves.items()]


def robot_port_present(port):
    from serial.tools import list_ports
    return any(p.device.upper() == port.upper() for p in list_ports.comports())


def ssh_base(args):
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", args.pi]


def pi_adapter_present(args):
    try:
        r = subprocess.run(ssh_base(args) + [f"test -e {args.pi_port}"],
                           capture_output=True, text=True, timeout=12)
        return r.returncode == 0
    except Exception:
        return False


def resolve_target(args):
    """Where can the body be moved right now? -> ('local'|'ssh'|None, detail)."""
    if args.exec_mode in ("auto", "local") and robot_port_present(args.port):
        return "local", f"adapter on {args.port} (laptop-direct)"
    if args.exec_mode in ("auto", "ssh") and pi_adapter_present(args):
        return "ssh", f"on the Pi ({args.pi}, {args.pi_port})"
    if args.exec_mode == "local":
        return None, f"no adapter on {args.port}"
    if args.exec_mode == "ssh":
        return None, f"{args.pi} unreachable or {args.pi_port} absent"
    return None, (f"no adapter on {args.port}, and {args.pi} "
                  f"unreachable or {args.pi_port} absent")


class MotionLink:
    """Client of 10_motion_server.py over a pipe (local child or ssh)."""

    def __init__(self, cmd):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  bufsize=1, encoding="utf-8", errors="replace")
        self.q = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        try:
            for line in self.p.stdout:
                self.q.put(line.rstrip("\r\n"))
        finally:
            self.q.put(None)

    def alive(self):
        return self.p.poll() is None

    def send(self, cmd):
        self.p.stdin.write(cmd + "\n")
        self.p.stdin.flush()

    def drain(self):
        while True:
            try:
                line = self.q.get_nowait()
            except queue.Empty:
                return
            if line:
                print(f"  [robot] {line}", flush=True)

    def wait_ready(self, timeout=90, on_line=None):
        t_end = time.time() + timeout
        while time.time() < t_end:
            try:
                line = self.q.get(timeout=1)
            except queue.Empty:
                continue
            if line is None:
                return False, "motion server exited (see [robot] lines above)"
            print(f"  [robot] {line}", flush=True)
            if on_line:
                try:
                    on_line(line)
                except Exception:
                    pass
            if line.startswith("READY"):
                return True, line
            if line.startswith("FATAL"):
                return False, line
        return False, f"no READY after {timeout:.0f} s"

    def wait_play(self, name, timeout=180):
        t_end = time.time() + timeout
        while time.time() < t_end:
            try:
                line = self.q.get(timeout=1)
            except queue.Empty:
                continue
            if line is None:
                return "FAILED: the motion link died mid-move."
            if not line:
                continue
            print(f"  [robot] {line}", flush=True)
            parts = line.split(None, 2)
            if parts[0] == "PLAY_DONE" and parts[1] == name:
                return f"Move '{name}' performed; body is back at the stance."
            if parts[0] == "PLAY_FAIL" and parts[1] == name:
                return "FAILED: " + (parts[2] if len(parts) > 2 else "unknown reason")
            if parts[0] == "TEMP_RELEASE":
                return "FAILED: overheated — body released to cool down."
        return f"FAILED: no completion report after {timeout:.0f} s."

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
            self.p.stdin.close()   # avoid "Exception ignored" noise at exit
        except Exception:
            pass


MOTION = {"link": None}

# --- lightweight profiling: per-turn op timings, summary at exit ------------
PROF_TURNS = []
CURRENT_PROF = {}
PROF_ORDER = ("rec", "stt_live", "stt", "brain", "tts", "speak", "move", "turn")


def prof_add(op, dt):
    CURRENT_PROF[op] = CURRENT_PROF.get(op, 0.0) + dt
    CURRENT_PROF["#" + op] = CURRENT_PROF.get("#" + op, 0) + 1


def prof_line():
    parts = []
    for op in PROF_ORDER:
        if op in CURRENT_PROF:
            n = CURRENT_PROF.get("#" + op, 1)
            parts.append(f"{op} {CURRENT_PROF[op]:.1f}s"
                         + (f"(x{n})" if n > 1 else ""))
    return " · ".join(parts)


def prof_close_turn():
    if any(op in CURRENT_PROF for op in PROF_ORDER):
        print(f"  [prof] {prof_line()}", flush=True)
        PROF_TURNS.append({k: v for k, v in CURRENT_PROF.items()
                           if not k.startswith("#")})
    CURRENT_PROF.clear()


def prof_summary():
    if not PROF_TURNS:
        return
    print(f"\n=== timings over {len(PROF_TURNS)} turns "
          f"(tts = time to first sound; speak overlaps move by design; "
          f"stt_live runs while you hold space; turn = everything after "
          f"transcription) ===")
    for op in PROF_ORDER:
        vals = [t[op] for t in PROF_TURNS if op in t]
        if vals:
            print(f"  {op:9s} n={len(vals):3d}  avg {sum(vals)/len(vals):5.2f}s"
                  f"  min {min(vals):5.2f}s  max {max(vals):5.2f}s")
# ---------------------------------------------------------------------------


def motion_command(args):
    if args.exec_mode in ("auto", "local") and robot_port_present(args.port):
        return ([sys.executable, "-u", str(MOTION_SERVER), "--port", args.port],
                f"local, adapter on {args.port}")
    if args.exec_mode in ("auto", "ssh"):
        remote = (f"cd {shlex.quote(args.pi_dir)}/scripts/motion && "
                  f"{shlex.quote(args.pi_python)} -u 10_motion_server.py "
                  f"--port {shlex.quote(args.pi_port)}")
        return ssh_base(args) + [remote], f"on the Pi ({args.pi}, {args.pi_port})"
    return None, f"no adapter on {args.port} (exec={args.exec_mode})"


def ensure_motion(args, on_line=None):
    """Return (link, None) with the robot awake and holding, or (None, why)."""
    link = MOTION["link"]
    if link and link.alive():
        return link, None
    MOTION["link"] = None
    cmd, desc = motion_command(args)
    if cmd is None:
        return None, desc
    print(f"  [robot] awakening ({desc})...", flush=True)
    link = MotionLink(cmd)
    ok, info = link.wait_ready(on_line=on_line)
    if not ok:
        link.close()
        return None, info
    MOTION["link"] = link
    return link, None


def begin_move(name, moves, args):
    """Start a move without waiting. Returns a handle for end_move()."""
    if name not in moves:
        print(f"  [robot] no such move '{name}'", flush=True)
        return ("fail", f"FAILED: '{name}' is not in the move library.")
    link, err = ensure_motion(args)
    if link is None:
        print(f"  [robot] offline: {err}", flush=True)
        return ("fail", f"FAILED: robot offline — {err}.")
    link.drain()
    link.send(f"play {name}")
    print(f"  [robot] playing '{name}'...", flush=True)
    return ("wait", link, name)


def end_move(handle):
    if handle[0] == "fail":
        return handle[1]
    _, link, name = handle
    try:
        return link.wait_play(name)
    except KeyboardInterrupt:
        try:
            link.send("stop")           # aborts mid-move, body eases to stance
        except Exception:
            pass
        raise


def system_prompt(moves):
    lst = "\n".join(f"- {n} ({m['seconds']:.0f} s)" for n, m in moves.items())
    return f"""You are Poppy — a humanoid robot: a torso with two arms and a head, on a \
suction-cup base on the desk. No legs, and proud of it. You were made by Mohamed \
Bachar, a PhD student at the CESI LINEACT research lab in France. You are deeply thankful to \
him for making you, and you can't wait to learn everything about this world.

Personality: curious, warm, playful, slightly cheeky — a young robot discovering \
the world. Replies are SPOKEN aloud: keep them to 1-3 short sentences, no emojis, \
no lists, no stage directions. Always answer in the language the human spoke \
(usually French or English).

Your body, honestly: 13 servo motors. Your right elbow motor is dead and awaiting \
its replacement, so the right arm is limited. Your left arm has a mechanical quirk \
fixed in software — you may joke your left arm is "special". Your head camera and \
speakers are being wired to your Raspberry Pi brain; today you hear and speak \
through the laptop beside you. While awake you hold your stand pose — that is your \
resting stance — and you return to it after every move.

Movement rules — IMPORTANT:
- You can ONLY move by calling the provided tools, one per move you have learned:
{lst if lst else '- (nothing recorded yet)'}
- Asked to move and a fitting move exists: call its tool and put your spoken words \
in its 'say' argument — they are said WHILE your body moves, like a human gesturing \
as they talk. Size them to last the whole move (each tool tells you its duration and \
word budget). Self-contained; after a successful move you add nothing more.
- Tool results are the ONLY truth about your body: "performed successfully" means it \
happened; "FAILED" means you did NOT move — say so plainly, give the reason, and \
never pretend otherwise.
- Asked for a movement you don't have: call NO tool. Say you haven't learned that one \
yet, and that they can teach it by hand — your body goes half-loose and they sculpt \
the move while you record it.
- Never invent moves, never promise motion later. What's not in the list doesn't exist.
- If asked what you can do, name your moves in plain words.

Messages wrapped in [SYSTEM EVENT ...] come from your own body and software, not \
from the human — react to them naturally in first person, never read them back \
literally."""


def transcribe(client, wav_buf, model, label="stt"):
    t0 = time.time()
    try:
        try:
            r = client.audio.transcriptions.create(model=model, file=wav_buf)
        except Exception as e:
            if model != "whisper-1":
                print(f"  ({model} failed: {e} — retrying with whisper-1)",
                      flush=True)
                wav_buf.seek(0)
                r = client.audio.transcriptions.create(model="whisper-1",
                                                       file=wav_buf)
            else:
                raise
    finally:
        prof_add(label, time.time() - t0)
    return (r.text or "").strip()


def robotize(pcm, rate, depth, offset=0):
    """Subtle ~30 Hz ring modulation — the classic robot-voice shimmer.
    Pure numpy: adds ~milliseconds. `offset` keeps the modulation phase
    continuous across streamed chunks."""
    if depth <= 0:
        return pcm
    x = pcm.astype(np.float32)
    t = (np.arange(x.shape[0], dtype=np.float32) + offset) / rate
    mod = (1.0 - depth) + depth * np.sin(2 * np.pi * 30.0 * t)
    x *= mod[:, None] if x.ndim == 2 else mod
    return np.clip(x, -32768, 32767).astype(np.int16)


def tts_synth(client, text, args):
    """Generate speech; returns (pcm, rate) ready to play."""
    t0 = time.time()
    base = dict(voice=args.voice, input=text, response_format="wav")
    first = dict(base, model=args.tts_model)
    if abs(args.tts_speed - 1.0) > 1e-3:
        first["speed"] = args.tts_speed
    if args.tts_model.startswith("gpt-"):
        first["instructions"] = TTS_INSTRUCTIONS
    attempts = [first]
    if "speed" in first:                   # some gpt-tts models reject 'speed';
        attempts.append({k: v for k, v in first.items() if k != "speed"})
    if args.tts_model != "tts-1":          # tts-1 honors 'speed' for sure
        attempts.append(dict(base, model="tts-1", speed=args.tts_speed))
    resp = err = None
    for kw in attempts:
        try:
            resp = client.audio.speech.create(**kw)
            break
        except Exception as e:
            err = e
    if resp is None:
        raise err
    with wave.open(io.BytesIO(resp.content), "rb") as w:
        rate, ch = w.getframerate(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if ch > 1:
        pcm = pcm.reshape(-1, ch)
    pcm = robotize(pcm, rate, args.robot_fx)
    prof_add("tts", time.time() - t0)
    return pcm, rate


def tts_play(client, text, args):
    pcm, rate = tts_synth(client, text, args)
    t0 = time.time()
    sd.play(pcm, rate, device=args.output_device)
    sd.wait()
    prof_add("speak", time.time() - t0)


def tts_stream_play(client, text, args):
    """Streaming TTS: playback starts on the first audio chunk, while the
    rest is still being generated. Falls back to tts_play on any trouble.
    Profiling: 'tts' = time to first sound, 'speak' = playback after that."""
    base = dict(voice=args.voice, input=text, response_format="pcm")
    first = dict(base, model=args.tts_model)
    if abs(args.tts_speed - 1.0) > 1e-3:
        first["speed"] = args.tts_speed
    if args.tts_model.startswith("gpt-"):
        first["instructions"] = TTS_INSTRUCTIONS
    attempts = [first]
    if "speed" in first:
        attempts.append({k: v for k, v in first.items() if k != "speed"})
    err = None
    for kw in attempts:
        t0 = time.time()
        try:
            with client.audio.speech.with_streaming_response.create(**kw) as resp:
                out = sd.OutputStream(samplerate=24000, channels=1,
                                      dtype="int16", device=args.output_device)
                out.start()
                leftover, offset, started = b"", 0, False
                try:
                    for chunk in resp.iter_bytes(chunk_size=4800):   # ~100 ms
                        if not started:
                            prof_add("tts", time.time() - t0)
                            t0 = time.time()
                            started = True
                        data = leftover + chunk
                        cut = len(data) // 2 * 2
                        leftover = data[cut:]
                        pcm = np.frombuffer(data[:cut], dtype=np.int16)
                        if len(pcm):
                            out.write(robotize(pcm, 24000, args.robot_fx, offset))
                            offset += len(pcm)
                finally:
                    out.stop()
                    out.close()
                if started:
                    prof_add("speak", time.time() - t0)
                    return
                raise RuntimeError("stream returned no audio")
        except Exception as e:
            err = e
    print(f"  (tts streaming failed: {err} — using non-streaming)", flush=True)
    tts_play(client, text, args)


def drain_console():
    if msvcrt:
        try:
            while msvcrt.kbhit():
                msvcrt.getwch()
        except Exception:
            pass


def wait_for_action():
    """Idle at the prompt: SPACE (hold) = talk, T = type, Q = quit."""
    while True:
        if keyboard.is_pressed("space"):
            return "space"
        if msvcrt and msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("q", "Q", "\x03"):
                return "quit"
            if ch in ("t", "T"):
                return "type"
        time.sleep(0.03)


def capture_space_stt(client, args):
    """Record while SPACE is held; transcribe live in ~1.6 s chunks; on
    release, transcribe the whole clip once more and return that text."""
    dev = sd.query_devices(args.input_device, "input")
    rate = int(dev["default_samplerate"])
    chunks, partial = [], {"busy": False}

    def cb(indata, frames, t, status):
        chunks.append(indata.copy())

    def partial_worker(snapshot):
        try:
            txt = transcribe(client, to_wav_buf(snapshot, rate),
                             args.stt_model, label="stt_live")
            print(f"\r  >> {txt[:100]:<100}", end="", flush=True)
        except Exception:
            pass
        finally:
            partial["busy"] = False

    print("  REC * speaking... (release SPACE to send)", flush=True)
    t_rec = time.time()
    last = time.time()
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                        device=args.input_device, callback=cb):
        while keyboard.is_pressed("space"):
            time.sleep(0.04)
            if time.time() - last > 1.6 and not partial["busy"] and chunks:
                snap = np.concatenate(chunks).ravel()
                if len(snap) > rate * 0.8:
                    partial["busy"] = True
                    last = time.time()
                    threading.Thread(target=partial_worker, args=(snap,),
                                     daemon=True).start()
    print("\r" + " " * 108 + "\r", end="", flush=True)
    prof_add("rec", time.time() - t_rec)
    if not chunks:
        return None
    audio = np.concatenate(chunks).ravel()
    if len(audio) < rate * 0.35:
        print("  too short, ignored.", flush=True)
        return None
    return transcribe(client, to_wav_buf(audio[-rate * 60:], rate),
                      args.stt_model).strip() or None


def record_push_to_talk(args):
    """Record from Enter to Enter — no silence detection to argue with."""
    dev = sd.query_devices(args.input_device, "input")
    rate = int(dev["default_samplerate"])
    chunks = []

    def cb(indata, frames, t, status):
        chunks.append(indata.copy())

    print("  REC * speak now — press Enter to stop", flush=True)
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                        device=args.input_device, callback=cb):
        input()
    if not chunks:
        return None, rate
    audio = np.concatenate(chunks).ravel()
    if len(audio) < rate * 0.35:
        print("  too short, ignored.", flush=True)
        return None, rate
    return audio[-rate * 60:], rate        # keep at most the last 60 s


def record_utterance(args):
    """--vad mode: record after Enter until ~silence-after seconds of quiet."""
    dev = sd.query_devices(args.input_device, "input")
    rate = int(dev["default_samplerate"])
    block = int(rate * 0.05)                       # 50 ms blocks
    chunks, started, quiet = [], None, 0.0
    print("  listening... speak now", flush=True)
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                        blocksize=block, device=args.input_device) as stream:
        ambient = np.mean([np.abs(stream.read(block)[0].astype(np.float32)).mean()
                           for _ in range(6)])
        threshold = args.vad_threshold or max(150.0, 4.0 * float(ambient))
        t0 = time.time()
        while True:
            data, _ = stream.read(block)
            level = np.abs(data.astype(np.float32)).mean()
            if started is None:
                if level > threshold:
                    started = time.time()
                    chunks.append(data.copy())
                    print("  recording... (stops on silence)", flush=True)
                elif time.time() - t0 > args.wait_speech:
                    print("  heard nothing.", flush=True)
                    return None, rate
            else:
                chunks.append(data.copy())
                quiet = quiet + 0.05 if level < threshold else 0.0
                if quiet >= args.silence_after or time.time() - started > args.max_seconds:
                    break
    audio = np.concatenate(chunks).ravel()
    if len(audio) < rate * 0.35:
        print("  too short, ignored.", flush=True)
        return None, rate
    return audio, rate


def to_wav_buf(audio, rate):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio.tobytes())
    buf.seek(0)
    buf.name = "speech.wav"
    return buf


def chat_turn(client, messages, tools, moves, args, say):
    """One user turn: run the model, speak content, execute tools, repeat."""
    for hop in range(4):
        kwargs = {"model": args.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            if hop == 3:                    # last hop: force a spoken wrap-up
                kwargs["tool_choice"] = "none"
        t0 = time.time()
        r = client.chat.completions.create(**kwargs)
        prof_add("brain", time.time() - t0)
        msg = r.choices[0].message
        entry = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            entry["tool_calls"] = [tc.model_dump() for tc in msg.tool_calls]
        messages.append(entry)
        if not msg.tool_calls:
            if msg.content:
                say(msg.content)
            return
        all_ok, spoke = True, False
        for tc in msg.tool_calls:
            name = tc.function.name.removeprefix("play_")
            try:
                say_text = json.loads(tc.function.arguments or "{}").get("say")
            except Exception:
                say_text = None
            t0 = time.time()
            handle = begin_move(name, moves, args)     # motion starts first...
            if not spoke and (say_text or msg.content):
                say(say_text or msg.content)           # ...speech rides on top
                spoke = True
            result = end_move(handle)
            prof_add("move", time.time() - t0)
            if result.startswith("FAILED"):
                all_ok = False
                result += (" — IMPORTANT: your body did NOT complete this "
                           "move. Tell the human plainly and give the reason. "
                           "Never claim or imply it happened.")
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": result})
        if all_ok and spoke:
            return          # the announcement WAS the comment — stay snappy


def check(moves, args, api_key, base_url, key_source):
    looks = "looks right (sk-...)" if (api_key or "").startswith("sk-") \
        else "does NOT look like an OpenAI key"
    print(f"repo root       : {ROOT}")
    print(f"python          : {sys.executable}")
    print(f"OPENAI_API_KEY  : from {key_source} — {looks if api_key else 'MISSING'}")
    print(f"endpoint        : {base_url}")
    print(f"models          : brain={args.model}  stt={args.stt_model}  tts={args.tts_model}  voice={args.voice}")
    print(f"motion server   : {'ok' if MOTION_SERVER.exists() else 'MISSING'} ({MOTION_SERVER})")
    target, detail = resolve_target(args)
    print(f"robot ({args.exec_mode:>5})   : {(target or 'OFFLINE') + ' — ' + detail}")
    print(f"moves ({len(moves)})       :")
    for n, m in moves.items():
        print(f"    {n:20s} {m['seconds']:5.1f} s  {m['frames']} frames")
    try:
        din = sd.query_devices(args.input_device, "input")
        dout = sd.query_devices(args.output_device, "output")
        print(f"mic             : {din['name']} @ {int(din['default_samplerate'])} Hz")
        print(f"speaker         : {dout['name']}")
    except Exception as e:
        print(f"audio           : PROBLEM — {e}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM7", help="robot serial port (laptop)")
    ap.add_argument("--exec", dest="exec_mode", choices=("auto", "local", "ssh"),
                    default="auto",
                    help="where moves run: local COM port, ssh to the Pi, or "
                         "auto (local if the adapter is here, else the Pi)")
    ap.add_argument("--pi", default="poppy@poppy.local")
    ap.add_argument("--pi-dir", default="/home/poppy/poppy")
    ap.add_argument("--pi-python", default="/home/poppy/env/bin/python")
    ap.add_argument("--pi-port", default="/dev/ttyACM0")
    ap.add_argument("--model", default="gpt-4.1-mini", help="chat model (the brain)")
    ap.add_argument("--stt-model", default="gpt-4o-mini-transcribe")
    ap.add_argument("--tts-model", default="gpt-4o-mini-tts")
    ap.add_argument("--voice", default="echo",
                    help="alloy/ash/ballad/coral/echo/fable/nova/onyx/sage/shimmer")
    ap.add_argument("--tts-speed", type=float, default=1.15)
    ap.add_argument("--robot-fx", type=float, default=0.25,
                    help="robot-voice ring-mod depth 0..1 (0 = off)")
    ap.add_argument("--input-device", type=int, default=None)
    ap.add_argument("--output-device", type=int, default=None)
    ap.add_argument("--vad-threshold", type=float, default=None,
                    help="fixed mic level threshold (default: auto from ambient)")
    ap.add_argument("--silence-after", type=float, default=1.2)
    ap.add_argument("--wait-speech", type=float, default=8.0)
    ap.add_argument("--max-seconds", type=float, default=20.0)
    ap.add_argument("--vad", action="store_true",
                    help="auto silence detection instead of push-to-talk")
    ap.add_argument("--mute", action="store_true", help="print only, no TTS")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    api_key, base_url, key_source = load_config()

    if args.list_devices:
        print(sd.query_devices())
        return

    moves = discover_moves()

    if args.check:
        check(moves, args, api_key, base_url, key_source)
        return

    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing — create a .env file at the "
                         "repo root containing:\n  OPENAI_API_KEY=sk-...")
    if key_source == "machine env" and not api_key.startswith("sk-"):
        print("WARNING: using the machine's inherited OPENAI_API_KEY, which does "
              "not look like a personal OpenAI key. If calls fail, put your real "
              "key in a .env file at the repo root.", flush=True)
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)

    tools = build_tools(moves)
    messages = [{"role": "system", "content": system_prompt(moves)}]

    def say(text):
        print(f"\nPOPPY: {text}", flush=True)
        if not args.mute:
            try:
                tts_stream_play(client, text, args)
            except Exception as e:
                print(f"  (tts failed: {e})", flush=True)

    print(f"POPPY VOICE AGENT — {len(moves)} moves loaded")

    # Wake-up scene: the greeting is generated in the background from the
    # first second and PLAYS THE MOMENT IT IS READY — while the body is still
    # settling and the head-glance (started mid-settle by the server) runs.
    messages.append({"role": "user", "content":
        "[SYSTEM EVENT: you are waking up — standing into your stance, head "
        "glancing slowly around the room. Greet everyone in the room out "
        "loud: happy to be up, what a good day, say hi to everyone and ask "
        "how they're doing. Two short sentences, no move tools, and never "
        "the phrase 'hello world'.]"})

    def _greet():
        try:
            t0 = time.time()
            r = client.chat.completions.create(model=args.model,
                                               messages=messages)
            prof_add("brain", time.time() - t0)
            text = (r.choices[0].message.content or "").strip()
            if text:
                messages.append({"role": "assistant", "content": text})
                print(f"\nPOPPY: {text}", flush=True)
                if not args.mute:
                    tts_stream_play(client, text, args)
        except Exception as e:
            print(f"  (wake-up greeting failed: {e})", flush=True)

    greet_thread = threading.Thread(target=_greet, daemon=True)
    greet_thread.start()

    link, err = ensure_motion(args)
    if link:
        print("  [robot] awake, holding the stance.")
    else:
        print(f"  [robot] OFFLINE — {err} — voice-only for now.")
    greet_thread.join(timeout=45)          # let the greeting finish playing
    if CURRENT_PROF:
        print(f"  [prof] wake-up: {prof_line()}", flush=True)
    CURRENT_PROF.clear()

    use_space = keyboard is not None and msvcrt is not None and not args.vad
    if use_space:
        print("Hold SPACE and talk — words appear live, release to send. "
              "T = type, Q = quit. Ctrl+C during a move stops it; quitting "
              "lays Poppy to rest (soft).")
    else:
        why = "--vad" if args.vad else "no 'keyboard' package"
        print(f"Enter-mode ({why}): Enter = record, then Enter/silence to "
              f"send; or type a message; 'q' to quit.")

    while True:
        try:
            text = None
            if use_space:
                print("\nyou > [hold SPACE to talk · T to type · Q to quit]",
                      flush=True)
                act = wait_for_action()
                if act == "quit":
                    break
                if act == "type":
                    drain_console()
                    text = input("type > ").strip()
                else:
                    text = capture_space_stt(client, args)
                    drain_console()
                if text:
                    print(f"  you: {text}", flush=True)
            else:
                typed = input("\nyou > ").strip()
                if typed.lower() in ("q", "quit", "exit"):
                    break
                if typed:
                    text = typed
                else:
                    audio, rate = (record_utterance(args) if args.vad
                                   else record_push_to_talk(args))
                    if audio is not None:
                        print("  transcribing...", flush=True)
                        text = transcribe(client, to_wav_buf(audio, rate),
                                          args.stt_model)
                        if text:
                            print(f"  you said: {text}", flush=True)
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            CURRENT_PROF.clear()
            continue
        t_proc = time.time()
        try:
            messages.append({"role": "user", "content": text})
            if len(messages) > 40:                     # keep system + recent turns
                del messages[1:len(messages) - 30]
                while len(messages) > 1 and messages[1]["role"] == "tool":
                    del messages[1]        # never start history on an orphan tool reply
            chat_turn(client, messages, tools, moves, args, say)
        except KeyboardInterrupt:
            print("\n  (interrupted)", flush=True)
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
        prof_add("turn", time.time() - t_proc)
        prof_close_turn()
    prof_summary()
    if MOTION["link"]:
        print("laying Poppy to rest (motors released)...", flush=True)
        MOTION["link"].close()
    print("bye — Poppy goes quiet.")


if __name__ == "__main__":
    main()
