// VOICE.md §5.4 — the read-only transcript browser, moved off the side column.
// Clicking a session expands it in place; nothing here writes anything.
import { useEffect, useState } from 'react'
import { apiSession, apiSessions } from '../../api'
import { useStore } from '../../state'
import type { SessionInfo, SessionRow } from '../../types'
import { Head, fmtWhen } from './bits'

export default function Sessions() {
  const live = useStore((s) => s.voice?.on === true)
  const [list, setList] = useState<SessionInfo[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const [rows, setRows] = useState<SessionRow[]>([])

  // Refresh on mount and whenever a session ends — that is when a new file
  // appears on disk.
  useEffect(() => {
    apiSessions()
      .then(setList)
      .catch(() => {})
  }, [live])

  const pick = (file: string) => {
    if (open === file) {
      setOpen(null)
      return
    }
    setOpen(file)
    setRows([])
    apiSession(file)
      .then((r) => setRows(r.rows))
      .catch(() => setOpen(null))
  }

  return (
    <section className="ad-section">
      <Head title="SESSIONS" tag="READ ONLY" />
      <div className="ad-scroll">
        <div className="pp-sessions">
          {list.length === 0 && <div className="v-empty">EMPTY</div>}
          {list.map((s) => (
            <div key={s.file}>
              <button
                type="button"
                className={`pp-srow${open === s.file ? ' on' : ''}`}
                onClick={() => pick(s.file)}
              >
                <span className="pp-swhen">{fmtWhen(s.when)}</span>
                <span className="pp-slines">{s.lines} lines</span>
                <span className="pp-swho">{s.who.join(', ')}</span>
              </button>
              {open === s.file && (
                <div className="pp-stranscript">
                  {rows.map((r, i) => (
                    <div key={i} className="v-row">
                      <span className="v-ts">{r.t}</span>
                      <span className="v-who">{r.who.toUpperCase()}</span>
                      <span className="v-text">{r.text}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
