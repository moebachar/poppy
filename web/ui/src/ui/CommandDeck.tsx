import { useEffect } from 'react'
import { apiCmd, apiPower } from '../api'
import { useStore } from '../state'
import { IconCam, IconPower, IconStop } from './icons'

export default function CommandDeck() {
  const power = useStore((s) => s.power)

  const powerOn = power !== 'off' && power !== 'error'
  const starting = power === 'starting'

  const canStand =
    power === 'ready' || power === 'released' || power === 'cooling'
  const canRelease = power === 'ready' || power === 'recording'
  const canLook = power === 'ready'
  const canStop = power === 'playing'

  // space = STOP
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      e.preventDefault()
      if (useStore.getState().power === 'playing') apiCmd('stop').catch(() => {})
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <section className="deck">
      <button
        type="button"
        className={`key power${powerOn ? ' active' : ''}`}
        disabled={starting}
        onClick={() => apiPower(!powerOn).catch(() => {})}
      >
        <span className="keyicon">
          <IconPower size={11} />
        </span>
        {starting ? 'SPINNING UP…' : 'POWER'}
      </button>
      <button
        type="button"
        className={`key${power === 'ready' ? ' active' : ''}`}
        disabled={!canStand}
        onClick={() => apiCmd('hold').catch(() => {})}
      >
        STAND
      </button>
      <button
        type="button"
        className={`key${power === 'released' ? ' active' : ''}`}
        disabled={!canRelease}
        onClick={() => apiCmd('release').catch(() => {})}
      >
        RELEASE
      </button>
      <button
        type="button"
        className="key"
        disabled={!canLook}
        onClick={() => apiCmd('look').catch(() => {})}
      >
        <span className="keyicon">
          <IconCam size={11} />
        </span>
        LOOK
      </button>
      <button
        type="button"
        className="key stop"
        disabled={!canStop}
        onClick={() => apiCmd('stop').catch(() => {})}
      >
        <span className="keyicon">
          <IconStop size={10} />
        </span>
        STOP
      </button>
    </section>
  )
}
