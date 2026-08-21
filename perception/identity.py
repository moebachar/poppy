#!/usr/bin/env python
r"""Who is speaking? — voiceprints + per-person memory for Poppy.

    python perception\identity.py enroll Mohamed   # teach Poppy a voice (mic)
    python perception\identity.py list             # who Poppy knows + facts
    python perception\identity.py test             # live mic identification
    python perception\identity.py forget <name>    # delete someone
    python perception\identity.py fact <name> "..."  # add a fact by hand

Each person is one JSON file in perception/people/ holding:
  - voiceprints: ECAPA-TDNN speaker embeddings (enrolled = permanent,
    adaptive = rolling window learned from confident matches)
  - facts: things Poppy remembers about them
The live agent (live_agent.py) identifies each utterance, tells the model
who is talking, and lets it enroll strangers and remember facts mid-chat.

Voice embeddings need: pip install torch torchaudio speechbrain
(first run downloads the ~80 MB speaker model into perception/models/).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PEOPLE_DIR = ROOT / "perception" / "people"
SESSIONS_DIR = PEOPLE_DIR / "_sessions"
MODELS_DIR = ROOT / "perception" / "models"

EMB_RATE = 16000              # what the speaker model eats
MIC_RATE = 24000              # what the live agent records at

# Matching policy — RAW cosine on unit embeddings (not the rescaled-[0,1]
# convention seen online), scored against a per-person centroid. SpeechBrain's
# VoxCeleb EER point is 0.25; matched-mic conditions push genuine scores up,
# so we sit stricter. Calibrate on real voices if it misbehaves.
# Measured on this rig: one person's own read-aloud clips score 0.63-0.75
# against their centroid, but the SAME voice in live conversation (room
# distance, cross-talk, 2-4 s of speech) fell under 0.32 and was called a
# stranger. Genuine live speech lives roughly 0.30-0.60, so the gates sit
# lower than the clean-speech numbers would suggest.
T_CONFIDENT = 0.36            # >=: that's them (with margin) — no doubt
T_TENTATIVE = 0.26            # >=: probably them; below: a stranger
MARGIN_MIN = 0.06             # best-vs-runner-up gap needed for "confident"
T_ADAPT = 0.45                # stricter gate before LEARNING from a match —
MARGIN_ADAPT = 0.10           # was 0.50, which live speech never reached, so
ADAPT_SECONDS = 2.5           # he never adapted to the room. Long, clean,
                              # unambiguous turns only (poisoning defense).
MIN_ID_SECONDS = 0.9          # shorter utterances: don't judge, carry over
MAX_ENROLLED = 10             # permanent prints per person (never evicted)
MAX_ADAPTIVE = 8              # side-list learned from confident matches
MAX_FACTS = 14


# names that are labels, not people — never become person files
RESERVED = {"poppy", "robot", "stranger", "someone", "somebody", "unknown",
            "everyone", "user", "human", "guest"}


def _slug(name):
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore")
    s = re.sub(r"[^a-z0-9]+", "-", s.decode().lower()).strip("-")
    if not s:   # fully non-Latin name (Arabic, Chinese...): stable per-name
        s = "p-" + hashlib.md5(
            str(name).strip().lower().encode("utf-8")).hexdigest()[:8]
    return s


# ------------------------------------------------------------- embedder ----
class Embedder:
    """Lazy ECAPA-TDNN wrapper: numpy int16 in, unit float32[192] out.

    Loading takes seconds (imports torch); do it on a worker thread via
    ensure_loading() and check .ready before calling embed()."""

    def __init__(self):
        self.model = None
        self.err = None
        self._lock = threading.Lock()
        self._loading = False

    @property
    def ready(self):
        return self.model is not None

    def ensure_loading(self):
        with self._lock:
            if self._loading or self.model is not None:
                return
            self._loading = True
        threading.Thread(target=self._load, daemon=True).start()

    def load_sync(self):
        self._load()
        if self.err:
            raise RuntimeError(self.err)

    def _load(self):
        try:
            t0 = time.time()
            # Windows: symlinks need admin/dev-mode — download real files
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
            import torch  # noqa: F401
            from speechbrain.inference.speaker import EncoderClassifier
            kw = {}
            try:
                from speechbrain.utils.fetching import LocalStrategy
                kw["local_strategy"] = getattr(
                    LocalStrategy, "COPY_SKIP_CACHE", LocalStrategy.COPY)
            except Exception:
                pass
            model = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir=str(MODELS_DIR / "spkrec-ecapa-voxceleb"),
                run_opts={"device": "cpu"}, **kw)
            model.eval()
            # warm up (and prove the whole pipeline works, scipy included)
            # BEFORE publishing — .ready and .err must stay exclusive
            self._embed(model, np.zeros(EMB_RATE, np.int16), EMB_RATE)
            self.model = model
            print(f"  [id] voice model ready ({time.time() - t0:.1f}s)",
                  flush=True)
        except Exception as e:
            self.err = (f"{type(e).__name__}: {e}")
            print(f"  [id] voice model unavailable — {self.err}", flush=True)

    def embed(self, pcm_int16, rate=MIC_RATE):
        return self._embed(self.model, pcm_int16, rate)

    @staticmethod
    def _embed(model, pcm_int16, rate):
        """pcm int16 mono at `rate` -> unit-norm float32 embedding.
        Silence is trimmed first — dead air drags every voice toward a
        common point and inflates impostor similarity."""
        import torch
        from scipy.signal import resample_poly
        x = pcm_int16.astype(np.float32) / 32768.0
        if rate != EMB_RATE:
            from math import gcd
            g = gcd(EMB_RATE, rate)
            x = resample_poly(x, EMB_RATE // g, rate // g).astype(np.float32)
        x = _trim_silence(x)
        with torch.inference_mode():
            emb = model.encode_batch(torch.from_numpy(x).unsqueeze(0))
        v = emb.squeeze().cpu().numpy().astype(np.float32)
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v


def speech_only(pcm_int16, rate=MIC_RATE):
    """Keep only speech-y 20 ms frames (int16 in/out, same rate). Both the
    minimum-length gate AND the audio actually embedded use this: VAD
    padding, room tone and the gaps between words drag every voice toward
    a common point and were costing real recognitions."""
    frame = rate // 50
    n = len(pcm_int16) // frame
    if n < 4:
        return pcm_int16
    frames = pcm_int16[:n * frame].reshape(n, frame)
    rms = np.sqrt((frames.astype(np.float32) ** 2).mean(axis=1))
    ref = np.percentile(rms, 90)
    keep = rms > max(ref * 0.12, 3.0)
    return frames[keep].reshape(-1)


def _trim_silence(x, rate=EMB_RATE, keep_ratio=0.12):
    """Drop 20 ms frames whose RMS is far below the utterance's loud frames.
    Falls back to the untrimmed signal if less than 0.5 s survives."""
    frame = rate // 50
    n = len(x) // frame
    if n < 4:
        return x
    frames = x[:n * frame].reshape(n, frame)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    ref = np.percentile(rms, 90)
    keep = rms > max(ref * keep_ratio, 1e-4)
    if keep.sum() * frame < rate // 2:
        return x
    return frames[keep].reshape(-1)


# ---------------------------------------------------------------- store ----
class People:
    """perception/people/*.json — voiceprints + facts, one file per person."""

    def __init__(self):
        self.people = {}                   # slug -> dict
        self._cents = {}                    # slug -> np.ndarray [n, 192]
        PEOPLE_DIR.mkdir(parents=True, exist_ok=True)
        for f in sorted(PEOPLE_DIR.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                self.people[f.stem] = d
                self._remat(f.stem)
            except Exception as e:
                print(f"  [id] unreadable person file {f.name}: {e}",
                      flush=True)

    def _remat(self, slug):
        """Per person: an enrollment-weighted centroid (drift is bounded by
        construction — enrolled prints always dominate adapted ones)."""
        d = self.people[slug]
        en = np.asarray(d.get("voiceprints", []) or [], dtype=np.float32)
        ad = np.asarray(d.get("adaptive_prints", []) or [], dtype=np.float32)
        cent = None
        if en.size and ad.size:
            cent = 0.6 * en.mean(0) + 0.4 * ad.mean(0)
        elif en.size:
            cent = en.mean(0)
        elif ad.size:
            cent = ad.mean(0)
        if cent is not None:
            n = float(np.linalg.norm(cent))
            cent = (cent / n).astype(np.float32) if n > 0 else None
        self._cents[slug] = cent

    def _save(self, slug):
        p = self.people[slug]
        tmp = PEOPLE_DIR / (slug + ".json.tmp")
        tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, PEOPLE_DIR / (slug + ".json"))

    def names(self):
        return [d["name"] for d in self.people.values()]

    def get(self, name):
        return self.people.get(_slug(name))

    # --- matching ---
    def match(self, emb):
        """-> (name|None, score, verdict, margin) — verdict in
        confident / tentative / unknown / nobody-enrolled."""
        scored = []
        for slug, cent in self._cents.items():
            if cent is not None and cent.shape == emb.shape:
                scored.append((float(cent @ emb), slug))
        if not scored:
            return None, 0.0, "nobody-enrolled", 0.0
        scored.sort(reverse=True)
        best, slug = scored[0]
        margin = best - (scored[1][0] if len(scored) > 1 else -1.0)
        name = self.people[slug]["name"]
        if best >= T_CONFIDENT and margin >= MARGIN_MIN:
            return name, best, "confident", margin
        if best >= T_TENTATIVE:
            return name, best, "tentative", margin
        return None, best, "unknown", margin

    def voice_conflict(self, name, embs):
        """True if `name` already exists with a DIFFERENT-sounding voice —
        enrolling would silently merge two people into one identity."""
        slug = _slug(name)
        cent = self._cents.get(slug)
        d = self.people.get(slug)
        if cent is None or d is None or not d.get("voiceprints") or not embs:
            return False
        best = max(float(cent @ e) for e in embs)
        return best < 0.30

    # --- writes ---
    def enroll(self, name, embs, adaptive=False, distinct=False):
        """distinct=True: if that name is taken by a DIFFERENT voice, make a
        new person ("Sara 2") instead of merging two humans into one file."""
        name = " ".join(str(name).split())
        if distinct and self.voice_conflict(name, embs):
            base, i = name, 2
            while self.voice_conflict(f"{base} {i}", embs) and i < 9:
                i += 1
            name = f"{base} {i}"
        slug = _slug(name)
        d = self.people.setdefault(slug, {
            "name": name.strip(), "created": datetime.now().isoformat(" ", "seconds"),
            "voiceprints": [], "adaptive_prints": [], "facts": [],
            "encounters": 0})
        key = "adaptive_prints" if adaptive else "voiceprints"
        cap = MAX_ADAPTIVE if adaptive else MAX_ENROLLED
        for e in embs:
            d.setdefault(key, []).append([round(float(x), 5) for x in e])
        while len(d[key]) > cap:
            if adaptive:                   # evict the most REDUNDANT print
                m = np.asarray(d[key], np.float32)     # (keeps diversity,
                sims = m @ m.T                          # unlike FIFO)
                np.fill_diagonal(sims, -1)
                d[key].pop(int(np.argmax(sims.max(axis=1))))
            else:
                d[key].pop(0)
        d["last_seen"] = datetime.now().isoformat(" ", "seconds")
        self._remat(slug)
        self._save(slug)
        return slug

    def saw(self, name):
        d = self.get(name)
        if d:
            d["last_seen"] = datetime.now().isoformat(" ", "seconds")
            d["encounters"] = d.get("encounters", 0) + 1
            self._save(_slug(name))

    def remember(self, name, fact, create=False):
        d = self.get(name)
        if d is None:
            if (not create or not str(name).strip()
                    or str(name).strip().lower() in RESERVED):
                return False               # labels are not people
            # someone Poppy heard ABOUT but has never heard speak
            self.enroll(name, [])
            d = self.get(name)
        fact = " ".join(str(fact).split())[:300]
        if fact and not any(f["text"].lower() == fact.lower()
                            for f in d["facts"]):
            d["facts"].append({"t": datetime.now().strftime("%Y-%m-%d"),
                               "text": fact})
            d["facts"] = d["facts"][-MAX_FACTS:]
            self._save(_slug(name))
        return True

    def forget(self, name):
        slug = _slug(name)
        if slug in self.people:
            del self.people[slug]
            self._cents.pop(slug, None)
            (PEOPLE_DIR / (slug + ".json")).unlink(missing_ok=True)
            return True
        return False

    # --- context for the model ---
    def roster_text(self, limit=1400):
        if not self.people:
            return ""
        rows = []
        order = sorted(self.people.values(),
                       key=lambda d: d.get("last_seen", ""), reverse=True)
        for d in order:
            facts = "; ".join(f["text"] for f in d.get("facts", [])[-6:])
            rows.append(f"- {d['name']}" + (f": {facts}" if facts else ""))
        text = "People you know by voice:\n" + "\n".join(rows)
        return text[:limit]


# --------------------------------------------------------- session log -----
class SessionLog:
    """Append-only who-said-what log; food for the end-of-session
    fact extractor and a nice keepsake."""

    def __init__(self):
        self.path = SESSIONS_DIR / (
            datetime.now().strftime("%Y%m%d-%H%M%S") + ".jsonl")
        self.n = 0

    def add(self, who, text):
        text = (text or "").strip()
        if not text:
            return
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"t": datetime.now().isoformat(" ", "seconds"),
               "who": who, "text": text}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.n += 1


def extract_facts(api_key, people, log_path, model="gpt-4.1-mini"):
    """Post-session: mine the transcript for lasting facts about each known
    person (including what they said to EACH OTHER) and merge them in."""
    try:
        lines = [json.loads(x) for x in
                 Path(log_path).read_text(encoding="utf-8").splitlines() if x]
    except Exception:
        return 0
    if len(lines) < 4:
        return 0
    convo = "\n".join(f"{r['who']}: {r['text']}" for r in lines)[-12000:]
    known = {d["name"]: [f["text"] for f in d.get("facts", [])]
             for d in people.people.values()}
    sysmsg = (
        "You mine a conversation transcript for LASTING facts about the "
        "humans in it (never about 'poppy', the robot). Facts must be worth "
        "remembering weeks later: who they are, relationships between the "
        "people, preferences, life events, running jokes. Skip small talk, "
        "one-off logistics, and anything already in the known facts. Reply "
        "with ONLY a JSON object mapping person name -> list of NEW short "
        "fact strings (empty object if nothing).")
    user = (f"Known people and their existing facts:\n"
            f"{json.dumps(known, ensure_ascii=False)}\n\n"
            f"Transcript (speaker: text):\n{convo}")
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps({
                "model": model,
                "messages": [{"role": "system", "content": sysmsg},
                             {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
                "max_tokens": 500,
            }).encode(),
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            out = json.loads(r.read())
        found = json.loads(out["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"  [id] fact extraction skipped ({e})", flush=True)
        return 0
    added = 0
    for name, facts in (found.items() if isinstance(found, dict) else []):
        if people.get(name) is None:
            continue                       # only people Poppy knows by voice
        for fact in (facts if isinstance(facts, list) else []):
            if isinstance(fact, str) and people.remember(name, fact):
                added += 1
    return added


# ------------------------------------------------------------------ CLI ----
def _record(seconds, rate=MIC_RATE):
    import sounddevice as sd
    print(f"    recording {seconds:.0f}s... speak now")
    x = sd.rec(int(seconds * rate), samplerate=rate, channels=1, dtype="int16")
    sd.wait()
    return x.reshape(-1)


# Prompts, not scripts: reading aloud produces a flat "reading voice" that
# scores poorly against the lively voice people actually converse in — the
# enrolment channel has to match the channel he will hear you on.
ENROLL_PROMPTS = [
    "Tell Poppy what you did this morning — just talk, whatever comes.",
    "Describe the room you are in right now, out loud.",
    "Say what you are working on at the lab these days.",
    "Tell him about something you would do with a completely free day.",
]


def cli():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("enroll"); p.add_argument("name")
    sub.add_parser("list")
    sub.add_parser("test")
    p = sub.add_parser("forget"); p.add_argument("name")
    p = sub.add_parser("fact"); p.add_argument("name"); p.add_argument("text")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    people = People()

    if args.cmd == "list":
        if not people.people:
            print("Poppy doesn't know anyone yet. Try: identity.py enroll <name>")
        for d in people.people.values():
            n_pr = len(d.get("voiceprints", [])) + len(d.get("adaptive_prints", []))
            print(f"{d['name']:15s} prints={n_pr:2d} "
                  f"last seen {d.get('last_seen', '?')}")
            for f in d.get("facts", []):
                print(f"    - ({f['t']}) {f['text']}")
        return

    if args.cmd == "forget":
        print("forgotten." if people.forget(args.name) else "unknown name.")
        return

    if args.cmd == "fact":
        print("noted." if people.remember(args.name, args.text)
              else "unknown name — enroll them first.")
        return

    emb = Embedder()
    print("loading voice model (first time downloads ~80 MB)...")
    emb.load_sync()

    if args.cmd == "enroll":
        n = len(ENROLL_PROMPTS)
        print(f"{chr(10)}Enrolling {args.name} — TALK, do not read. Speak the "
              f"way you would to a person, at the distance you normally sit "
              f"from the mic. Keep going until the recording stops.")
        embs = []
        for i, prompt in enumerate(ENROLL_PROMPTS, 1):
            input(f"{chr(10)}  {i}/{n}  {prompt}{chr(10)}    press Enter, "
                  f"then talk: ")
            pcm = _record(8.0)
            level = float(np.abs(pcm.astype(np.float32)).mean())
            if level < 40:
                print("    (that was almost silence — let us redo it)")
                input("    press Enter, then talk: ")
                pcm = _record(8.0)
            voiced = len(speech_only(pcm)) / MIC_RATE
            if voiced < 2.0:
                print(f"    (only {voiced:.1f}s of actual speech there — try "
                      f"to keep talking through the whole recording)")
            embs.append(emb.embed(pcm))
        sims = [float(np.dot(embs[i], embs[j]))
                for i in range(n) for j in range(i + 1, n)]
        print(f"\n  self-consistency {min(sims):.2f}..{max(sims):.2f} "
              f"(same voice should be > {T_TENTATIVE:.2f})")
        if min(sims) < T_TENTATIVE:
            print("  ! recordings disagree — noisy room or mixed voices; "
                  "consider re-running enroll.")
        people.enroll(args.name, embs)
        name, score, verdict, _ = people.match(embs[0])
        print(f"  saved. sanity check: recording #1 -> {name} "
              f"({score:.2f}, {verdict})")
        return

    if args.cmd == "test":
        print("\nLive test — press Enter, speak a sentence, see who Poppy "
              "thinks you are. Ctrl+C to stop.")
        while True:
            input("\n  press Enter, then speak: ")
            pcm = _record(4.0)
            name, score, verdict, margin = people.match(emb.embed(pcm))
            print(f"  -> {name or 'a stranger'}  (score {score:.2f}, "
                  f"margin {margin:.2f}, {verdict})")


if __name__ == "__main__":
    try:
        cli()
    except KeyboardInterrupt:
        print("\nbye.")
