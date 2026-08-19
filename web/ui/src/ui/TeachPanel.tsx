import { useEffect, useState } from 'react'
import { apiRecordAbort, apiRecordStart, apiRecordStop, apiState } from '../api'
import { useStore } from '../state'
import { MOTOR_NAMES, motorLabel } from '../types'
import { IconRec } from './icons'

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
            disabled={picked[id] >= 60}
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
      </div>
    </div>
  )
}

function Armed() {
  const recording = useStore((s) => s.recording)
  const motors = useStore((s) => s.motors)
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)

  const nameOf = (id: number) =>
    motors.find((m) => m.id === id)?.name ?? MOTOR_NAMES[id] ?? String(id)

  const loose = recording ? recording.loose : {}
  const valid = NAME_RE.test(name)

  const save = () => {
    if (saving) return
    setSaving(true)
    apiRecordStop(name)
      .then(() => apiState().then((s) => useStore.getState().applyState(s)))
      .catch(() => {})
      .finally(() => setSaving(false))
  }

  const discard = () => {
    if (saving) return
    setSaving(true)
    apiRecordAbort()
      .catch(() => {})
      .finally(() => setSaving(false))
  }

  return (
    <div className="teach-body">
      <Elapsed />
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
      <div className="saveas">
        <span className="teach-hint">SAVE AS</span>
        <input
          className="name-input"
          value={name}
          maxLength={32}
          spellCheck={false}
          autoComplete="off"
          onChange={(e) =>
            setName(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ''))
          }
          onKeyDown={(e) => {
            if (e.repeat) return
            if (e.key === 'Enter' && valid && !saving) save()
          }}
        />
      </div>
      <div className="teach-keys">
        <button
          type="button"
          className="key"
          disabled={!valid || saving}
          onClick={save}
        >
          SAVE
        </button>
        <button
          type="button"
          className="key"
          disabled={saving}
          onClick={discard}
        >
          DISCARD
        </button>
      </div>
    </div>
  )
}

export default function TeachPanel() {
  const power = useStore((s) => s.power)
  const teachActive = useStore((s) => s.teachActive)
  const startTeach = useStore((s) => s.startTeach)

  return (
    <section className="teach">
      <div className="panel-label">TEACH / RECORD</div>
      {power === 'recording' ? (
        <Armed />
      ) : teachActive ? (
        <Picking />
      ) : (
        <div className="teach-body">
          <button
            type="button"
            className="key wide"
            disabled={power !== 'ready'}
            onClick={startTeach}
          >
            TEACH
          </button>
        </div>
      )}
    </section>
  )
}
