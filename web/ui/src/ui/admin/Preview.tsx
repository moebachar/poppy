// VOICE.md §5.4 — the exact strings and tool JSON the next session will send,
// assembled by the bridge with the same code that sends them. Read-only: there
// is nothing to edit here, only something to check.
import { useEffect, useState } from 'react'
import { apiAdminPreview } from '../../api'
import type { AdminPreview } from '../../types'
import { Head } from './bits'

export default function Preview() {
  const [p, setP] = useState<AdminPreview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => {
    setBusy(true)
    setErr(null)
    apiAdminPreview()
      .then((next) => setP(next))
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  useEffect(load, [])

  return (
    <section className="ad-section">
      <Head title="PREVIEW" tag="READ ONLY">
        <div className="ad-keys">
          <button
            type="button"
            className="ad-mini"
            disabled={busy}
            onClick={load}
          >
            REFRESH
          </button>
        </div>
      </Head>
      <div className="ad-scroll">
        {err !== null && (
          <div className="ad-pblock">
            <span className="ad-bad">{err}</span>
          </div>
        )}
        {p !== null && (
          <>
            <div className="ad-pblock">
              <span className="ad-plabel">INSTRUCTIONS</span>
              <pre className="ad-pre">{p.instructions}</pre>
            </div>
            <div className="ad-pblock">
              <span className="ad-plabel">ROSTER</span>
              <pre className="ad-pre">{p.roster}</pre>
            </div>
            <div className="ad-pblock">
              <span className="ad-plabel">TOOLS</span>
              <pre className="ad-pre">{JSON.stringify(p.tools, null, 2)}</pre>
            </div>
            <div className="ad-pblock">
              <span className="ad-plabel">SESSION</span>
              <pre className="ad-pre">{JSON.stringify(p.session, null, 2)}</pre>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
