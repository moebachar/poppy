import { apiCmd, apiPlay } from '../api'
import { useStore } from '../state'
import { IconPlay, IconStop } from './icons'

export default function Sequences() {
  const moves = useStore((s) => s.moves)
  const power = useStore((s) => s.power)
  const playing = useStore((s) => s.playing)

  const off = power === 'off' || power === 'starting' || power === 'error'
  const canPlay = power === 'ready'

  return (
    <section className={`sequences${off ? ' off' : ''}`}>
      <div className="panel-label">SEQUENCES</div>
      <div className="seq-list">
        {moves.length === 0 && <div className="seq-empty">EMPTY</div>}
        {moves.map((m) => {
          const active = playing === m.name
          return (
            <div key={m.name} className={`seqrow${active ? ' active' : ''}`}>
              <span className="seq-name">{m.name}</span>
              <span className="seq-meta">
                <span>{m.seconds.toFixed(1)}s</span>
                <span className="seq-frames">{m.frames}</span>
              </span>
              {active || canPlay ? (
                <button
                  type="button"
                  className="seq-btn"
                  onClick={() => {
                    if (active) apiCmd('stop').catch(() => {})
                    else apiPlay(m.name).catch(() => {})
                  }}
                >
                  {active ? <IconStop size={10} /> : <IconPlay size={10} />}
                </button>
              ) : (
                <span className="seq-btn" />
              )}
              {active && (
                <span
                  className="seq-progress"
                  style={{ animationDuration: `${m.seconds}s` }}
                />
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
