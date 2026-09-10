// VOICE.md §5.2 — the gate. It is painted over whatever section is showing and
// never replaces it, so a token that expires mid-edit costs nothing typed.
import { useEffect, useRef, useState } from 'react'
import { apiAdminLogin } from '../../api'
import { useStore } from '../../state'

/** True when the caret is in something the operator is writing in. */
function writing(): boolean {
  const el = document.activeElement
  if (!(el instanceof HTMLElement)) return false
  return (
    el.isContentEditable ||
    el.tagName === 'INPUT' ||
    el.tagName === 'TEXTAREA' ||
    el.tagName === 'SELECT'
  )
}

export default function Login() {
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const box = useRef<HTMLInputElement>(null)

  // This gate mounts for two different reasons. Opening ADMIN focuses nothing
  // (the deck goes `inert`, which drops the focus it had), and that case must
  // land in the field without a click. The other reason is a token that died
  // under a working operator — a bridge restart drops every in-memory token,
  // and the next gated call 401s mid-sentence. autoFocus cannot tell the two
  // apart and would pull the caret out of INSTRUCTIONS into a password box.
  useEffect(() => {
    if (!writing()) box.current?.focus()
  }, [])

  const submit = () => {
    if (pw === '' || busy) return
    setBusy(true)
    setErr(null)
    apiAdminLogin(pw)
      .then((r) => {
        setPw('')
        useStore.getState().setAdminToken(r.token)
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  return (
    <div className="ad-gate">
      <div className="ad-gatebox">
        <span className="ad-title">ADMIN</span>
        <input
          ref={box}
          className="name-input"
          type="password"
          value={pw}
          autoComplete="off"
          disabled={busy}
          onChange={(e) => setPw(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
          }}
        />
        <button
          type="button"
          className="key wide"
          disabled={pw === '' || busy}
          onClick={submit}
        >
          {busy ? 'CHECKING…' : 'ENTER'}
        </button>
        {err !== null && <span className="ad-bad">{err}</span>}
        <span className="ad-hint">
          Local dashboard — this password is a latch, not a lock.
        </span>
      </div>
    </div>
  )
}
