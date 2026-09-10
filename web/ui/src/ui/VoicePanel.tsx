// VOICE.md §4.3 — the live conversation: status strip, transcript, level
// meter and the action keys. The CONFIG block moved to the admin page (§5.4),
// which is now the one place any of Poppy's settings are edited.
import { useEffect, useRef, useState } from 'react'
import { apiVoiceCmd, apiVoicePtt, apiVoiceSet, apiVoiceTag } from '../api'
import { readLevels } from '../audioBus'
import { DEFAULT_PTT_KEY, isPttKey, pttKeyLabel } from '../pttKey'
import { useStore } from '../state'
import type { ChatRow, VoiceDuplex } from '../types'

const SEGS = 7

/** Fast attack, slow release — the agent sends the raw envelope. */
const ATTACK = 0.55
const RELEASE = 0.14

/** Two of these are the meter; the enrolment flow borrows the mic one. */
export function LevelStrip({ label, pick }: { label: string; pick: 'in' | 'out' }) {
  const barsRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const host = barsRef.current
    if (!host) return
    const bars = Array.from(host.children) as HTMLElement[]
    let raf = 0
    let v = 0
    const tick = () => {
      const l = readLevels()
      const target = pick === 'in' ? l.in : l.out
      v += (target - v) * (target > v ? ATTACK : RELEASE)
      const lit = v * SEGS
      for (let i = 0; i < bars.length; i++) {
        const f = Math.max(0, Math.min(1, lit - i))
        bars[i].style.opacity = String(0.16 + 0.84 * f)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [pick])

  return (
    <div className="v-meter">
      <span className="v-meter-label">{label}</span>
      <div className={`v-bars ${pick}`} ref={barsRef}>
        {Array.from({ length: SEGS }, (_, i) => (
          <span key={i} className="v-bar" style={{ height: 4 + i * 1.7 }} />
        ))}
      </div>
    </div>
  )
}

function Row({ r }: { r: ChatRow }) {
  // '?' is the stranger on a heard row (§4.3). A bridge note has no speaker
  // at all, so it gets an empty column rather than borrowing that mark.
  const who =
    r.kind === 'say'
      ? 'POPPY'
      : r.kind === 'tool'
        ? `▸ ${r.text.toUpperCase()}`
        : r.who
          ? r.who.toUpperCase()
          : r.kind === 'heard'
            ? '?'
            : ''

  const text =
    r.kind === 'tool' ? (r.ok === null ? '…' : r.ok ? 'ok' : 'fail') : r.text

  return (
    <div className={`v-row k-${r.kind}`}>
      <span className="v-ts">{r.ts}</span>
      <span className={`v-who${r.kind === 'heard' && !r.who ? ' anon' : ''}`}>
        {who}
      </span>
      <span
        className={
          r.kind === 'tool'
            ? `v-text tool${r.ok === false ? ' bad' : r.ok ? ' good' : ''}`
            : 'v-text'
        }
      >
        {text}
      </span>
      {r.kind === 'heard' && typeof r.score === 'number' && (
        <span className={`v-score${r.verdict === 'tentative' ? ' warn' : ''}`}>
          {r.score.toFixed(2)}
        </span>
      )}
    </div>
  )
}

function Transcript() {
  const chat = useStore((s) => s.chat)
  const logRef = useRef<HTMLDivElement | null>(null)
  const stickRef = useRef(true)
  // Not chat.length: past 80 rows the ring stops growing and only `n` moves.
  const newest = chat.length ? chat[chat.length - 1].n : 0

  // Only chase the newest row when the operator is already at the bottom —
  // never yank the view while they are reading back.
  useEffect(() => {
    const el = logRef.current
    if (!el || !stickRef.current) return
    el.scrollTop = el.scrollHeight
  }, [newest])

  const onScroll = () => {
    const el = logRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  }

  return (
    <div className="v-log" ref={logRef} onScroll={onScroll}>
      {chat.length === 0 && <div className="v-empty">EMPTY</div>}
      {chat.map((r) => (
        <Row key={r.n} r={r} />
      ))}
    </div>
  )
}

function Ptt() {
  const [held, setHeld] = useState(false)
  const heldRef = useRef(false)
  // SPEECH › PTT KEY on the admin page; the same key drives the kiosk's bar
  const code = useStore((s) => s.voice?.ptt_key ?? DEFAULT_PTT_KEY)

  const set = (down: boolean) => {
    if (heldRef.current === down) return
    heldRef.current = down
    setHeld(down)
    apiVoicePtt(down).catch(() => {})
  }

  // The configured key held = the same button. Space belongs to STOP and is
  // never offered as a choice; do not touch it.
  useEffect(() => {
    const inField = (t: EventTarget | null) => {
      const el = t as HTMLElement | null
      return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')
    }
    const kd = (e: KeyboardEvent) => {
      if (!isPttKey(e, code) || e.repeat || inField(e.target)) return
      e.preventDefault()
      set(true)
    }
    const ku = (e: KeyboardEvent) => {
      if (e.code === code) set(false)
    }
    const blur = () => set(false)
    window.addEventListener('keydown', kd)
    window.addEventListener('keyup', ku)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', kd)
      window.removeEventListener('keyup', ku)
      window.removeEventListener('blur', blur)
      set(false) // never leave the mic latched open
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code])

  return (
    <button
      type="button"
      className={`key wide ptt${held ? ' active' : ''}`}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        set(true)
      }}
      onPointerUp={() => set(false)}
      onPointerCancel={() => set(false)}
    >
      HOLD TO TALK · {pttKeyLabel(code)}
    </button>
  )
}

export default function VoicePanel() {
  const voice = useStore((s) => s.voice)
  const [tagging, setTagging] = useState(false)
  const [tag, setTag] = useState('')
  const [liveDuplex, setLiveDuplex] = useState<VoiceDuplex | null>(null)
  // The {"t":"voice"} broadcast arrives after the POST answers — without this
  // a second click on START VOICE just prints a 409 in the log.
  const [busy, setBusy] = useState(false)

  const on = voice?.on === true
  const phase = voice?.phase ?? 'off'
  // Only the spawn itself is un-cancellable; a stuck 'connecting' must stay
  // killable from here.
  const starting = phase === 'starting'

  // A guided enrolment owns the mic: voicelink.start() refuses while one is
  // open. Ending a live session stays possible whatever the enrolment says.
  const enroll = voice?.enroll ?? null
  const enrolling = !on && enroll !== null && enroll.status !== 'done'

  // CONFIG can move `duplex` mid-session, but the agent was LAUNCHED with what
  // it said at spawn, and that is what /api/voice/ptt judges. Latch it, or
  // flipping the preference takes away the only way to talk to a live PTT
  // session — the deck would be lying, and the mic would stay shut.
  useEffect(() => {
    setLiveDuplex(on ? (useStore.getState().voice?.duplex ?? null) : null)
  }, [on])

  const submitTag = () => {
    const name = tag.trim()
    if (!name) return
    // Clear only once the bridge has taken it: a refused name must not vanish
    // with nothing but an ERR line four panels away to show for it.
    apiVoiceTag(name)
      .then(() => {
        setTagging(false)
        setTag('')
      })
      .catch(() => {})
  }

  const toggle = () => {
    if (busy) return
    setBusy(true)
    apiVoiceSet({ on: !on })
      .catch(() => {})
      .finally(() => setBusy(false))
  }

  return (
    <section className="voicepanel">
      <div className={`v-strip p-${phase}`}>
        <span className="v-dot" />
        <span className="v-phase">{phase.toUpperCase()}</span>
        {voice && (
          <span className="v-conf">
            {voice.voice} · {voice.model} · {voice.duplex}
          </span>
        )}
        {voice?.resp && (
          <span className="v-resp">
            <span className="seg-label">RESP</span> {voice.resp.avg.toFixed(2)}s
          </span>
        )}
      </div>
      {voice?.error && <div className="v-err">{voice.error}</div>}

      {on && liveDuplex === 'ptt' && (
        <div className="v-pttwrap">
          <Ptt />
        </div>
      )}

      <Transcript />

      <div className="v-meters">
        <LevelStrip label="IN" pick="in" />
        <LevelStrip label="OUT" pick="out" />
      </div>

      <div className="v-keys">
        <button
          type="button"
          className={`key${on ? ' active' : ''}`}
          disabled={starting || busy || enrolling}
          onClick={toggle}
        >
          {starting
            ? 'LINKING…'
            : enrolling
              ? 'ENROLLING'
              : on
                ? 'END VOICE'
                : 'START VOICE'}
        </button>
        <button
          type="button"
          className="key"
          disabled={!on}
          onClick={() => apiVoiceCmd('interrupt').catch(() => {})}
        >
          INTERRUPT
        </button>
        <button
          type="button"
          className="key"
          disabled={!on}
          onClick={() => apiVoiceCmd('nudge').catch(() => {})}
        >
          NUDGE
        </button>
        <button
          type="button"
          className={`key${tagging ? ' active' : ''}`}
          disabled={!on}
          onClick={() => {
            setTag('')
            setTagging(!tagging)
          }}
        >
          TAG VOICE…
        </button>
      </div>

      {tagging && on && (
        <div className="v-tag">
          <input
            className="name-input"
            autoFocus
            value={tag}
            maxLength={32}
            spellCheck={false}
            autoComplete="off"
            placeholder="name"
            onChange={(e) => setTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submitTag()
              if (e.key === 'Escape') setTagging(false)
            }}
          />
        </div>
      )}
    </section>
  )
}
