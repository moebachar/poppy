#!/usr/bin/env python
r"""POPPY/DECK admin — the soft password gate and the agent-configuration API.

Serves web/VOICE.md 5.2 (the gate) and 5.3 (/api/admin/*). The password is a
salted SHA-256 in web/admin_auth.json; tokens live in memory only, so closing
the bridge signs everybody out.

web/server.py wires its routes into this module and asks gate() which paths
need a token; this module never imports server.py back. perception/agent_config
is imported ON DEMAND — it belongs to the agent, and a missing or broken copy
of it must answer one route with a sentence, not stop the bridge from starting.
"""
import copy
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path

import voicelink                 # params, the identity module, the fan-out

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AUTH_PATH = HERE / "admin_auth.json"
MOVES_DIR = ROOT / "scripts" / "motion" / "moves" / "recorded"

FIRST_PASSWORD = "1234"          # what the file is created with on first run
TOKEN_TTL = 8 * 3600             # VOICE.md 5.2
LOGIN_DELAY = 0.25               # fixed cost on a refusal: no timing oracle
PASS_MIN, PASS_MAX = 4, 64
# The 250 ms delay is a timing shield, NOT a rate limit: it is per request and
# the route runs on a thread pool 40 wide, so 40 refusals used to sleep side by
# side — ~160 guesses a second, the whole 4-digit space in a minute, and the
# shipped default 1234 inside the first one. So: a real counter, per client.
LOGIN_FREE = 5                   # honest fat-finger tries before the wait
LOGIN_LOCKS = (5, 30, 120, 600, 1800)     # seconds, escalating, then 30 min
LOGIN_FORGET = 3600              # a quiet hour clears a client's counter
LIMITS = {"instructions": 20000, "greeting": 2000, "nudge_prompt": 2000,
          "description": 1000}
PROMPT_KEYS = ("instructions", "greeting", "nudge_prompt")

# the realtime session literals live in perception/live_agent.py; only the
# tool list is shared code (agent_config.build_tools), so these four must
# follow live_agent.session_payload() if it ever changes
RATE = 24000
TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
TRANSCRIBE_LANGUAGE = "fr"           # mirrors live_agent.session_payload()

_LOCK = threading.Lock()         # guards _TOKENS, _FAILS and the auth file
_TOKENS = {}                     # token -> expiry (unix). In memory ONLY: a
                                 # token from a previous bridge run matches
                                 # nothing at all, which is the point.
_FAILS = {}                      # client host -> {n, until, at}: the counter
_AGENT_CFG = None                # perception/agent_config.py, on demand
# agent_config.save() is a read-modify-write of one file: two saves landing in
# different thread-pool threads a few ms apart merged over each other and the
# first edit vanished, while BOTH answers looked right because each re-read
# after the other's write. voicelink serialises its people writes for exactly
# this reason (_PEOPLE_LOCK); this is the same lock for the config file.
_CFG_LOCK = threading.RLock()    # RLock: config_set re-enters it via config_doc


class AdminError(Exception):
    """An error with an HTTP status; rendered as {"error": sentence}."""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def _sentence(e):
    """An exception as one clean line the deck can print."""
    return " ".join(f"{e}".split()) or type(e).__name__


def _agent_config():
    """perception/agent_config.py — the agent's own defaults and tool builder.

    The SAME module the session uses, so a preview cannot drift from what is
    actually sent (VOICE.md 5.1).
    """
    global _AGENT_CFG
    if _AGENT_CFG is None:
        path = str(ROOT / "perception")
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            import agent_config
        except Exception as e:
            raise AdminError(503, "the agent configuration module will not "
                                  f"load: {_sentence(e)}")
        _AGENT_CFG = agent_config
    return _AGENT_CFG


# -------------------------------------------------------------- the gate ----
def _stamp(when):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))


def _hash(password, salt):
    """Salted SHA-256, hex. The password itself never leaves this function."""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _new_auth(password):
    salt = secrets.token_hex(16)
    return {"salt": salt, "hash": _hash(password, salt),
            "changed": _stamp(time.time())}


def _write_auth(doc):
    """Publish atomically, through a name no other writer could be using.

    Same rule as perception/identity.py:_save — os.replace gives atomic
    publication, not mutual exclusion, so a fixed <name>.tmp would let two
    writers truncate each other's half-written file and publish the result.
    """
    tmp = AUTH_PATH.with_name(f"{AUTH_PATH.name}.{os.getpid()}-"
                              f"{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        json.loads(tmp.read_text(encoding="utf-8"))   # a short write (full
        for i in range(4):                            # disk) is not a password
            try:
                os.replace(tmp, AUTH_PATH)
                break
            except PermissionError:
                # Windows refuses to replace a file somebody merely has open
                if i == 3:
                    raise
                time.sleep(0.02 * (i + 1))
    except Exception:
        tmp.unlink(missing_ok=True)       # no stray temp file left behind
        raise


def _auth_doc():
    """The stored salt+hash, created with the default password on first use.

    Also the repair path: a file somebody emptied or hand-broke is rewritten
    with the default, because a dashboard nobody can sign into is worse than
    one whose password is back to what it shipped with.
    """
    try:
        doc = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        doc = None
    if isinstance(doc, dict) and isinstance(doc.get("salt"), str) \
            and isinstance(doc.get("hash"), str) and doc["salt"] and doc["hash"]:
        return doc
    doc = _new_auth(FIRST_PASSWORD)
    try:
        _write_auth(doc)
    except OSError as e:
        raise AdminError(500, f"could not write web/admin_auth.json: "
                              f"{_sentence(e)}")
    return doc


def _verify(password):
    """True when `password` matches the stored hash. Constant-time compare."""
    if not isinstance(password, str) or not password:
        return False
    doc = _auth_doc()
    # bytes, not str: compare_digest raises TypeError on a non-ASCII str, and
    # a hand-edited hash would then answer a login with a 500
    return hmac.compare_digest(_hash(password, doc["salt"]).encode("utf-8"),
                               str(doc["hash"]).encode("utf-8"))


def _prune(now):
    """Drop the expired tokens (lock held). Expiry is re-checked on use."""
    for tok in [t for t, exp in _TOKENS.items() if exp <= now]:
        _TOKENS.pop(tok, None)


def _how_long(seconds):
    """A wait in words — the operator has to know when to come back."""
    s = int(seconds) + 1                  # round up: "0 seconds" is a lie
    if s < 60:
        return f"{s} second" + ("" if s == 1 else "s")
    m = (s + 59) // 60
    return f"{m} minute" + ("" if m == 1 else "s")


def _forget_old(now):
    """Drop the counters of clients that have been quiet for an hour."""
    for host, rec in list(_FAILS.items()):
        if rec["until"] <= now and now - rec["at"] > LOGIN_FORGET:
            _FAILS.pop(host, None)


def _locked_for(host, now):
    """Seconds this client still has to wait, or 0.0 (lock held)."""
    rec = _FAILS.get(host)
    if rec is None:
        return 0.0
    return max(0.0, rec["until"] - now)


def _login_failed(host, now):
    """Count one wrong password and close the door a little further."""
    rec = _FAILS.get(host) or {"n": 0, "until": 0.0, "at": now}
    rec["n"] += 1
    rec["at"] = now
    over = rec["n"] - LOGIN_FREE
    if over > 0:
        rec["until"] = now + LOGIN_LOCKS[min(over, len(LOGIN_LOCKS)) - 1]
    _FAILS[host] = rec


def login(body, host=None):
    """POST /api/admin/login — the whole gate (VOICE.md 5.2)."""
    who = host if isinstance(host, str) and host else "?"
    password = body.get("password")
    token, expires, wait = None, 0.0, 0.0
    with _LOCK:
        now = time.time()
        _forget_old(now)
        wait = _locked_for(who, now)
        # the lock is checked BEFORE the compare, so a locked-out client learns
        # nothing from a correct guess either, and a wrong one during the lock
        # costs us no work at all
        if not wait:
            if _verify(password):
                _FAILS.pop(who, None)     # you are who you say: forget the
                _prune(now)               # near misses on the way in
                token = secrets.token_urlsafe(24)
                expires = now + TOKEN_TTL
                _TOKENS[token] = expires
            else:
                _login_failed(who, now)
    if wait:
        raise AdminError(429, "too many wrong passwords — this machine can try "
                              f"again in {_how_long(wait)}")
    if token is None:
        # one fixed cost whatever was wrong — a missing field, the wrong type,
        # a near-miss password — and one sentence that names none of them
        time.sleep(LOGIN_DELAY)
        raise AdminError(401, "that password is not right")
    return {"token": token, "expires": _stamp(expires)}


def token_error(token):
    """None when the token is good, else the sentence to answer 401 with.

    Every use re-checks the expiry: a token minted nine hours ago is as good
    as no token at all, whether or not anything pruned it in between.
    """
    if not isinstance(token, str) or not token:
        return "this needs the admin password"
    given = token.encode("utf-8")
    now = time.time()
    with _LOCK:
        _prune(now)
        # compare_digest against each live token: a dict lookup answers in a
        # time that depends on the guess
        for tok, exp in _TOKENS.items():
            if exp > now and hmac.compare_digest(tok.encode("utf-8"), given):
                return None
    return "that admin session is over — sign in again"


def gated(path):
    """True when this request path needs an X-Admin-Token header.

    One rule in one place, checked before routing: a route added later cannot
    forget the gate, and a path that reaches no route at all is refused just
    the same.

    /api/sessions is here for the same reason /api/people is: a past
    transcript is the raw material the personal facts were mined out of, and
    VOICE.md 5.4 puts SESSIONS on this page. /api/voice/chat is NOT gated —
    that is the deck's own live panel, which sits in front of the password,
    and same-origin policy already stops a web page reading it.
    """
    if path == "/api/admin/login":
        return False
    return (path == "/api/admin" or path.startswith("/api/admin/")
            or path == "/api/people" or path.startswith("/api/people/")
            or path == "/api/sessions" or path.startswith("/api/sessions/"))


def change_password(body, token):
    """POST /api/admin/password — re-hash under a fresh salt."""
    nxt = body.get("next")
    if not isinstance(nxt, str) or not PASS_MIN <= len(nxt) <= PASS_MAX:
        raise AdminError(400, f"the new password must be {PASS_MIN}-{PASS_MAX} "
                              f"characters")
    with _LOCK:
        if not _verify(body.get("current")):
            ok = False
        else:
            doc = _new_auth(nxt)
            try:
                _write_auth(doc)
            except OSError as e:
                raise AdminError(500, "could not write web/admin_auth.json: "
                                      f"{_sentence(e)}")
            # the password changed, so every OTHER browser holding a token is
            # signed out; the tab that made the change keeps the session it is
            # standing in, with the expiry it already had
            exp = _TOKENS.get(token) if isinstance(token, str) else None
            _TOKENS.clear()
            if exp is not None:
                _TOKENS[token] = exp
            ok = True
    if not ok:
        time.sleep(LOGIN_DELAY)           # same cost, same words, as login
        raise AdminError(401, "that password is not right")
    return {"ok": True, "changed": doc["changed"]}


# ---------------------------------------------------------- configuration ----
def _grouped(cfg):
    """agent_config's tree as {"prompt": …, "tools": …, "recognition": …}.

    Whether the three texts sit under 'prompt' or at the top level is
    agent_config's own choice, so read either shape — the admin page always
    shows them grouped, and a config written the other way must not read back
    empty.
    """
    if isinstance(cfg.get("prompt"), dict):
        prompt = dict(cfg["prompt"])
    else:
        prompt = {k: cfg[k] for k in PROMPT_KEYS if k in cfg}
    tools = cfg.get("tools")
    rec = cfg.get("recognition")
    return {"prompt": prompt,
            "tools": tools if isinstance(tools, dict) else {},
            "recognition": rec if isinstance(rec, dict) else {}}


def _flat_prompt(ac):
    """True when agent_config keeps the three texts at its top level."""
    defaults = getattr(ac, "DEFAULTS", None)
    return not (isinstance(defaults, dict)
                and isinstance(defaults.get("prompt"), dict))


def _load(ac):
    try:
        cfg = ac.load()
    except Exception as e:
        raise AdminError(500, "the agent configuration will not load: "
                              f"{_sentence(e)}")
    return cfg if isinstance(cfg, dict) else {}


def _diff(live, base, prefix, out):
    """Every leaf path where the live config differs from the default.

    Walks the UNION of the keys: an override on something the defaults do not
    mention (a move recorded last week, turned off for the model) is exactly
    the kind of change the UI offers a reset for.
    """
    keys = list(base) + [k for k in live if k not in base]
    for k in keys:
        a, b = live.get(k), base.get(k)
        path = prefix + str(k)
        if isinstance(a, dict) and isinstance(b, dict):
            _diff(a, b, path + ".", out)
        elif isinstance(a, dict) and b is None:
            _diff(a, {}, path + ".", out)
        elif isinstance(b, dict) and a is None:
            _diff({}, b, path + ".", out)
        elif a != b:
            out.append(path)


def config_doc():
    """GET /api/admin/config — the live tree, the defaults, and the diff."""
    with _CFG_LOCK:                       # not mid-save: the answer a save
        return _config_doc()              # returns must be what it wrote


def _config_doc():
    ac = _agent_config()
    cfg = _load(ac)
    live = _grouped(cfg)
    base = _grouped(copy.deepcopy(getattr(ac, "DEFAULTS", None) or {}))
    # agent_config's own answer when it has one: it knows that a move nobody
    # listed is simply ON, so "wave: enabled" is not a change from anything
    lister = getattr(ac, "changed", None)
    changed = None
    if callable(lister):
        try:
            changed = list(lister(cfg))
        except Exception:
            changed = None                # fall back to the plain tree diff
    if changed is None:
        changed = []
        _diff(live, base, "", changed)
    doc = dict(live)
    # the per-machine session parameters (web/voice_prefs.json) are the admin
    # page's SPEECH block; they have no override file, so nothing about them
    # is ever 'changed'
    doc["params"] = voicelink.prefs()
    base["params"] = copy.deepcopy(voicelink.DEFAULTS)
    doc["defaults"] = base
    doc["changed"] = changed
    # An unreadable override file is not fatal — agent_config falls back to the
    # defaults so a JSON typo never leaves Poppy mute. But then this page shows
    # a pristine tree with nothing 'changed', which reads as "no overrides"
    # rather than "your overrides are being ignored", and the next save writes
    # over them. Say so instead.
    reader = getattr(ac, "read_overrides", None)
    doc["error"] = None
    if callable(reader):
        try:
            doc["error"] = reader()[1]
        except Exception:
            doc["error"] = None
    return doc


def _checked_tool_row(name, row, desc_ok):
    if not isinstance(row, dict):
        raise AdminError(400, f"tools.{name} must be an object")
    clean = {}
    for k, v in row.items():
        if k == "enabled":
            if not isinstance(v, bool):
                raise AdminError(400, f"tools.{name}.enabled must be true or "
                                      f"false")
            clean["enabled"] = v
        elif k == "description" and desc_ok:
            if not isinstance(v, str):
                raise AdminError(400, f"tools.{name}.description must be text")
            if len(v) > LIMITS["description"]:
                raise AdminError(400, f"tools.{name}.description is {len(v)} "
                                      f"characters — {LIMITS['description']} "
                                      f"at most")
            clean["description"] = v
        elif k == "description":
            # a move's description and 'when' list live in its own move file
            raise AdminError(400, f"the description of '{name}' is edited in "
                                  f"SEQUENCES, not here")
        else:
            raise AdminError(400, f"unknown field '{k}' on tools.{name}")
    if not clean:
        raise AdminError(400, f"tools.{name} changes nothing")
    return clean


def _checked_tools(tools):
    if not isinstance(tools, dict):
        raise AdminError(400, "tools must be an object")
    out = {}
    for name, row in tools.items():
        if name == "moves":
            if not isinstance(row, dict):
                raise AdminError(400, "tools.moves must be an object")
            moves = {}
            for mname, mrow in row.items():
                moves[str(mname)] = _checked_tool_row(f"moves.{mname}", mrow,
                                                      desc_ok=False)
            out["moves"] = moves
        else:
            out[str(name)] = _checked_tool_row(str(name), row, desc_ok=True)
    return out


def _checked_patch(body):
    """The shape and the VOICE.md 5.3 length limits.

    Ranges are agent_config's business — it refuses a bad number rather than
    clamping it, and that ValueError becomes the 400 sentence.
    """
    patch = {}
    prompt = body.get("prompt")
    if prompt is not None:
        if not isinstance(prompt, dict):
            raise AdminError(400, "prompt must be an object")
        out = {}
        for k, v in prompt.items():
            if k not in PROMPT_KEYS:
                raise AdminError(400, f"unknown prompt field '{k}'")
            if not isinstance(v, str):
                raise AdminError(400, f"{k} must be text")
            if len(v) > LIMITS[k]:
                raise AdminError(400, f"{k} is {len(v)} characters — "
                                      f"{LIMITS[k]} at most")
            out[k] = v
        if out:
            patch["prompt"] = out
    tools = body.get("tools")
    if tools is not None:
        clean = _checked_tools(tools)
        if clean:
            patch["tools"] = clean
    rec = body.get("recognition")
    if rec is not None:
        if not isinstance(rec, dict):
            raise AdminError(400, "recognition must be an object")
        out = {}
        for k, v in rec.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise AdminError(400, f"recognition.{k} must be a number")
            try:
                out[str(k)] = float(v)
            except OverflowError:
                # json gives a 400-digit literal back as an int, and there is
                # no float that big: without this it is a traceback on the
                # console and a bare 500, instead of the range refusal that
                # 1e400 (inf) and NaN already get from agent_config
                raise AdminError(400, f"recognition.{k} is out of range")
        if out:
            patch["recognition"] = out
    return patch


def _for_agent(ac, patch):
    """The admin patch in whatever shape agent_config's own tree uses."""
    out = {k: v for k, v in patch.items() if k != "prompt"}
    prompt = patch.get("prompt")
    if prompt:
        if _flat_prompt(ac):
            out.update(prompt)
        else:
            out["prompt"] = prompt
    return out


def config_set(body):
    """POST /api/admin/config — validate, write, tell the open decks."""
    patch = _checked_patch(body)
    params = body.get("params")
    if params is not None and not isinstance(params, dict):
        raise AdminError(400, "params must be an object")
    if not patch and not params:
        raise AdminError(400, "there is nothing to change in that body")
    # one writer at a time all the way through: save() re-reads the file,
    # merges and writes it back, so PERSONALITY SAVE and RECOGNITION RESET
    # landing together used to keep only the second one — silently
    with _CFG_LOCK:
        if patch:
            ac = _agent_config()
            try:
                ac.save(_for_agent(ac, patch))
            except ValueError as e:       # agent_config's own range checks
                raise AdminError(400, _sentence(e))
            except AdminError:
                raise
            except Exception as e:
                raise AdminError(500, "the configuration could not be saved: "
                                      f"{_sentence(e)}")
        if params:
            voicelink.set_prefs(params)   # persists and broadcasts by itself
        doc = _config_doc()
    # the deck refreshes on {"t":"voice"}; a config edit only reaches the model
    # at the NEXT session, which is what the panel already says
    voicelink.push_voice()
    return doc


def config_reset(body):
    """POST /api/admin/config/reset — drop one override, or every one."""
    path = body.get("path")
    if not isinstance(path, str) or not path.strip():
        raise AdminError(400, 'body must be {"path": "prompt.instructions"} '
                              'or {"path": "*"}')
    path = path.strip()
    head = path.split(".")[0]
    if head == "params":
        raise AdminError(400, "the speech settings are per machine — they are "
                              "changed, not reset")
    ac = _agent_config()
    targets = [path]
    if path != "*" and _flat_prompt(ac):
        # 'prompt' groups the three texts on the admin page only
        if path == "prompt":
            targets = list(PROMPT_KEYS)
        elif path.startswith("prompt."):
            targets = [path[len("prompt."):]]
    done, failed = 0, None
    with _CFG_LOCK:                       # reset() rewrites the same file a
        for target in targets:            # save() is merging into
            try:
                ac.reset(target)
                done += 1
            except (ValueError, KeyError) as e:
                failed = e                # one of a group holds no override
            except Exception as e:
                raise AdminError(500, "the override could not be dropped: "
                                      f"{_sentence(e)}")
        if not done:
            if isinstance(failed, ValueError):
                raise AdminError(400, _sentence(failed))
            raise AdminError(404, f"nothing at '{path}' to reset")
        doc = _config_doc()
    voicelink.push_voice()
    return doc


# --------------------------------------------------------------- preview ----
def _moves(ac):
    """{name: {seconds, frames, description, when}} — what build_tools eats.

    agent_config's own reader when it has one, so the preview reads the move
    files by exactly the rule the session does. Hidden takes (_take.json) are
    NOT skipped here: the deck hides them, the agent does not, and the point
    of this page is what he will actually be given.
    """
    finder = getattr(ac, "discover_moves", None)
    if callable(finder):
        try:
            moves = finder()
        except TypeError:
            moves = None                  # a different signature: read them
        if isinstance(moves, dict):       # ourselves
            return moves
    moves = {}
    try:
        paths = sorted(MOVES_DIR.glob("*.json"))
    except OSError:
        return moves
    for f in paths:
        try:
            # explicit utf-8: the accents and em-dashes in description/when go
            # straight into the model's tool list, and cp1252 mangles them
            d = json.loads(f.read_text(encoding="utf-8"))
            moves[f.stem] = {"seconds": float(d["frames"][-1]["t"]),
                             "frames": len(d["frames"]),
                             "description": d.get("description", ""),
                             "when": d.get("when") or []}
        except Exception:
            continue                      # unreadable move: the agent skips it
    return moves


def _roster():
    """The roster the agent sends once it is connected, read fresh.

    NEVER fatal. The roster is one of the preview's four blocks; the other
    three — the instructions, the tool list and the session payload — are what
    somebody opened this page to read, and losing all of them because numpy is
    missing or one person file is unparseable is the wrong trade. The agent
    survives the same failure the same way: voice-blind, still talking.
    """
    try:
        return str(voicelink.identity_module().People().roster_text() or "")
    except Exception as e:
        return f"[the roster could not be read: {_sentence(e)}]"


def _session(instructions, tools, prefs):
    """The session.update payload — mirrors live_agent.session_payload()."""
    manual = bool(prefs.get("identify")) and prefs.get("duplex") != "ptt"
    if prefs.get("duplex") == "ptt":
        vad = None                        # manual turns: the mic is only open
    elif prefs.get("vad") == "semantic":  # while the key is held
        vad = {"type": "semantic_vad", "eagerness": "medium",
               "create_response": not manual, "interrupt_response": True}
    else:
        vad = {"type": "server_vad", "threshold": 0.6,
               "prefix_padding_ms": 300, "silence_duration_ms": 600,
               "create_response": not manual, "interrupt_response": True}
    return {"type": "realtime",
            "output_modalities": ["audio"],
            "instructions": instructions,
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": RATE},
                                "noise_reduction": {"type": "far_field"},
                                "turn_detection": vad,
                                "transcription": {"model": TRANSCRIBE_MODEL,
                                                  "language": TRANSCRIBE_LANGUAGE}},
                      "output": {"format": {"type": "audio/pcm", "rate": RATE},
                                 "voice": prefs.get("voice")}},
            "tools": tools,
            "tool_choice": "auto"}


def preview():
    """GET /api/admin/preview — the exact strings and tools of the next session.

    The tool JSON comes from agent_config.build_tools, the same call the agent
    makes, so this page cannot quietly disagree with the session it describes.
    """
    ac = _agent_config()
    cfg = _load(ac)
    try:
        tools = ac.build_tools(_moves(ac), cfg)
    except ValueError as e:
        raise AdminError(400, _sentence(e))
    except Exception as e:
        raise AdminError(500, f"the tool list could not be built: "
                              f"{_sentence(e)}")
    instructions = str(_grouped(cfg)["prompt"].get("instructions") or "")
    prefs = voicelink.prefs()
    # voice-id off means no roster is sent at all, not an empty one
    roster = _roster() if prefs.get("identify") else ""
    return {"instructions": instructions, "roster": roster, "tools": tools,
            "session": _session(instructions, tools, prefs)}
