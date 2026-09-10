// KIOSK.md §3.2 — the lab's logo, the wordmark, and one phrase about how
// Poppy is doing right now.
import { useState } from 'react'
import { useKiosk } from './store'
import type { KioskState } from './store'

type Tone = 'dim' | 'ok' | 'warn' | 'fault' | 'accent'

interface Status {
  text: string
  tone: Tone
  pulse: boolean
  /** the error sentence, shown small under "Something went wrong" */
  detail?: string
}

type StatusInputs = Pick<KioskState, 'wsUp' | 'deckUp' | 'power' | 'error' | 'voice'>

// The order is the contract's: what is broken outranks what is happening,
// and the voice outranks the body because it is what the visitor is doing.
// Called from render on selected primitives — never used AS a zustand
// selector: it builds a new object every time, and a selector that never
// returns the same snapshot twice re-renders for ever (React error #185).
function statusOf(s: StatusInputs): Status {
  if (!s.wsUp) return { text: 'Connexion…', tone: 'dim', pulse: false }
  if (s.deckUp === false) {
    return { text: "Le système de Poppy n'est pas lancé", tone: 'fault', pulse: false }
  }
  if (s.power === 'error') {
    return {
      text: "Quelque chose s'est mal passé",
      tone: 'fault',
      pulse: false,
      detail: s.error ?? undefined,
    }
  }
  const v = s.voice
  if (v && v.on) {
    switch (v.phase) {
      case 'starting':
      case 'connecting':
        return { text: 'Connexion de la voix…', tone: 'warn', pulse: true }
      case 'listening':
        return { text: "À l'écoute", tone: 'ok', pulse: false }
      case 'hearing':
        return { text: 'Il vous entend…', tone: 'accent', pulse: false }
      case 'thinking':
        return { text: 'Il réfléchit…', tone: 'warn', pulse: false }
      case 'speaking':
        return { text: 'Il parle', tone: 'accent', pulse: true }
      case 'error':
        return { text: 'La voix a coupé', tone: 'fault', pulse: false }
      case 'off':
        break // on with phase off is a blink between states; fall to the body
    }
  }
  switch (s.power) {
    case 'off':
      return { text: 'Endormi', tone: 'dim', pulse: false }
    case 'starting':
      return { text: 'Il se réveille…', tone: 'warn', pulse: true }
    case 'ready':
      return { text: 'Réveillé', tone: 'ok', pulse: false }
    case 'playing':
      return { text: 'En mouvement', tone: 'accent', pulse: false }
    case 'recording':
      return { text: 'Il apprend un geste', tone: 'warn', pulse: false }
    case 'released':
      return { text: 'Détendu', tone: 'dim', pulse: false }
    case 'cooling':
      return { text: 'Il refroidit', tone: 'warn', pulse: false }
  }
}

// The logo is not ours to draw: try the png, then the svg, then admit there
// is none. A failed <img> fires onError once per src, so two steps suffice.
// It sits over the stage, top-left (KioskApp), not in this header.
export function Logo() {
  const [step, setStep] = useState(0)
  if (step >= 2) return <div className="logo placeholder">LOGO</div>
  return (
    <img
      className="logo"
      src={step === 0 ? '/lab-logo.png' : '/lab-logo.svg'}
      alt=""
      onError={() => setStep((n) => n + 1)}
    />
  )
}

export default function Header() {
  const wsUp = useKiosk((s) => s.wsUp)
  const deckUp = useKiosk((s) => s.deckUp)
  const power = useKiosk((s) => s.power)
  const error = useKiosk((s) => s.error)
  const voice = useKiosk((s) => s.voice)
  const status = statusOf({ wsUp, deckUp, power, error, voice })
  return (
    <header className="header">
      <div className="title">
        <div className="wordmark">Poppy</div>
        <div className={`status tone-${status.tone}${status.pulse ? ' pulse' : ''}`}>
          <span className="dot" />
          <span>{status.text}</span>
        </div>
        {status.detail && <div className="status-detail">{status.detail}</div>}
      </div>
    </header>
  )
}
