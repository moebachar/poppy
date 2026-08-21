// VOICE.md §4.4 — who Poppy knows: the roster, the guided enrolment, and the
// read-only session log.
import { useEffect, useState } from 'react'
import {
  apiAddFact,
  apiDeleteFact,
  apiEnrollCancel,
  apiEnrollFinish,
  apiEnrollRecord,
  apiEnrollStart,
  apiForgetPerson,
  apiRenamePerson,
  apiSession,
  apiSessions,
  refreshPeople,
} from '../api'
import { useStore } from '../state'
import type {
  EnrollState,
  Person,
  SessionInfo,
  SessionRow,
  VoiceState,
} from '../types'
import { LevelStrip } from './VoicePanel'

const CLIP_SECONDS = 8

/** "2026-08-21 10:53" -> "21/08 10:53" */
function fmtWhen(s: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/.exec(s)
  return m ? `${m[3]}/${m[2]} ${m[4]}` : s
}

function PersonBlock({ p }: { p: Person }) {
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(p.name)
  const [confirming, setConfirming] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [fact, setFact] = useState('')
  const [saving, setSaving] = useState(false)

  const rename = () => {
    const to = name.trim()
    if (saving) return
    if (!to || to === p.name) {
      setRenaming(false)
      return
    }
    // Close the field only once the write lands. A 409 on a name someone else
    // already has used to look like it worked: the field shut, and the roster
    // quietly refreshed back to the old name a moment later.
    setSaving(true)
    apiRenamePerson(p.name, to)
      .then(() => setRenaming(false))
      .catch(() => {})
      .finally(() => setSaving(false))
  }

  const forget = () => {
    if (confirmText.trim().toLowerCase() !== 'forget') return
    apiForgetPerson(p.name).catch(() => {})
    setConfirming(false)
    setConfirmText('')
  }

  const addFact = () => {
    const text = fact.trim()
    if (!text) return
    // Empty the field only once it is written: a 404 on a person renamed from
    // another deck must not swallow what was typed.
    apiAddFact(p.name, text)
      .then(() => setFact(''))
      .catch(() => {})
  }

  return (
    <div className="pp-person">
      <div className="pp-head">
        {renaming ? (
          <input
            className="name-input pp-rename"
            autoFocus
            value={name}
            maxLength={40}
            spellCheck={false}
            autoComplete="off"
            disabled={saving}
            onChange={(e) => setName(e.target.value)}
            onBlur={rename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') rename()
              if (e.key === 'Escape') {
                setName(p.name)
                setRenaming(false)
              }
            }}
          />
        ) : (
          <button
            type="button"
            className="pp-name"
            onClick={() => {
              setName(p.name)
              setRenaming(true)
            }}
          >
            {p.name.toUpperCase()}
          </button>
        )}
        {confirming ? (
          <span className="seq-confirm pp-confirm">
            <input
              autoFocus
              value={confirmText}
              placeholder="type forget"
              onChange={(e) => setConfirmText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') forget()
                if (e.key === 'Escape') setConfirming(false)
              }}
              onBlur={() => setConfirming(false)}
            />
          </span>
        ) : (
          <span className="pp-meta">
            <span>
              {p.prints}+{p.adaptive} PRINTS
            </span>
            <span>{p.facts.length} FACTS</span>
            <span>{fmtWhen(p.last_seen)}</span>
          </span>
        )}
        {!confirming && (
          <button
            type="button"
            className="seq-del"
            onClick={() => {
              setConfirmText('')
              setConfirming(true)
            }}
          >
            ×
          </button>
        )}
      </div>

      {p.facts.map((f, i) => (
        <div key={`${f.t}-${i}`} className="pp-fact">
          <span className="pp-facttext">{f.text}</span>
          <button
            type="button"
            className="seq-del"
            onClick={() => apiDeleteFact(p.name, i).catch(() => {})}
          >
            ×
          </button>
        </div>
      ))}

      <div className="pp-addfact">
        <span className="pp-plus">+ FACT</span>
        <input
          className="name-input"
          value={fact}
          maxLength={300}
          spellCheck={false}
          autoComplete="off"
          onChange={(e) => setFact(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') addFact()
            if (e.key === 'Escape') setFact('')
          }}
        />
      </div>
    </div>
  )
}

function Countdown() {
  const [left, setLeft] = useState(CLIP_SECONDS)
  useEffect(() => {
    const t0 = Date.now()
    const id = setInterval(
      () => setLeft(Math.max(0, CLIP_SECONDS - (Date.now() - t0) / 1000)),
      100,
    )
    return () => clearInterval(id)
  }, [])
  return <span className="pp-count">{left.toFixed(1)}s</span>
}

/** The enrol endpoints all answer with the new VoiceState — apply it now, the
 *  broadcast that follows only confirms it. */
function applyVoice(p: Promise<VoiceState>): void {
  p.then((v) => useStore.getState().setVoice(v)).catch(() => {})
}

/** Same, for the 8 s clip. CANCEL during a recording leaves the answer in
 *  flight: it must never repaint whoever is being enrolled by then. */
function applyClip(p: Promise<VoiceState>, name: string): void {
  p.then((v) => {
    const shown = useStore.getState().voice?.enroll ?? null
    if (!shown || shown.name !== name || v.enroll?.name !== name) return
    useStore.getState().setVoice(v)
  }).catch(() => {})
}

function Guided({ e }: { e: EnrollState }) {
  const step = Math.min(e.step + 1, e.of)
  const recording = e.status === 'recording'
  const done = e.status === 'done'
  const full = e.step >= e.of

  return (
    <div className="pp-enrol">
      <div className="pp-erow">
        <span className="pp-ename">{e.name.toUpperCase()}</span>
        {!done && <span className="pp-estep">{`${step}/${e.of}`}</span>}
        {recording && <Countdown />}
      </div>
      {e.status === 'loading' && <div className="pp-hint">LOADING</div>}
      {!done && e.status !== 'loading' && (
        <div className="pp-prompt">{e.prompt}</div>
      )}
      {/* 'done' also ends a flow that never started — a voice model that would
          not load says so here, and that sentence is not good news. */}
      {e.note && (
        <div className={`pp-note${done && e.clips > 0 ? ' good' : ''}`}>
          {e.note}
        </div>
      )}
      <LevelStrip label="MIC" pick="in" />
      <div className="teach-keys">
        {!done && (
          <button
            type="button"
            className="key"
            disabled={e.status !== 'ready' || full}
            onClick={() => applyClip(apiEnrollRecord(), e.name)}
          >
            {e.note ? 'REDO' : 'RECORD'}
          </button>
        )}
        {!done && (
          <button
            type="button"
            className="key"
            disabled={e.status !== 'ready' || e.clips < 2}
            onClick={() => applyVoice(apiEnrollFinish())}
          >
            SAVE
          </button>
        )}
        <button
          type="button"
          className="key"
          onClick={() => applyVoice(apiEnrollCancel())}
        >
          {done ? 'CLOSE' : 'CANCEL'}
        </button>
      </div>
    </div>
  )
}

function Enrol() {
  const enroll = useStore((s) => s.voice?.enroll ?? null)
  const live = useStore((s) => s.voice?.on === true)
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')

  useEffect(() => {
    if (enroll) setNaming(false)
  }, [enroll])

  if (enroll) return <Guided e={enroll} />

  if (naming) {
    // A session can go live while the name is being typed — the mic is then
    // taken and enroll/start would 409.
    const start = () => {
      const n = name.trim()
      if (!n || live) return
      applyVoice(apiEnrollStart(n))
    }
    return (
      <div className="pp-enrol">
        <input
          className="name-input"
          autoFocus
          value={name}
          maxLength={40}
          spellCheck={false}
          autoComplete="off"
          placeholder="name"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') start()
            if (e.key === 'Escape') setNaming(false)
          }}
        />
        <div className="teach-keys">
          <button
            type="button"
            className="key"
            disabled={!name.trim() || live}
            onClick={start}
          >
            {live ? 'VOICE LIVE' : 'START'}
          </button>
          <button type="button" className="key" onClick={() => setNaming(false)}>
            CANCEL
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="pp-enrol">
      <button
        type="button"
        className="key wide"
        disabled={live}
        onClick={() => {
          setName('')
          setNaming(true)
        }}
      >
        {live ? 'VOICE LIVE' : 'ENROL A VOICE'}
      </button>
    </div>
  )
}

function Sessions() {
  const live = useStore((s) => s.voice?.on === true)
  const [list, setList] = useState<SessionInfo[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const [rows, setRows] = useState<SessionRow[]>([])

  // Refresh on mount and whenever a session ends — that is when a new file
  // appears on disk.
  useEffect(() => {
    apiSessions()
      .then(setList)
      .catch(() => {})
  }, [live])

  const pick = (file: string) => {
    if (open === file) {
      setOpen(null)
      return
    }
    setOpen(file)
    setRows([])
    apiSession(file)
      .then((r) => setRows(r.rows))
      .catch(() => setOpen(null))
  }

  return (
    <div className="pp-sessions">
      <div className="panel-label">SESSIONS</div>
      {list.length === 0 && <div className="v-empty">EMPTY</div>}
      {list.map((s) => (
        <div key={s.file}>
          <button
            type="button"
            className={`pp-srow${open === s.file ? ' on' : ''}`}
            onClick={() => pick(s.file)}
          >
            <span className="pp-swhen">{fmtWhen(s.when)}</span>
            <span className="pp-slines">{s.lines} lines</span>
            <span className="pp-swho">{s.who.join(', ')}</span>
          </button>
          {open === s.file && (
            <div className="pp-stranscript">
              {rows.map((r, i) => (
                <div key={i} className="v-row">
                  <span className="v-ts">{r.t}</span>
                  <span className="v-who">{r.who.toUpperCase()}</span>
                  <span className="v-text">{r.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default function PeoplePanel() {
  const people = useStore((s) => s.people)

  useEffect(() => {
    refreshPeople()
  }, [])

  return (
    <section className="peoplepanel">
      <div className="pp-list">
        {people.length === 0 && <div className="v-empty">EMPTY</div>}
        {people.map((p) => (
          <PersonBlock key={p.slug} p={p} />
        ))}
        <Enrol />
        <Sessions />
      </div>
    </section>
  )
}
