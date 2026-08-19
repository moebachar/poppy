import { useEffect, useState } from 'react'
import { useStore } from '../state'

const SESSION_START = Date.now()

function fmtUptime(ms: number): string {
  const s = Math.floor(ms / 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s / 60) % 60))}:${p(s % 60)}`
}

export default function TopBar() {
  const power = useStore((s) => s.power)
  const port = useStore((s) => s.port)
  const wsConnected = useStore((s) => s.wsConnected)
  const health = useStore((s) => s.health)
  const motors = useStore((s) => s.motors)
  const awaitingAwaken = useStore((s) => s.awaitingAwaken)

  const [uptime, setUptime] = useState('00:00:00')
  useEffect(() => {
    const t = setInterval(() => setUptime(fmtUptime(Date.now() - SESSION_START)), 1000)
    return () => clearInterval(t)
  }, [])

  // hottest motor: live health first, FullState scan values as fallback
  let tmax: number | null = health.maxtemp
  if (tmax === null) {
    for (const m of motors) {
      if (m.temp !== null && (tmax === null || m.temp > tmax)) tmax = m.temp
    }
  }
  const tmaxClass = tmax === null ? '' : tmax >= 50 ? ' fault' : tmax >= 45 ? ' warn' : ''

  // state word — hold STARTING until the hologram finishes awakening
  const word =
    power === 'ready' && awaitingAwaken ? 'starting' : power
  const wordText = word === 'starting' ? 'STARTING' : word.toUpperCase()

  return (
    <header className="topbar">
      <div className="topbar-id">
        <span className="wordmark">POPPY/DECK</span>
        <span className="topbar-sub">TORSO·2013</span>
        <span className={`stateword s-${word}`}>{wordText}</span>
      </div>
      <div className="topbar-readouts">
        <div className="seg">
          <span className="seg-label">LINK</span>
          <span className={wsConnected ? 'linkdot up' : 'linkdot'} />
          <span className="seg-value">{port ?? '—'}</span>
        </div>
        <div className="seg">
          <span className="seg-label">T.MAX</span>
          <span className={`seg-value tmax${tmaxClass}`}>
            {tmax === null ? '—' : `${tmax}°C`}
          </span>
        </div>
        <div className="seg">
          <span className="seg-value">{uptime}</span>
        </div>
      </div>
      {!wsConnected && <div className="link-lost-rule" />}
    </header>
  )
}
