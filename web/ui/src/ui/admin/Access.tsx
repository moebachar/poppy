// VOICE.md §5.4 — the gate itself, and the one place that can throw every
// override away. The sentence below is the whole truth about this password.
import { useState } from 'react'
import { apiAdminConfig, apiAdminPassword, apiAdminReset } from '../../api'
import { useStore } from '../../state'
import type { AdminConfig } from '../../types'
import { Head } from './bits'

const MIN = 4
const MAX = 64

export default function Access({
  cfg,
  onCfg,
}: {
  cfg: AdminConfig | null
  onCfg: (c: AdminConfig) => void
}) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [confirm, setConfirm] = useState<string | null>(null)

  const ok = current !== '' && next.length >= MIN && next.length <= MAX

  const change = () => {
    if (!ok || busy) return
    setBusy(true)
    setErr(null)
    setDone(false)
    apiAdminPassword(current, next)
      .then(() => {
        setCurrent('')
        setNext('')
        setDone(true)
      })
      .catch((e: Error) => {
        setErr(e.message)
        // This route answers a wrong CURRENT with 401 and keeps the token
        // (api.ts) — a typo must not sign the page out. The gate refuses an
        // expired token with the same status, though, so ask it one ordinary
        // gated question: only if THAT comes back 401 is the session really
        // over, and then the login box takes over the way it should.
        apiAdminConfig()
          .then(onCfg)
          .catch(() => {})
      })
      .finally(() => setBusy(false))
  }

  const resetAll = () => {
    if (confirm === null || confirm.trim().toLowerCase() !== 'reset') return
    setBusy(true)
    setErr(null)
    apiAdminReset('*')
      .then(() => apiAdminConfig())
      .then(onCfg)
      .catch((e: Error) => setErr(e.message))
      .finally(() => {
        setBusy(false)
        setConfirm(null)
      })
  }

  return (
    <section className="ad-section">
      <Head title="ACCESS" />
      <div className="ad-scroll">
        <div className="ad-soft">
          This dashboard answers on this machine only, and the password is a
          latch, not a lock — it keeps the roster and the personality out of
          reach of a passing hand, nothing more.
        </div>

        <div className="ad-form">
          <span className="ad-clabel">CURRENT</span>
          <input
            className="name-input"
            type="password"
            value={current}
            autoComplete="off"
            onChange={(e) => setCurrent(e.target.value)}
          />
        </div>
        <div className="ad-form">
          <span className="ad-clabel">NEW</span>
          <input
            className="name-input"
            type="password"
            value={next}
            maxLength={MAX}
            autoComplete="off"
            onChange={(e) => setNext(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') change()
            }}
          />
          <span className="ad-def">
            {MIN}–{MAX}
          </span>
        </div>
        <div className="ad-form">
          <span className="ad-clabel" />
          <button
            type="button"
            className="key"
            disabled={!ok || busy}
            onClick={change}
          >
            CHANGE
          </button>
          <button
            type="button"
            className="key"
            onClick={() => useStore.getState().setAdminToken(null)}
          >
            SIGN OUT
          </button>
          {done && <span className="ad-good">SAVED</span>}
          {err !== null && <span className="ad-bad">{err}</span>}
        </div>

        <div className="ad-form">
          <span className="ad-clabel">DEFAULTS</span>
          {confirm === null ? (
            <button
              type="button"
              className="ad-mini warn"
              disabled={cfg === null || cfg.changed.length === 0}
              onClick={() => setConfirm('')}
            >
              RESET ALL
            </button>
          ) : (
            <span className="seq-confirm">
              <input
                autoFocus
                value={confirm}
                placeholder="type reset"
                onChange={(e) => setConfirm(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') resetAll()
                  if (e.key === 'Escape') setConfirm(null)
                }}
                onBlur={() => setConfirm(null)}
              />
            </span>
          )}
          {cfg !== null && (
            <span className="ad-def">{cfg.changed.length} CHANGED</span>
          )}
        </div>
      </div>
    </section>
  )
}
