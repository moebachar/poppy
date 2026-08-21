#!/usr/bin/env python
"""Persistent motion server: awaken, hold the stance, replay moves on demand.

    python 10_motion_server.py --port /dev/ttyACM0        (on the Pi)
    python 10_motion_server.py --port COM7                (laptop-direct)

On start: stiffen where the robot is, travel slowly into the stand pose, hold
it. Then serve a line protocol on stdin/stdout (used by perception/voice_agent.py,
also usable by hand):

    play <name>   -> PLAY_START <name> ... PLAY_DONE <name> <secs>
                     or PLAY_FAIL <name> <reason>   (returns to stance after)
    look          -> head glances left/right (wake-up gesture), LOOK_DONE
    stop          -> aborts the current play immediately (out-of-band)
    hold          -> re-stiffen into the stance (after a release)
    release       -> go soft but keep serving
    record_start {"41":20,"42":0}
                  -> RECORD_START: body rigid, each listed motor loose at the
                     given stiffness pct (0 = free), taught by hand at 20 Hz
    record_stop <name> -> save moves/recorded/<name>.json (07's format),
                     re-stiffen, back to stance, RECORD_SAVED <name> <frames> <secs>
    record_abort  -> same restore path, nothing written -> RECORD_ABORTED
    status        -> STATUS holding=... maxtemp=...
    quit / EOF    -> BYE (always releases the motors)

Temp watchdog: any motor >= 52 C -> full release + TEMP_RELEASE (send 'hold'
to resume once cooled). The 12 V plug stays the physical e-stop.

--telemetry (for web/server.py) adds unsolicited lines, one JSON per line:
MOTORS (once after the scan), POS (10 Hz), HEALTH (every 2 s).
"""
import argparse
import json
import queue
import re
import signal
import sys
import threading
import time
from pathlib import Path

import pypot.dynamixel

from dxl_multiturn import SEAM_IDS, present_deg, goto_deg, freeze, rebase, is_multiturn

HERE = Path(__file__).parent
RECORDED = HERE / "moves" / "recorded"
POSES = HERE / "poses"
TEMP_HARD = 52          # release everything at this temperature
TEMP_RESUME = 45        # ...and re-hold automatically once back down here
HOLD_TORQUE = 60        # idle holding torque %% — full 100 only during moves
REC_HZ = 20.0           # frames stored per second (07_record_replay's format)
FOLLOW_HZ = 40.0        # goal-follows-hand rate: 2x REC_HZ halves the error
                        # the hand has to fight between ticks
EXPECTED_IDS = [33, 34, 35, 36, 37, 41, 42, 43, 44, 51, 52, 53, 54]  # 00_read_only's map

PRINT_LOCK = threading.Lock()   # one lock for stdout — lines never interleave
BUS_GATE = threading.Lock()     # held by play/record ticks; telemetry yields to it


def out(*words):
    with PRINT_LOCK:
        print(" ".join(str(w) for w in words), flush=True)


def unwrap(vals):
    """Make a recorded series continuous (undo +/-360 flickers at the seam)."""
    res = [vals[0]]
    for v in vals[1:]:
        d = v - res[-1]
        d -= 360.0 * round(d / 360.0)
        res.append(res[-1] + d)
    return res


class Body:
    def __init__(self, dxl, present):
        self.dxl = dxl
        self.present = present
        self.seam = [i for i in present if i in SEAM_IDS]
        self.others = [i for i in present if i not in SEAM_IDS]
        self.holding = False

    def positions(self, ids=None):
        """Read every present motor, or just `ids` (teach ticks read the few
        loose joints only — the whole body is read once per stored frame)."""
        want = self.present if ids is None else [i for i in ids if i in self.present]
        others = [i for i in want if i not in SEAM_IDS]
        pos = dict(zip(others, self.dxl.get_present_position(others))) if others else {}
        for i in want:
            if i in SEAM_IDS:
                pos[i] = present_deg(self.dxl, i)
        return pos

    def set_goal(self, i, v):
        if i in SEAM_IDS:
            goto_deg(self.dxl, i, v)
        else:
            self.dxl.set_goal_position({i: v})

    def stiffen(self):
        """Freeze at the current position, full strength, slow speed."""
        cur = self.positions()
        for i in self.present:
            self.dxl.set_moving_speed({i: 20})
            self.dxl.set_torque_limit({i: 100})
            if i in SEAM_IDS:
                freeze(self.dxl, i)
            else:
                self.dxl.set_goal_position({i: cur[i]})
                self.dxl.enable_torque((i,))
        time.sleep(0.3)
        self.holding = True
        return cur

    def travel_begin(self, target, max_travel, speed=20):
        """Command a slow guarded travel; return its estimated duration (s)."""
        cur = self.positions()
        target = {i: v for i, v in target.items() if i in self.present}
        for i in self.seam:
            if i in target:
                target[i] = rebase(target[i], cur[i])
        worst = max(abs(target[i] - cur[i]) for i in target)
        if worst > max_travel:
            raise RuntimeError(f"target {worst:.0f} deg away (> {max_travel:.0f})")
        for i in target:
            self.dxl.set_moving_speed({i: speed})
            self.set_goal(i, target[i])
        return worst / speed + 0.3

    def travel(self, target, max_travel, speed=20):
        time.sleep(self.travel_begin(target, max_travel, speed))

    def set_torque(self, pct):
        for i in self.present:
            self.dxl.set_torque_limit({i: pct})

    def release(self):
        self.dxl.disable_torque(self.present)
        self.holding = False

    def max_temp(self):
        return max(self.dxl.get_present_temperature(self.present))


def load_pose(name):
    return {int(k): v for k, v in
            json.loads((POSES / f"{name}.json").read_text())["positions"].items()}


def head_look(body, stance):
    """Glance left, then right, then back to center — a wake-up gesture."""
    pan = 36
    if pan not in body.present:
        raise RuntimeError("head pan motor 36 not on the bus")
    center = stance.get(pan, body.positions()[pan])
    body.dxl.set_moving_speed({pan: 45})   # unhurried, like waking up
    for tgt, pause in ((center + 25, 1.5), (center - 25, 2.0),
                       (center + 12, 1.3), (center, 1.0)):
        body.dxl.set_goal_position({pan: tgt})
        time.sleep(pause)
    body.dxl.set_moving_speed({pan: 20})


def telemetry(body):
    """POS at 10 Hz + HEALTH every 2 s; all reads on this daemon thread.

    BUS_GATE keeps the reads out of the 0.08s-critical play/record ticks:
    if a tick owns the bus right now, drop the beat instead of queueing.
    """
    n = 0
    while True:
        time.sleep(0.1)
        n += 1
        health = n % 20 == 0
        if not BUS_GATE.acquire(blocking=False):
            continue                       # bus busy: drop the beat
        try:
            pos = body.positions()
            if health:
                temps = body.dxl.get_present_temperature(body.present)
                volts = body.dxl.get_present_voltage(body.present)
        except Exception:
            continue                       # bus hiccup: drop the beat
        finally:
            BUS_GATE.release()
        out("POS " + json.dumps({str(i): round(p, 1) for i, p in pos.items()},
                                separators=(",", ":")))
        if health:
            out("HEALTH " + json.dumps(
                {"maxtemp": int(round(max(temps))), "holding": body.holding,
                 "motors": {str(i): {"t": int(round(t)), "v": round(v, 1)}
                            for i, t, v in zip(body.present, temps, volts)}},
                separators=(",", ":")))


TEACH_TORQUE_MAX = 20   # feel 100 % — the old scale's 20, "holds its weight"
TEACH_P_MAX = 12        # ...still far below the factory P of 32


def feel_to_hw(pct, model):
    """Operator 'feel' % -> (torque limit %, MX P gain, AX compliance slope).

    The whole scale lives in the SOFT band on purpose: a picked motor is one
    the hand is about to move, so it must never be rigid — a joint you want
    rigid you simply don't pick. feel 100 lands at what the raw register
    scale called 20 % (just enough to carry the limb's own weight); feel 5 is
    all but free. What the hand fights is mostly the position loop (P gain x
    the error since the last tick), so the gain softens along the same curve.
    """
    f = max(0.0, min(100.0, float(pct))) / 100.0
    torque = max(1, int(round(TEACH_TORQUE_MAX * f ** 1.5)))
    if str(model).startswith("AX"):            # AX-12: compliance slope, 128 = softest
        return torque, None, (128 if f <= 0.6 else 64)
    return torque, max(2, int(round(2 + (TEACH_P_MAX - 2) * f ** 1.2))), None


def restance(body, stance, max_settle):
    """Recording over: torque ceilings back to 100, stiff, slow travel home."""
    body.stiffen()
    try:
        body.travel(stance, max_settle)
    except Exception as e:
        out(f"# return-to-stance skipped: {e}")
    body.set_torque(HOLD_TORQUE)


def soften(dxl, loose, present):
    """Put the picked motors into teach feel; return what to restore after."""
    ids = [i for i, pct in loose.items() if pct > 0 and i in present]
    models = dict(zip(ids, dxl.get_model(ids))) if ids else {}
    saved = {}
    for i, pct in loose.items():
        if pct <= 0:
            dxl.disable_torque((i,))       # 0 = truly free (coast, no drag)
            continue
        torque, p_gain, slope = feel_to_hw(pct, models.get(i, "MX-28"))
        dxl.set_moving_speed({i: 150})
        dxl.set_torque_limit({i: torque})
        try:                               # soften the position loop itself
            if p_gain is not None:
                p, ig, d = dxl.get_pid_gain((i,))[0]
                saved[i] = ("pid", (p, ig, d))
                dxl.set_pid_gain({i: (p_gain, ig, d)})
            else:
                saved[i] = ("slope", dxl.get_compliance_slope((i,))[0])
                dxl.set_compliance_slope({i: (slope, slope)})
        except Exception as e:
            out(f"# motor {i}: gain softening skipped ({e})")
        out(f"# motor {i}: feel {pct:.0f}% -> torque {torque}%"
            + (f", P {p_gain}" if p_gain is not None else f", slope {slope}"))
    return saved


def unsoften(dxl, saved):
    """Put the position-loop gains back the way we found them."""
    for i, (kind, val) in saved.items():
        try:
            if kind == "pid":
                dxl.set_pid_gain({i: val})
            else:
                dxl.set_compliance_slope({i: val})
        except Exception as e:
            out(f"# motor {i}: gain restore failed ({e})")


def record(body, loose, cmds, stance, max_settle):
    """Teach mode (07's do_record, serverized): body rigid at 100% with fixed
    goals; each loose motor follows the hand (goal := present every tick).
    Runs until record_stop/record_abort/release/quit or the temp watchdog."""
    dxl = body.dxl
    absent = [i for i in loose if i not in body.present]
    loose = {i: pct for i, pct in loose.items() if i in body.present}
    if absent:
        out(f"# loose motors not on the bus, ignored: {absent}")
    if not loose:
        out("# WARNING: empty loose map — nothing will be movable by hand")
    body.stiffen()                         # rigid at 100%, fixed goals
    saved = soften(dxl, loose, body.present)
    try:
        return record_loop(body, loose, cmds, stance, max_settle)
    finally:
        unsoften(dxl, saved)


def record_loop(body, loose, cmds, stance, max_settle):
    """The teach tick: follow the hand at FOLLOW_HZ, store frames at REC_HZ."""
    out("RECORD_START")
    frames, t0 = [], time.time()
    period, last_temp = 1.0 / FOLLOW_HZ, t0
    frame_period = 1.0 / REC_HZ
    followed = [i for i, pct in loose.items() if pct > 0]
    next_frame = t0
    while True:
        tick = time.time()
        # a stored frame needs the whole body; the follow ticks in between
        # only need the joints the hand is holding (keeps the bus quiet)
        store = tick >= next_frame
        with BUS_GATE:
            pos = body.positions(None if store else followed)
            for i in followed:             # goal follows the hand: what you
                body.set_goal(i, pos[i])   # move, stays
        if store:
            next_frame = max(tick, next_frame + frame_period)
            frames.append({"t": round(tick - t0, 3),
                           "pos": {str(i): round(p, 2) for i, p in pos.items()}})
        if tick - last_temp > 2:
            last_temp = tick
            t_now = body.max_temp()
            if t_now >= TEMP_HARD:
                body.set_torque(100)
                body.release()
                out("RECORD_ABORTED")
                out(f"TEMP_RELEASE {t_now} C — body released to cool, "
                    f"auto-resumes at {TEMP_RESUME} C")
                return "hot"
        while True:                        # non-blocking poll each tick, so
            try:                           # record_stop is seen
                cmd = cmds.get_nowait()
            except queue.Empty:
                break
            parts = cmd.split(None, 1)
            if cmd in ("quit", "exit"):
                body.set_torque(100)
                out("RECORD_ABORTED")
                return "quit"
            elif cmd == "status":
                out(f"STATUS holding={body.holding} maxtemp={body.max_temp()}")
            elif cmd == "release":
                body.set_torque(100)
                body.release()
                out("RECORD_ABORTED")
                out("RELEASED")
                return "release"
            elif cmd == "record_abort":
                restance(body, stance, max_settle)
                out("RECORD_ABORTED")
                return None
            elif parts[0] == "record_stop":
                name = parts[1].strip() if len(parts) > 1 else ""
                if not re.fullmatch(r"[a-z0-9_-]{1,32}", name):
                    out(f"RECORD_FAIL bad name '{name}' — want [a-z0-9_-]{{1,32}}")
                elif len(frames) < 5:
                    restance(body, stance, max_settle)
                    out(f"RECORD_FAIL too short ({len(frames)} frames, need 5)")
                    out("RECORD_ABORTED")
                    return None
                else:
                    RECORDED.mkdir(parents=True, exist_ok=True)
                    (RECORDED / f"{name}.json").write_text(json.dumps(
                        {"name": name, "space": "raw", "hz": REC_HZ,
                         "ids": list(body.present), "frames": frames}, indent=1))
                    restance(body, stance, max_settle)
                    out(f"RECORD_SAVED {name} {len(frames)} {frames[-1]['t']:.1f}")
                    return None
            elif parts[0] == "record_start":
                out("RECORD_FAIL already recording")
            elif parts[0] == "play":
                out(f"PLAY_FAIL {parts[1] if len(parts) > 1 else '?'} recording")
            elif cmd == "look":
                out("LOOK_FAIL recording")
            elif cmd == "hold":
                out("HOLD_FAIL recording")
            else:
                out(f"# unknown command: {cmd}")
        time.sleep(max(0, period - (time.time() - tick)))


def play(body, name, stance, stop_event, max_travel, max_settle):
    path = RECORDED / f"{name}.json"
    if not path.exists():
        return f"no such recording '{name}'"
    frames = json.loads(path.read_text())["frames"]
    ids = [i for i in body.present if str(i) in frames[0]["pos"]]
    seam = [i for i in ids if i in SEAM_IDS]
    others = [i for i in ids if i not in SEAM_IDS]

    cur = body.positions()
    seam_traj = {}
    for i in seam:
        series = unwrap([f["pos"][str(i)] for f in frames])
        shift = rebase(series[0], cur[i]) - series[0]
        seam_traj[i] = [v + shift for v in series]

    first = {i: frames[0]["pos"][str(i)] for i in others}
    first.update({i: seam_traj[i][0] for i in seam})
    body.travel(first, max_travel, speed=40)   # short hop from the stance

    for i in ids:
        body.dxl.set_moving_speed({i: 150})
    t0, tref = time.time(), frames[0]["t"]
    last_temp = t0
    aborted = None
    for n, fr in enumerate(frames[1:], start=1):
        if stop_event.is_set():
            aborted = "stopped by user"
            break
        target = t0 + (fr["t"] - tref)
        now = time.time()
        if now > target + 0.08:
            continue                       # running late: drop the frame
        if target > now:
            time.sleep(target - now)
        with BUS_GATE:
            for i in others:
                v = fr["pos"].get(str(i))
                if v is not None:
                    body.dxl.set_goal_position({i: v})
            for i in seam:
                goto_deg(body.dxl, i, seam_traj[i][n])
        if time.time() - last_temp > 2:
            last_temp = time.time()
            if body.max_temp() >= TEMP_HARD:
                body.release()
                return "hot"
    try:
        body.travel(stance, max_settle, speed=40)  # back to the resting stance
    except Exception as e:
        out(f"# return-to-stance skipped: {e}")
    return aborted


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--pose", default="stand")
    ap.add_argument("--max-travel", type=float, default=100.0)
    ap.add_argument("--max-settle", type=float, default=150.0,
                    help="travel allowance for settling into the stance "
                         "(slow + supervised, so wider than move travel)")
    ap.add_argument("--telemetry", action="store_true",
                    help="emit MOTORS/POS/HEALTH lines for web/server.py")
    args = ap.parse_args()

    for signame in ("SIGHUP", "SIGTERM", "SIGINT"):
        if hasattr(signal, signame):
            try:
                signal.signal(getattr(signal, signame),
                              lambda *_: (_ for _ in ()).throw(SystemExit(1)))
            except (ValueError, OSError):
                pass

    stance = load_pose(args.pose)
    cmds, stop_event = queue.Queue(), threading.Event()

    def reader():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if line == "stop":             # out-of-band: aborts a running play
                stop_event.set()
            else:
                cmds.put(line)
        stop_event.set()                   # EOF: abort anything running...
        cmds.put("quit")                   # ...then shut down (releases)

    threading.Thread(target=reader, daemon=True).start()

    with pypot.dynamixel.DxlIO(args.port, baudrate=args.baud) as dxl:
        present = [i for i in dxl.scan(list(range(60))) if i < 250]
        if not present:
            out("FATAL no motors answered — is the 12 V bus powered?")
            return 1
        bad = [i for i in present if i in SEAM_IDS and not is_multiturn(dxl, i)]
        if bad:
            out(f"FATAL seam motors {bad} not in multi-turn mode "
                f"(dxl_multiturn.py enable)")
            return 1
        body = Body(dxl, present)
        if args.telemetry:
            out("MOTORS " + json.dumps({"present": present,
                                        "expected": EXPECTED_IDS},
                                       separators=(",", ":")))
            threading.Thread(target=telemetry, args=(body,), daemon=True).start()
        try:
            out(f"# {len(present)} motors up, stiffening...")
            body.stiffen()
            out(f"SETTLING into '{args.pose}'")
            try:
                est = body.travel_begin(stance, args.max_settle)
            except Exception as e:
                out(f"# settle skipped: {e}")   # hold where we froze — safe
            else:
                time.sleep(est * 0.35)     # the glance starts mid-settle,
                out("LOOKING")             # like a person waking up
                try:
                    head_look(body, stance)
                except Exception as e:
                    out(f"# look skipped: {e}")
                time.sleep(max(0.0, est * 0.65 - 6.0))
            body.set_torque(HOLD_TORQUE)   # cool idle hold; 100% only in moves
            out(f"READY {len(present)} motors, holding '{args.pose}'")
            last_temp = time.time()
            released_hot = False
            while True:
                try:
                    cmd = cmds.get(timeout=2)
                except queue.Empty:
                    cmd = None
                if time.time() - last_temp > 3:
                    last_temp = time.time()
                    t_now = body.max_temp()
                    if body.holding and t_now >= TEMP_HARD:
                        body.release()
                        released_hot = True
                        out(f"TEMP_RELEASE {t_now} C — body released to cool, "
                            f"auto-resumes at {TEMP_RESUME} C")
                    elif released_hot and not body.holding and t_now <= TEMP_RESUME:
                        restance(body, stance, args.max_settle)
                        released_hot = False
                        out(f"HOLDING (cooled to {t_now} C, back at stance)")
                if cmd is None:
                    continue
                if cmd in ("quit", "exit"):
                    break
                if cmd == "status":
                    out(f"STATUS holding={body.holding} maxtemp={body.max_temp()}")
                elif cmd == "release":
                    body.release()
                    released_hot = False
                    out("RELEASED")
                elif cmd == "hold":
                    restance(body, stance, args.max_settle)
                    released_hot = False
                    out(f"HOLDING '{args.pose}'")
                elif cmd == "look":
                    if not body.holding:
                        out("LOOK_FAIL body is released")
                        continue
                    try:
                        head_look(body, stance)
                        out("LOOK_DONE")
                    except Exception as e:
                        out(f"LOOK_FAIL {e}")
                elif cmd.startswith("play "):
                    name = cmd.split(None, 1)[1]
                    if not body.holding:
                        out(f"PLAY_FAIL {name} body is released (overheat or "
                            f"'release') — needs 'hold' first")
                        continue
                    out(f"PLAY_START {name}")
                    stop_event.clear()
                    body.set_torque(100)   # full strength for the move
                    t0 = time.time()
                    try:
                        err = play(body, name, stance, stop_event,
                                   args.max_travel, args.max_settle)
                    except Exception as e:
                        err = str(e)
                        if body.holding:
                            try:
                                restance(body, stance, args.max_settle)
                            except Exception:
                                pass
                    if body.holding:
                        body.set_torque(HOLD_TORQUE)
                    if err == "hot":
                        out(f"PLAY_FAIL {name} overheat during the move — "
                            f"body released to cool")
                        out(f"TEMP_RELEASE {body.max_temp()} C — body released "
                            f"to cool, auto-resumes at {TEMP_RESUME} C")
                        released_hot = True
                    elif err:
                        out(f"PLAY_FAIL {name} {err}")
                    else:
                        out(f"PLAY_DONE {name} {time.time() - t0:.1f}s")
                elif cmd.split(None, 1)[0] == "record_start":
                    if not body.holding:
                        out("RECORD_FAIL body is released — needs 'hold' first")
                        continue
                    try:
                        raw = json.loads(cmd[12:].strip() or "{}")
                        loose = {int(k): float(v) for k, v in raw.items()}
                    except (ValueError, TypeError, AttributeError) as e:
                        out(f"RECORD_FAIL bad loose map: {e}")
                        continue
                    try:
                        res = record(body, loose, cmds, stance, args.max_settle)
                    except Exception as e:
                        out(f"# record crashed: {e}")
                        try:
                            restance(body, stance, args.max_settle)
                            out("RECORD_ABORTED")
                        except Exception:
                            try:               # can't restance: go limp, say so
                                body.release()
                            except Exception:
                                pass
                            out("RECORD_ABORTED")
                            out("RELEASED")
                        res = None
                    if res == "hot":
                        released_hot = True
                    elif res == "release":
                        released_hot = False
                    elif res == "quit":
                        break
                elif cmd.split(None, 1)[0] in ("record_stop", "record_abort"):
                    out("RECORD_FAIL not recording")
                else:
                    out(f"# unknown command: {cmd}")
        finally:
            try:
                body.release()
            except Exception:
                pass
            out("BYE (released, compliant)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
