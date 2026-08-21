import { useEffect, useRef, useState } from 'react'
import {
  apiDeleteMove,
  apiRecordAbort,
  apiRecordStart,
  apiRecordStop,
  apiRenameMove,
  apiState,
} from '../api'
import { useStore } from '../state'
import { MOTOR_NAMES, motorLabel } from '../types'
import { IconRec } from './icons'
import {
  listenForStop,
  primeMicPermission,
  voiceSupported,
  type VoiceStatus,
} from '../voice'

const VOICE_KEY = 'poppy.voiceStop'

function voiceEnabled(): boolean {
  try {
    return localStorage.getItem(VOICE_KEY) !== '0'
  } catch {
    return true
  }
}

function setVoiceEnabled(on: boolean): void {
  try {
    localStorage.setItem(VOICE_KEY, on ? '1' : '0')
  } catch {
    /* private window: the toggle just won't persist */
  }
}

const NAME_RE = /^[a-z0-9_-]{1,32}$/

function fmtElapsed(ms: number): string {
  const t = Math.max(0, ms)
  const m = Math.floor(t / 60000)
  const s = Math.floor((t % 60000) / 1000)
  const d = Math.floor((t % 1000) / 100)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(m)}:${p(s)}.${d}`
}

/** "14:01:59" -> ms timestamp today (fallback when recStartedAt is unknown) */
function parseStarted(hms: string): number {
  const m = /^(\d{2}):(\d{2}):(\d{2})$/.exec(hms)
  if (!m) return Date.now()
  const d = new Date()
  d.setHours(Number(m[1]), Number(m[2]), Number(m[3]), 0)
  return d.getTime()
}

function Elapsed() {
  const recStartedAt = useStore((s) => s.recStartedAt)
  const recording = useStore((s) => s.recording)
  const start =
    recStartedAt ?? (recording ? parseStarted(recording.started) : Date.now())
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 100)
    return () => clearInterval(t)
  }, [])
  return <div className="rec-elapsed">{fmtElapsed(now - start)}</div>
}

function Picking() {
  const picked = useStore((s) => s.picked)
  const motors = useStore((s) => s.motors)
  const power = useStore((s) => s.power)
  const cancelTeach = useStore((s) => s.cancelTeach)
  const stepPct = useStore((s) => s.stepPct)
  const [voiceOn, setVoiceOn] = useState(voiceEnabled() && voiceSupported())

  const ids = Object.keys(picked)
    .map(Number)
    .sort((a, b) => a - b)

  const nameOf = (id: number) =>
    motors.find((m) => m.id === id)?.name ?? MOTOR_NAMES[id] ?? String(id)

  return (
    <div className="teach-body">
      <div className="teach-hint">SELECT JOINTS ON HOLOGRAM</div>
      {ids.map((id) => (
        <div key={id} className="pkrow">
          <span className="pkrow-id">{id}</span>
          <span className="pkrow-name">{motorLabel(nameOf(id))}</span>
          <span className="pkrow-pct">{picked[id]}%</span>
          <button
            type="button"
            className="stepper"
            disabled={picked[id] <= 0}
            onClick={() => stepPct(id, -5)}
          >
            -
          </button>
          <button
            type="button"
            className="stepper"
            disabled={picked[id] >= 100}
            onClick={() => stepPct(id, +5)}
          >
            +
          </button>
        </div>
      ))}
      <div className="teach-keys">
        <button
          type="button"
          className="key rec"
          disabled={ids.length === 0 || power !== 'ready'}
          onClick={() => {
            apiRecordStart(useStore.getState().picked).catch(() => {})
          }}
        >
          <span className="keyicon">
            <IconRec size={10} />
          </span>
          ARM
        </button>
        <button type="button" className="key" onClick={cancelTeach}>
          CANCEL
        </button>
        {voiceSupported() && (
          <button
            type="button"
            className={`key voice${voiceOn ? ' on' : ''}`}
            title="say STOP to end the take instead of reaching for the mouse"
            onClick={() => {
              const next = !voiceOn
              setVoiceOn(next)
              setVoiceEnabled(next)
              if (next) primeMicPermission()   // ask now, not mid-pose
            }}
          >
            VOICE {voiceOn ? 'ON' : 'OFF'}
          </button>
        )}
      </div>
    </div>
  )
}

const TAKE = '_take'

function Armed({ onFinished }: { onFinished: () => void }) {
  const recording = useStore((s) => s.recording)
  const motors = useStore((s) => s.motors)
  const [busy, setBusy] = useState(false)
  const [voice, setVoice] = useState<VoiceStatus>('idle')
  const [heard, setHeard] = useState('')

  const nameOf = (id: number) =>
    motors.find((m) => m.id === id)?.name ?? MOTOR_NAMES[id] ?? String(id)

  const loose = recording ? recording.loose : {}

  const finish = () => {
    if (busy) return
    setBusy(true)
    apiRecordStop(TAKE)
      .then(() => {
        onFinished()
        return apiState().then((s) => useStore.getState().applyState(s))
      })
      .catch(() => {})
      .finally(() => setBusy(false))
  }

  // Hands-free finish: both hands are on the robot while teaching.
  const finishRef = useRef(finish)
  finishRef.current = finish
  useEffect(() => {
    if (!voiceEnabled() || !voiceSupported()) return
    let done = false
    const log = (line: string) =>
      useStore.getState().pushEvent(new Date().toTimeString().slice(0, 8), line)
    const cancel = listenForStop(
      () => {
        if (done) return
        done = true
        finishRef.current()          // always the live handler, never a stale one
      },
      (s, text) => {
        setVoice(s)
        if (text) setHeard(text)
      },
      log,
    )
    return cancel
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const discard = () => {
    if (busy) return
    setBusy(true)
    apiRecordAbort()
      .catch(() => {})
      .finally(() => setBusy(false))
  }

  const voiceLine =
    voice === 'listening'
      ? `SAY “STOP” TO FINISH${heard ? ` · ${heard}` : ''}`
      : voice === 'denied'
        ? 'VOICE OFF · MIC BLOCKED'
        : voice === 'offline'
          ? 'VOICE OFF · NO NETWORK'
          : voice === 'unsupported'
            ? 'VOICE OFF · BROWSER'
            : ''

  return (
    <div className="teach-body">
      <Elapsed />
      {voiceLine && (
        <div className={`voice-line${voice === 'listening' ? ' live' : ''}`}>
          {voiceLine}
        </div>
      )}
      <div className="rec-loose">
        {Object.keys(loose)
          .map(Number)
          .sort((a, b) => a - b)
          .map((id) => (
            <span key={id}>
              {id} {motorLabel(nameOf(id))} <b>{loose[String(id)]}%</b>
            </span>
          ))}
      </div>
      <div className="teach-keys">
        <button type="button" className="key" disabled={busy} onClick={finish}>
          FINISH
        </button>
        <button type="button" className="key" disabled={busy} onClick={discard}>
          DISCARD
        </button>
      </div>
    </div>
  )
}

/** Name + the LLM-facing fields, filled in once the body is back at rest. */
function Naming({
  source,
  initial,
  onClose,
}: {
  source: string
  initial?: { name: string; description: string; when: string[] }
  onClose: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [desc, setDesc] = useState(initial?.description ?? '')
  const [when, setWhen] = useState((initial?.when ?? []).join('\n'))
  const [busy, setBusy] = useState(false)
  const valid = NAME_RE.test(name) && !name.startsWith('_')

  const save = () => {
    if (!valid || busy) return
    setBusy(true)
    apiRenameMove(source, name, {
      description: desc.trim(),
      when: when
        .split('\n')
        .map((w) => w.trim())
        .filter(Boolean),
    })
      .then(onClose)                     // stays open on error (name taken…)
      .catch(() => {})
      .finally(() => setBusy(false))
  }

  const discard = () => {
    if (busy) return
    if (initial) {
      onClose()                          // editing: leave the move untouched
      return
    }
    setBusy(true)
    apiDeleteMove(source)
      .catch(() => {})
      .finally(() => {
        setBusy(false)
        onClose()
      })
  }

  return (
    <div className="teach-body">
      <div className="saveas">
        <span className="teach-hint">NAME</span>
        <input
          className="name-input"
          autoFocus
          value={name}
          maxLength={32}
          spellCheck={false}
          autoComplete="off"
          onChange={(e) =>
            setName(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ''))
          }
          onKeyDown={(e) => {
            if (e.repeat) return
            if (e.key === 'Enter') save()
          }}
        />
      </div>
      <div className="metafield">
        <span className="teach-hint">DESCRIPTION</span>
        <textarea
          className="meta-input"
          rows={3}
          maxLength={800}
          spellCheck={false}
          placeholder="what the body does, in Poppy's own terms"
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
        />
      </div>
      <div className="metafield">
        <span className="teach-hint">WHEN · ONE PER LINE</span>
        <textarea
          className="meta-input"
          rows={4}
          spellCheck={false}
          placeholder={'someone walks in\nsomeone is leaving'}
          value={when}
          onChange={(e) => setWhen(e.target.value)}
        />
      </div>
      <div className="teach-keys">
        <button
          type="button"
          className="key"
          disabled={!valid || busy}
          onClick={save}
        >
          SAVE
        </button>
        <button type="button" className="key" disabled={busy} onClick={discard}>
          {initial ? 'CANCEL' : 'DISCARD'}
        </button>
      </div>
    </div>
  )
}

export default function TeachPanel() {
  const power = useStore((s) => s.power)
  const teachActive = useStore((s) => s.teachActive)
  const startTeach = useStore((s) => s.startTeach)
  const editingMove = useStore((s) => s.editingMove)
  const setEditingMove = useStore((s) => s.setEditingMove)
  const moves = useStore((s) => s.moves)
  const [naming, setNaming] = useState(false)

  useEffect(() => {
    if (power === 'off' || power === 'error') setNaming(false)
  }, [power])

  const edited = editingMove
    ? moves.find((m) => m.name === editingMove)
    : undefined

  return (
    <section className="teach">
      <div className="panel-label">
        {naming || edited ? 'MOVE DETAILS' : 'TEACH / RECORD'}
      </div>
      {power === 'recording' ? (
        <Armed onFinished={() => setNaming(true)} />
      ) : naming ? (
        <Naming source={TAKE} onClose={() => setNaming(false)} />
      ) : edited ? (
        <Naming
          source={edited.name}
          initial={{
            name: edited.name,
            description: edited.description ?? '',
            when: edited.when ?? [],
          }}
          onClose={() => setEditingMove(null)}
        />
      ) : teachActive ? (
        <Picking />
      ) : (
        <div className="teach-body">
          <button
            type="button"
            className="key wide"
            disabled={power !== 'ready'}
            onClick={() => {
              // ask for the mic now — never once both hands are on the robot
              if (voiceEnabled() && voiceSupported()) primeMicPermission()
              startTeach()
            }}
          >
            TEACH
          </button>
        </div>
      )}
    </section>
  )
}
