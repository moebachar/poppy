// Thin bridge between the zustand store and the hologram module.
// Creates the module once, pushes state diffs in, routes pick/hover back.
import { useEffect, useRef, useState } from 'react'
import { createHolo } from '../holo'
import type { HoloMode, HoloMotor, VoicePhase } from '../holo'
import { readLevels, subscribeLevels } from '../audioBus'
import { useStore } from '../state'
import type { DeckState } from '../state'
import type { Power, VoiceState } from '../types'

/** VOICE.md §3 — the aura's ceiling; the module wants a cheap setter, not a feed. */
const AURA_FRAME = 1000 / 30

function modeOf(p: Power): HoloMode {
  if (p === 'starting') return 'awakening'
  if (p === 'off' || p === 'error') return 'dormant'
  return 'live' // ready | playing | recording | released | cooling
}

// The bridge's phase union is the aura's plus two states the field has no look
// for: 'starting' is the spawn, which reads as 'connecting'; 'error' means
// there is nothing left to listen to, so the field goes away.
function voicePhaseOf(v: VoiceState | null): VoicePhase {
  if (!v) return 'off'
  if (v.on) {
    if (v.phase === 'starting') return 'connecting'
    if (v.phase === 'error' || v.phase === 'off') return 'off'
    return v.phase
  }
  // No session, but a guided enrolment holds the mic and streams its envelope
  // (VOICE.md §2.5): the aura reacting to the person is the whole reason that
  // flow lives in the deck instead of a terminal.
  const e = v.enroll
  if (e && e.status !== 'done') {
    return e.status === 'recording' ? 'hearing' : 'listening'
  }
  return 'off'
}

function motorsOf(s: DeckState): HoloMotor[] {
  const showPick = s.teachActive || s.power === 'recording'
  return s.motors.map((m) => ({
    id: m.id,
    ok: m.ok,
    present: m.present,
    picked: showPick && m.id in s.picked,
    hover: s.hoveredMotor === m.id && s.hoverSource === 'row',
  }))
}

export default function HoloStage() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const holoRef = useRef<ReturnType<typeof createHolo> | null>(null)
  const [view, setView] = useState<'front' | 'top' | 'side'>('front')

  const pickView = (v: 'top' | 'side') => {
    const next = view === v ? 'front' : v
    setView(next)
    holoRef.current?.setView(next)
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const holo = createHolo(canvas)
    holoRef.current = holo
    holo.onMotorPick((id) => useStore.getState().togglePick(id))
    holo.onMotorHover((id) => useStore.getState().setHovered(id, 'holo'))
    holo.onAwakened(() => useStore.getState().clearAwaken())

    let lastMode: HoloMode | null = null
    let lastPose: Record<string, number> | null = null
    let lastMotorsKey = ''
    let lastPickable: boolean | null = null
    let lastHighlight: number | null = null
    let awakenTimer: number | undefined
    let lastPower: Power | null = null
    let zeroTimer: number | undefined

    // ---- the voice aura (VOICE.md §3, §4.1) ------------------------------
    // Levels arrive 30 times a second and must never reach React, so they come
    // off the module-scope bus and go straight into the module — the same shape
    // as the store subscription below, outside the render tree entirely.
    let auraPhase: VoicePhase = 'off'
    let auraTimer: number | undefined

    // The one place that talks to setVoice: a level packet, a phase change and
    // the stale-feed timer all come through here, so only ever one is pending.
    const drive = () => {
      window.clearTimeout(auraTimer)
      if (auraPhase === 'off') return
      const l = readLevels()
      holo.setVoice({ phase: auraPhase, out: l.out, in: l.in, bands: l.bands })
      // A feed that STOPS is not the same as silence. audioBus decays a stale
      // reading, but only when something asks — so keep asking until it has
      // actually bled out, or the field freezes lit on the last packet before
      // the socket dropped. Two frames of slack: a live feed re-arms first.
      if (l.out > 0.002 || l.in > 0.002) {
        auraTimer = window.setTimeout(drive, AURA_FRAME * 2)
      }
    }

    const setAuraPhase = (p: VoicePhase) => {
      if (p === auraPhase) return
      auraPhase = p
      if (p === 'off') {
        window.clearTimeout(auraTimer)
        holo.setVoice(null) // the aura fades itself out, then frees itself
        return
      }
      drive() // paint the new phase now, do not wait for the next packet
    }

    const unsubLevels = subscribeLevels(drive)

    const push = (s: DeckState) => {
      setAuraPhase(voicePhaseOf(s.voice))

      const mode = modeOf(s.power)
      if (mode !== lastMode) {
        lastMode = mode
        holo.setMode(mode)
      }

      // Auto-zero: every arrival at 'ready' means the body just settled into
      // its stance — snapshot the real positions as the twin's neutral.
      if (s.power !== lastPower) {
        lastPower = s.power
        if (s.power === 'ready') {
          window.clearTimeout(zeroTimer)
          zeroTimer = window.setTimeout(() => {
            const pos = useStore.getState().latestPos
            if (Object.keys(pos).length >= 10) holo.setZero(pos)
          }, 800)
        }
      }

      if (s.latestPos !== lastPose) {
        lastPose = s.latestPos
        holo.setPose(s.latestPos)
      }

      const hm = motorsOf(s)
      const key = JSON.stringify(hm)
      if (key !== lastMotorsKey) {
        lastMotorsKey = key
        holo.setMotors(hm)
      }

      const pickable = s.teachActive && s.power === 'ready'
      if (pickable !== lastPickable) {
        lastPickable = pickable
        holo.setPickable(pickable)
      }

      const highlight = s.hoverSource === 'row' ? s.hoveredMotor : null
      if (highlight !== lastHighlight) {
        lastHighlight = highlight
        holo.setHighlight(highlight)
      }

      // Fallback: if the module never fires onAwakened (stub), release the
      // STARTING state word shortly after READY.
      if (s.power === 'ready' && s.awaitingAwaken && awakenTimer === undefined) {
        awakenTimer = window.setTimeout(
          () => useStore.getState().clearAwaken(),
          2600,
        )
      }
      if (!s.awaitingAwaken && awakenTimer !== undefined) {
        window.clearTimeout(awakenTimer)
        awakenTimer = undefined
      }
    }

    push(useStore.getState())
    const unsub = useStore.subscribe(push)

    const ro = new ResizeObserver(() => holo.resize())
    if (canvas.parentElement) ro.observe(canvas.parentElement)

    return () => {
      unsub()
      unsubLevels()
      ro.disconnect()
      if (awakenTimer !== undefined) window.clearTimeout(awakenTimer)
      window.clearTimeout(zeroTimer)
      window.clearTimeout(auraTimer)
      holoRef.current = null
      holo.dispose()
    }
  }, [])

  return (
    <>
      <canvas ref={canvasRef} className="holo-canvas" />
      <div className="stage-tools">
        <button
          className={view === 'top' ? 'stage-reset active' : 'stage-reset'}
          onClick={() => pickView('top')}
        >
          TOP VIEW
        </button>
        <button
          className={view === 'side' ? 'stage-reset active' : 'stage-reset'}
          onClick={() => pickView('side')}
        >
          SIDE VIEW
        </button>
        <button
          className="stage-reset"
          onClick={() => {
            setView('front')
            holoRef.current?.setView('front')
            holoRef.current?.resetYaw()
          }}
        >
          FACE FRONT
        </button>
      </div>
    </>
  )
}
