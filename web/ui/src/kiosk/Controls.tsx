// KIOSK.md §3.4 — the three buttons, the hold-to-talk bar a push-to-talk
// session needs, and the one strip a refusal lands on.
import { useEffect, useRef, useState } from 'react'
import { DEFAULT_PTT_KEY, isPttKey, pttKeyLabel } from '../pttKey'
import type { VoiceDuplex } from '../types'
import { IconLevel, IconPower } from '../ui/icons'
import { ptt, setPower, setVoice, stand } from './link'
import { useKiosk } from './store'

const TOAST_MS = 5000

// The deck answers in English; visitors read French. Known sentences get a
// real translation, the rest a French lead with the original kept underneath
// for the operator. "Poppy est injoignable" is already ours.
const TOAST_FR: Array<[RegExp, string]> = [
  [/power is off/i, 'Le corps est éteint — appuyez sur Marche'],
  [/already running/i, 'La voix est déjà lancée'],
  [/already moving|already playing/i, 'Il bouge déjà'],
  [/not in push-to-talk/i, "Cette session n'est pas en mode « maintenir »"],
  [/is closing/i, 'La voix est en train de se couper'],
  [/OPENAI_API_KEY/i, "Clé vocale manquante — voyez l'opérateur"],
  [/cooling/i, 'Il refroidit — un instant'],
]
function frMsg(e: unknown): string {
  const m = e instanceof Error ? e.message : String(e)
  for (const [re, fr] of TOAST_FR) if (re.test(m)) return fr
  return m.startsWith('Poppy') ? m : `Ça n'a pas marché — ${m}`
}

// pttKeyLabel speaks English key names (shared with the deck's admin page);
// the kiosk shows French ones.
const KEY_FR: Record<string, string> = {
  'LEFT SHIFT': 'MAJ GAUCHE',
  'RIGHT SHIFT': 'MAJ DROITE',
  'LEFT CTRL': 'CTRL GAUCHE',
  'RIGHT CTRL': 'CTRL DROITE',
  'LEFT ALT': 'ALT GAUCHE',
  'RIGHT ALT': 'ALT DROITE',
  ENTER: 'ENTRÉE',
  'NUMPAD ENTER': 'ENTRÉE PAVÉ NUM.',
  'CAPS LOCK': 'VERR. MAJ',
  'PAGE UP': 'PAGE PRÉC.',
  'PAGE DOWN': 'PAGE SUIV.',
  HOME: 'DÉBUT',
  END: 'FIN',
  INSERT: 'INSER',
}
function frKey(label: string): string {
  return KEY_FR[label] ?? label.replace(/^NUMPAD /, 'PAVÉ NUM. ')
}

/** The deck's HOLD TO TALK, sized for a table: pointer or the configured key. */
function HoldToTalk({ code }: { code: string }) {
  const [held, setHeld] = useState(false)
  const heldRef = useRef(false)
  const setToast = useKiosk((s) => s.setToast)

  const set = (down: boolean) => {
    if (heldRef.current === down) return
    heldRef.current = down
    setHeld(down)
    ptt(down).catch((e: unknown) => {
      // a refused press is worth saying; a refused release is not — the mic
      // is shut either way
      if (down) setToast(frMsg(e))
    })
  }

  useEffect(() => {
    const kd = (e: KeyboardEvent) => {
      if (!isPttKey(e, code) || e.repeat) return
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
      className={`ptt${held ? ' held' : ''}`}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        set(true)
      }}
      onPointerUp={() => set(false)}
      onPointerCancel={() => set(false)}
      onContextMenu={(e) => e.preventDefault()}
    >
      <span className="ptt-label">{held ? 'Parlez…' : 'Maintenir pour parler'}</span>
      <span className="ptt-hint">ou maintenir {frKey(pttKeyLabel(code))}</span>
    </button>
  )
}

/** A standing figure, drawn in the same 12x12 frame as the deck's glyphs. */
function IconStand() {
  return (
    <svg width={12} height={12} viewBox="0 0 12 12" aria-hidden focusable={false}>
      <path d="M6 1.4 A1.2 1.2 0 1 0 6.01 1.4 Z" fill="currentColor" />
      <path d="M6 3.8 L6 7.6" stroke="currentColor" strokeWidth="1.4" fill="none" />
      <path d="M3.4 5.2 L8.6 5.2" stroke="currentColor" strokeWidth="1.2" fill="none" />
      <path d="M6 7.6 L4.3 11" stroke="currentColor" strokeWidth="1.2" fill="none" />
      <path d="M6 7.6 L7.7 11" stroke="currentColor" strokeWidth="1.2" fill="none" />
    </svg>
  )
}

function Toast() {
  const toast = useKiosk((s) => s.toast)
  const setToast = useKiosk((s) => s.setToast)
  useEffect(() => {
    if (toast === null) return
    const t = window.setTimeout(() => setToast(null), TOAST_MS)
    return () => window.clearTimeout(t)
  }, [toast, setToast])
  return <div className={`toast${toast ? ' show' : ''}`}>{toast?.text ?? ''}</div>
}

export default function Controls() {
  const power = useKiosk((s) => s.power)
  const voice = useKiosk((s) => s.voice)
  const deckUp = useKiosk((s) => s.deckUp)
  const setToast = useKiosk((s) => s.setToast)
  // The deck's broadcast lands after the POST answers; a second click in that
  // window would 409. One guard per button so Power does not lock Voice.
  const [busy, setBusy] = useState({ power: false, stand: false, voice: false })

  const powerOn = power !== 'off' && power !== 'error'
  const starting = power === 'starting'
  const canStand = power === 'ready' || power === 'released' || power === 'cooling'

  const voiceOn = voice?.on === true
  const voiceStarting = voice?.phase === 'starting'
  // The admin page can move `duplex` mid-session, but the agent was LAUNCHED
  // with what it said at spawn, and that is what /api/voice/ptt judges. Latch
  // it at the start of the session, like the deck does.
  const [liveDuplex, setLiveDuplex] = useState<VoiceDuplex | null>(null)
  useEffect(() => {
    setLiveDuplex(voiceOn ? (useKiosk.getState().voice?.duplex ?? null) : null)
  }, [voiceOn])
  const pushToTalk = voiceOn && liveDuplex === 'ptt' && !voiceStarting
  // A guided enrolment on the deck holds the mic; the deck refuses to start
  // a session under it, so say so instead of collecting a 409.
  const enroll = voice?.enroll ?? null
  const enrolling = !voiceOn && enroll !== null && enroll.status !== 'done'

  const offline = deckUp !== true

  const run = (key: keyof typeof busy, p: () => Promise<unknown>) => {
    if (busy[key]) return
    setBusy((b) => ({ ...b, [key]: true }))
    p()
      .catch((e: unknown) => setToast(frMsg(e)))
      .finally(() => setBusy((b) => ({ ...b, [key]: false })))
  }

  return (
    <footer className="controls">
      <Toast />
      {pushToTalk && <HoldToTalk code={voice?.ptt_key ?? DEFAULT_PTT_KEY} />}
      <div className="buttons">
        <button
          type="button"
          className={`btn${powerOn ? ' active' : ''}`}
          disabled={offline || starting || busy.power}
          onClick={() => run('power', () => setPower(!powerOn))}
        >
          <span className="icon">
            <IconPower size={22} />
          </span>
          <span className="label">{starting ? 'Réveil…' : 'Marche'}</span>
        </button>
        <button
          type="button"
          // an action, not a state: lit only while the request is out.
          // Lit on 'ready' it never went dark, since standing IS ready.
          className={`btn${busy.stand ? ' active' : ''}`}
          disabled={offline || !canStand || busy.stand}
          onClick={() => run('stand', stand)}
        >
          <span className="icon">
            <IconStand />
          </span>
          <span className="label">Debout</span>
        </button>
        <button
          type="button"
          className={`btn${voiceOn ? ' active' : ''}`}
          disabled={offline || voiceStarting || enrolling || busy.voice}
          onClick={() => run('voice', () => setVoice(!voiceOn))}
        >
          <span className="icon">
            <IconLevel size={22} />
          </span>
          <span className="label">
            {voiceStarting ? 'Connexion…' : enrolling ? 'Occupé' : 'Voix'}
          </span>
        </button>
      </div>
    </footer>
  )
}
