// KIOSK.md §3.5 — the deck's HoloStage with the operator's parts taken out:
// no pick, no hover, no view buttons, no teach. Store in, hologram out.
import { useEffect, useRef } from 'react'
import { createHolo } from '../holo'
import type { HoloMode, HoloMotor, VoicePhase } from '../holo'
import { readLevels, subscribeLevels } from '../audioBus'
import { useKiosk } from './store'
import type { KioskState } from './store'
import { EXPECTED_IDS } from '../types'
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
  // No session, but a guided enrolment on the deck holds the mic and streams
  // its envelope — the twin reacting to the person is worth showing here too.
  const e = v.enroll
  if (e && e.status !== 'done') {
    return e.status === 'recording' ? 'hearing' : 'listening'
  }
  return 'off'
}

// The kiosk never scans the bus. Before the deck has, no motor is present —
// which is "not surveyed yet", not "all dead": show him whole and calm.
function motorsOf(s: KioskState): HoloMotor[] {
  if (!s.motors.some((m) => m.present)) {
    return EXPECTED_IDS.map((id) => ({ id, ok: true, present: true }))
  }
  return s.motors.map((m) => ({ id: m.id, ok: m.ok, present: m.present }))
}

export default function Stage() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    // whole body always: a visitor sees the robot, the marker says what is dead
    const holo = createHolo(canvas, { theme: 'light', keepDeadParts: true })

    let lastMode: HoloMode | null = null
    let lastPose: Record<string, number> | null = null
    let lastMotorsKey = ''
    let lastPower: Power | null = null
    let zeroTimer: number | undefined

    // ---- the voice aura (VOICE.md §3, §4.1) ------------------------------
    // Levels arrive 30 times a second and must never reach React, so they come
    // off the module-scope bus and go straight into the module.
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

    const push = (s: KioskState) => {
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
            const pos = useKiosk.getState().latestPos
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
    }

    push(useKiosk.getState())
    const unsub = useKiosk.subscribe(push)

    const onDbl = () => holo.resetYaw()
    canvas.addEventListener('dblclick', onDbl)

    const ro = new ResizeObserver(() => holo.resize())
    if (canvas.parentElement) ro.observe(canvas.parentElement)

    return () => {
      unsub()
      unsubLevels()
      ro.disconnect()
      canvas.removeEventListener('dblclick', onDbl)
      window.clearTimeout(zeroTimer)
      window.clearTimeout(auraTimer)
      holo.dispose()
    }
  }, [])

  return <canvas ref={canvasRef} className="holo-canvas" />
}
