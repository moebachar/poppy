import { useEffect, useState } from 'react'
import { apiCmd, apiPower, apiVoiceSet } from '../api'
import { useStore } from '../state'
import { IconCam, IconLevel, IconPower, IconStop } from './icons'

export default function CommandDeck() {
  const power = useStore((s) => s.power)
  const voice = useStore((s) => s.voice)
  const setSideTab = useStore((s) => s.setSideTab)
  // The broadcast that flips `phase` lands after the POST answers, so a second
  // click in that window would 409. Same guard TeachPanel uses.
  const [busy, setBusy] = useState(false)

  const powerOn = power !== 'off' && power !== 'error'
  const starting = power === 'starting'

  // The agent does not need the body: this key works with the robot off.
  const voiceOn = voice?.on === true
  const voiceBusy = voice?.phase === 'starting'

  // A guided enrolment holds the same laptop mic, so voicelink.start() refuses
  // while one is open. Ending a live session is never blocked.
  const enroll = voice?.enroll ?? null
  const enrolling = !voiceOn && enroll !== null && enroll.status !== 'done'

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

  const toggleVoice = () => {
    if (busy) return
    setBusy(true)
    if (!voiceOn) setSideTab('voice')
    apiVoiceSet({ on: !voiceOn })
      .catch(() => {})
      .finally(() => setBusy(false))
  }

  return (
    <section className="deck">
      <button
        type="button"
        className={`key power${powerOn ? ' active' : ''}${
          starting ? ' transient' : ''
        }`}
        disabled={starting}
        onClick={() => apiPower(!powerOn).catch(() => {})}
      >
        <span className="keyicon">
          <IconPower size={11} />
        </span>
        <span className="keylabel">
          {starting ? 'SPINNING UP…' : 'POWER'}
        </span>
      </button>
      <button
        type="button"
        className={`key voicekey${voiceOn ? ' active' : ''}${
          voiceBusy ? ' transient' : ''
        }`}
        disabled={voiceBusy || busy || enrolling}
        onClick={toggleVoice}
      >
        <span className="keyicon">
          <IconLevel size={11} />
        </span>
        <span className="keylabel">
          {voiceBusy ? 'LINKING…' : enrolling ? 'ENROLLING' : 'VOICE'}
        </span>
      </button>
      <button
        type="button"
        className={`key${power === 'ready' ? ' active' : ''}`}
        disabled={!canStand}
        onClick={() => apiCmd('hold').catch(() => {})}
      >
        <span className="keylabel">STAND</span>
      </button>
      <button
        type="button"
        className={`key${power === 'released' ? ' active' : ''}`}
        disabled={!canRelease}
        onClick={() => apiCmd('release').catch(() => {})}
      >
        <span className="keylabel">RELEASE</span>
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
        <span className="keylabel">LOOK</span>
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
        <span className="keylabel">STOP</span>
      </button>
    </section>
  )
}
