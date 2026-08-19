// Thin bridge between the zustand store and the hologram module.
// Creates the module once, pushes state diffs in, routes pick/hover back.
import { useEffect, useRef, useState } from 'react'
import { createHolo } from '../holo'
import type { HoloMode, HoloMotor } from '../holo'
import { useStore } from '../state'
import type { DeckState } from '../state'
import type { Power } from '../types'

function modeOf(p: Power): HoloMode {
  if (p === 'starting') return 'awakening'
  if (p === 'off' || p === 'error') return 'dormant'
  return 'live' // ready | playing | recording | released | cooling
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
  const [topView, setTopView] = useState(false)

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

    const push = (s: DeckState) => {
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
      ro.disconnect()
      if (awakenTimer !== undefined) window.clearTimeout(awakenTimer)
      window.clearTimeout(zeroTimer)
      holoRef.current = null
      holo.dispose()
    }
  }, [])

  return (
    <>
      <canvas ref={canvasRef} className="holo-canvas" />
      <div className="stage-tools">
        <button
          className={topView ? 'stage-reset active' : 'stage-reset'}
          onClick={() => {
            const next = !topView
            setTopView(next)
            holoRef.current?.setTopView(next)
          }}
        >
          TOP VIEW
        </button>
        <button
          className="stage-reset"
          onClick={() => holoRef.current?.resetYaw()}
        >
          FACE FRONT
        </button>
      </div>
    </>
  )
}
