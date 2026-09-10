// VOICE.md §5.4 — the VOICE tab's old CONFIG block, moved here whole. These
// are the per-machine session parameters (web/voice_prefs.json). They used to
// go to POST /api/voice, the same ungated route the deck's VOICE key uses to
// start a session — one setting behind two doors, one of them unlocked. That
// route now refuses every preference key, so SAVE goes through the gated
// POST /api/admin/config instead, which is where this page already lives.
import { useEffect, useState } from 'react'
import { apiAudioDevices, apiSpeechSet } from '../../api'
import { pttKeyLabel, pttKeyProblem } from '../../pttKey'
import { useStore } from '../../state'
import type { AudioDevices, VoicePrefs, VoiceState } from '../../types'
import { REALTIME_MODELS, REALTIME_VOICES } from '../../types'
import { Chips, Head, SaveBar } from './bits'

type Prefs = Required<VoicePrefs>

function pick(v: VoiceState): Prefs {
  return {
    voice: v.voice,
    model: v.model,
    vad: v.vad,
    fx: v.fx,
    nudge: v.nudge,
    duplex: v.duplex,
    identify: v.identify,
    gestures: v.gestures ?? true,
    input: v.input,
    output: v.output,
    ptt_key: v.ptt_key,
  }
}

function same(a: Prefs, b: Prefs): boolean {
  return (
    a.voice === b.voice &&
    a.model === b.model &&
    a.vad === b.vad &&
    a.fx === b.fx &&
    a.nudge === b.nudge &&
    a.duplex === b.duplex &&
    a.identify === b.identify &&
    a.gestures === b.gestures &&
    a.input === b.input &&
    a.output === b.output &&
    a.ptt_key === b.ptt_key
  )
}

/** The push-to-talk key: press the button, then press the key you want.
 *  Stored as the physical key code, so it survives a keyboard layout change. */
function KeyPick({ now, onPick }: { now: string; onPick: (code: string) => void }) {
  const [listening, setListening] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    if (!listening) return
    // capture phase, so the deck's own window keys (space = STOP, the current
    // PTT key) never see the press that is meant for this field
    const kd = (e: KeyboardEvent) => {
      e.preventDefault()
      e.stopPropagation()
      if (e.code === 'Escape') {
        setListening(false)
        return
      }
      const why = pttKeyProblem(e.code)
      if (why) {
        setNote(why)
        return
      }
      setNote(null)
      onPick(e.code)
      setListening(false)
    }
    const blur = () => setListening(false)
    window.addEventListener('keydown', kd, true)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', kd, true)
      window.removeEventListener('blur', blur)
    }
  }, [listening, onPick])

  return (
    <>
      <button
        type="button"
        className={`key${listening ? ' active' : ''}`}
        onClick={() => {
          setNote(null)
          setListening(!listening)
        }}
      >
        {listening ? 'PRESS A KEY…' : pttKeyLabel(now)}
      </button>
      <span className={`ad-cval${note ? ' warn' : ''}`}>
        {note ?? 'HOLD TO TALK · DECK AND KIOSK'}
      </span>
    </>
  )
}

function Body({
  live,
  onDirty,
}: {
  live: VoiceState
  onDirty: (d: boolean) => void
}) {
  const [d, setD] = useState<Prefs>(() => pick(live))
  const [devices, setDevices] = useState<AudioDevices | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    apiAudioDevices()
      .then(setDevices)
      .catch(() => {})
  }, [])

  const saved = pick(live)
  const dirty = !same(d, saved)

  useEffect(() => onDirty(dirty), [dirty, onDirty])

  const set = (patch: Partial<Prefs>) => setD((p) => ({ ...p, ...patch }))

  const save = () => {
    setBusy(true)
    setErr(null)
    // `dirty` is the draft measured against `live`, and `live` only moves when
    // something writes it. The {"t":"voice"} broadcast usually does — but a
    // save with the socket down still writes the file, and waiting for a
    // broadcast that is not coming would leave SAVE lit and CLOSE warning
    // about edits that are already on disk. So settle `live` from the answer.
    // The config route answers with the whole admin tree, whose `params` block
    // is what voice_prefs.json now holds; the rest of VoiceState (on, phase,
    // people, ...) is not its business, so the two are merged rather than
    // swapped — and `params` is what the bridge STORED, which is the value to
    // measure against, not the draft that was sent.
    apiSpeechSet(d)
      .then((doc) => {
        const now = useStore.getState().voice
        if (now === null) return
        useStore.getState().setVoice({ ...now, ...(doc.params ?? {}) })
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  const devValue = (n: number | null) => (n === null ? '' : String(n))
  const devPick = (rawValue: string) => (rawValue === '' ? null : Number(rawValue))

  return (
    <>
      <div className="ad-scroll">
        <div className="ad-crow">
          <span className="ad-clabel">VOICE</span>
          <Chips
            values={REALTIME_VOICES}
            now={d.voice as (typeof REALTIME_VOICES)[number]}
            onPick={(voice) => set({ voice })}
          />
        </div>
        <div className="ad-crow">
          <span className="ad-clabel">MODEL</span>
          <Chips
            values={REALTIME_MODELS}
            now={d.model as (typeof REALTIME_MODELS)[number]}
            onPick={(model) => set({ model })}
          />
        </div>
        <div className="ad-crow">
          <span className="ad-clabel">VAD</span>
          <Chips
            values={['semantic', 'server'] as const}
            now={d.vad}
            onPick={(vad) => set({ vad })}
          />
        </div>
        <div className="ad-crow">
          <span className="ad-clabel">DUPLEX</span>
          <Chips
            values={['full', 'gate', 'ptt'] as const}
            now={d.duplex}
            onPick={(duplex) => set({ duplex })}
          />
        </div>
        <div className="ad-crow">
          <span className="ad-clabel">PTT KEY</span>
          <KeyPick now={d.ptt_key} onPick={(ptt_key) => set({ ptt_key })} />
        </div>
        <div className="ad-crow">
          <span className="ad-clabel">IDENTIFY</span>
          <Chips
            values={['on', 'off'] as const}
            now={d.identify ? 'on' : 'off'}
            onPick={(x) => set({ identify: x === 'on' })}
          />
        </div>
        <div className="ad-crow">
          <span className="ad-clabel">GESTURES</span>
          <Chips
            values={['on', 'off'] as const}
            now={d.gestures ? 'on' : 'off'}
            onPick={(x) => set({ gestures: x === 'on' })}
          />
          <span className="ad-cval">SMALL IDLE ROUTINE · ~1/MIN</span>
        </div>
        <div className="ad-crow">
          <span className="ad-clabel">FX</span>
          <input
            className="ad-slider"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={d.fx}
            onChange={(e) => set({ fx: Number(e.target.value) })}
          />
          <span className="ad-cval">{d.fx.toFixed(2)}</span>
        </div>
        <div className="ad-crow">
          <span className="ad-clabel">NUDGE</span>
          <button
            type="button"
            className="stepper"
            disabled={d.nudge <= 0}
            onClick={() => set({ nudge: Math.max(0, d.nudge - 15) })}
          >
            -
          </button>
          <button
            type="button"
            className="stepper"
            disabled={d.nudge >= 600}
            onClick={() => set({ nudge: Math.min(600, d.nudge + 15) })}
          >
            +
          </button>
          <span className="ad-cval">{d.nudge === 0 ? 'OFF' : `${d.nudge}s`}</span>
        </div>
        <div className="ad-crow">
          <span className="ad-clabel">MIC</span>
          <select
            className="ad-select"
            value={devValue(d.input)}
            onChange={(e) => set({ input: devPick(e.target.value) })}
          >
            <option value="">DEFAULT</option>
            {devices?.input.map((x) => (
              <option key={x.i} value={x.i}>
                {x.name}
              </option>
            ))}
          </select>
        </div>
        <div className="ad-crow">
          <span className="ad-clabel">SPEAKER</span>
          <select
            className="ad-select"
            value={devValue(d.output)}
            onChange={(e) => set({ output: devPick(e.target.value) })}
          >
            <option value="">DEFAULT</option>
            {devices?.output.map((x) => (
              <option key={x.i} value={x.i}>
                {x.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      <SaveBar
        dirty={dirty}
        blocked={false}
        busy={busy}
        err={err}
        onSave={save}
        onRevert={() => {
          setD(pick(live))
          setErr(null)
        }}
      />
    </>
  )
}

export default function Speech({ onDirty }: { onDirty: (d: boolean) => void }) {
  const voice = useStore((s) => s.voice)

  return (
    <section className="ad-section">
      <Head title="SPEECH" />
      {voice === null ? (
        <div className="v-empty">NO LINK</div>
      ) : (
        <Body live={voice} onDirty={onDirty} />
      )}
    </section>
  )
}
