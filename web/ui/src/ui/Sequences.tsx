import { useState } from 'react'
import { apiCmd, apiDeleteMove, apiPlay } from '../api'
import { useStore } from '../state'
import { IconPlay, IconStop } from './icons'

export default function Sequences() {
  const moves = useStore((s) => s.moves)
  const power = useStore((s) => s.power)
  const playing = useStore((s) => s.playing)
  const setEditingMove = useStore((s) => s.setEditingMove)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [confirmText, setConfirmText] = useState('')

  const off = power === 'off' || power === 'starting' || power === 'error'
  const canPlay = power === 'ready'

  const closeConfirm = () => {
    setConfirming(null)
    setConfirmText('')
  }

  const tryDelete = (name: string) => {
    if (confirmText.trim().toLowerCase() !== 'delete') return
    apiDeleteMove(name).catch(() => {})
    closeConfirm()
  }

  return (
    <section className={`sequences${off ? ' off' : ''}`}>
      <div className="panel-label">SEQUENCES</div>
      <div className="seq-list">
        {moves.length === 0 && <div className="seq-empty">EMPTY</div>}
        {moves.map((m) => {
          const active = playing === m.name
          return (
            <div
              key={m.name}
              className={`seqrow${active ? ' active' : ''}`}
              title={m.description || undefined}
            >
              <span className="seq-name">{m.name}</span>
              {confirming === m.name ? (
                <span className="seq-confirm">
                  <input
                    autoFocus
                    value={confirmText}
                    placeholder="type delete"
                    onChange={(e) => setConfirmText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') tryDelete(m.name)
                      if (e.key === 'Escape') closeConfirm()
                    }}
                    onBlur={closeConfirm}
                  />
                </span>
              ) : (
                <span className="seq-meta">
                  <span>{m.seconds.toFixed(1)}s</span>
                  <span className="seq-frames">{m.frames}</span>
                </span>
              )}
              {confirming !== m.name && !active && (
                <>
                  <button
                    type="button"
                    className="seq-del"
                    title="edit description / when"
                    onClick={() => setEditingMove(m.name)}
                  >
                    ⋯
                  </button>
                  <button
                    type="button"
                    className="seq-del"
                    title="remove this move"
                    onClick={() => {
                      setConfirming(m.name)
                      setConfirmText('')
                    }}
                  >
                    ×
                  </button>
                </>
              )}
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
