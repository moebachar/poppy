// VOICE.md §5.4 — the admin page. A full window over the deck, which keeps
// running underneath: this page never unmounts the hologram, it is painted on
// top of it, so CLOSE comes back to the same stage with the same context.
import { useEffect, useState } from 'react'
import { apiAdminConfig, refreshPeople } from '../api'
import { useStore } from '../state'
import type { AdminConfig } from '../types'
import Access from './admin/Access'
import Login from './admin/Login'
import Personality from './admin/Personality'
import Preview from './admin/Preview'
import Recognition from './admin/Recognition'
import Sessions from './admin/Sessions'
import Speech from './admin/Speech'
import Tools from './admin/Tools'
import { Head } from './admin/bits'
import PeoplePanel from './PeoplePanel'

type Section =
  | 'personality'
  | 'tools'
  | 'speech'
  | 'recognition'
  | 'people'
  | 'sessions'
  | 'preview'
  | 'access'

const SECTIONS: { id: Section; label: string }[] = [
  { id: 'personality', label: 'PERSONALITY' },
  { id: 'tools', label: 'TOOLS' },
  { id: 'speech', label: 'SPEECH' },
  { id: 'recognition', label: 'RECOGNITION' },
  { id: 'people', label: 'PEOPLE' },
  { id: 'sessions', label: 'SESSIONS' },
  { id: 'preview', label: 'PREVIEW' },
  { id: 'access', label: 'ACCESS' },
]

export default function AdminPage() {
  const token = useStore((s) => s.adminToken)
  const voiceOn = useStore((s) => s.voice?.on === true)
  const [section, setSection] = useState<Section>('personality')
  const [cfg, setCfg] = useState<AdminConfig | null>(null)
  const [cfgErr, setCfgErr] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [pending, setPending] = useState<{ run: () => void } | null>(null)

  // The deck is still mounted under this page and still listening on window:
  // SPACE is STOP down there, and V is push-to-talk. This page is made of text
  // fields, so both are swallowed in the capture phase — before the deck's own
  // listeners see them. stopPropagation only, never preventDefault: a space
  // must still type a space and still press the focused key.
  useEffect(() => {
    const swallow = (e: KeyboardEvent) => {
      if (e.code === 'Space' || e.code === 'KeyV') e.stopPropagation()
    }
    window.addEventListener('keydown', swallow, true)
    window.addEventListener('keyup', swallow, true)
    return () => {
      window.removeEventListener('keydown', swallow, true)
      window.removeEventListener('keyup', swallow, true)
    }
  }, [])

  // CLOSE warns before it leaves. F5, Ctrl+W and the tab's own close button
  // must not be the quiet way out that loses 19 000 typed characters instead.
  // The browser writes the wording; the only thing a page decides is whether
  // it is asked at all, so the handler is only bound while there is something
  // to lose.
  useEffect(() => {
    if (!dirty) return
    const ask = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = '' // engines that still read the old flag
    }
    window.addEventListener('beforeunload', ask)
    return () => {
      window.removeEventListener('beforeunload', ask)
    }
  }, [dirty])

  // The roster and the config are both behind the gate: ask once the token
  // exists, and again if it is replaced after an expiry.
  useEffect(() => {
    if (token === null) return
    let dead = false
    apiAdminConfig()
      .then((c) => {
        if (!dead) {
          setCfg(c)
          setCfgErr(null)
        }
      })
      .catch((e: Error) => {
        if (!dead) setCfgErr(e.message)
      })
    refreshPeople()
    return () => {
      dead = true
    }
  }, [token])

  // Nothing on this page auto-saves, so nothing leaves it silently either.
  // An inline hairline, never confirm() — that dialog blocks the whole tab.
  const guard = (run: () => void) => {
    if (dirty) setPending({ run })
    else run()
  }

  const go = (to: Section) => {
    if (to === section) return
    guard(() => {
      setSection(to)
      setDirty(false)
    })
  }

  const close = () => guard(() => useStore.getState().setPage('deck'))

  // A key out, because a pointer is not always the way: CLOSE is one 26px key
  // in a corner, and this page has a 1100px floor that a narrow window pushes
  // it against. ESCAPE goes through the same guard, so it can no more discard
  // an edit than CLOSE can. Re-bound whenever `dirty` or `pending` change,
  // which is what keeps the captured `close` current.
  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return
      // While something is being typed into, ESCAPE belongs to that field and
      // to nobody else — half the fields here cancel a rename or a confirm
      // with it, and some of them commit on blur, so this must not even take
      // the focus away. CLOSE is always on screen for that case.
      const el = document.activeElement
      if (
        el instanceof HTMLElement &&
        (el.isContentEditable ||
          el.tagName === 'INPUT' ||
          el.tagName === 'TEXTAREA' ||
          el.tagName === 'SELECT')
      ) {
        return
      }
      // The warning is a question, and ESCAPE answers the safe half of it.
      if (pending !== null) setPending(null)
      else close()
    }
    window.addEventListener('keydown', onEsc)
    return () => {
      window.removeEventListener('keydown', onEsc)
    }
  }, [dirty, pending])

  const openMove = (name: string) =>
    guard(() => {
      const st = useStore.getState()
      st.setSideTab('seq')
      st.setEditingMove(name)
      st.setPage('deck')
    })

  // Waiting on the gate, on the round trip, or on a bridge that refused.
  const waiting = () => (
    <section className="ad-section">
      <div className="v-empty">{cfgErr === null ? 'LOADING' : cfgErr}</div>
    </section>
  )

  const body = () => {
    switch (section) {
      case 'personality':
        return cfg === null ? (
          waiting()
        ) : (
          <Personality cfg={cfg} onCfg={setCfg} onDirty={setDirty} />
        )
      case 'tools':
        return cfg === null ? (
          waiting()
        ) : (
          <Tools
            cfg={cfg}
            onCfg={setCfg}
            onDirty={setDirty}
            onOpenMove={openMove}
          />
        )
      case 'speech':
        return <Speech onDirty={setDirty} />
      case 'recognition':
        return cfg === null ? (
          waiting()
        ) : (
          <Recognition cfg={cfg} onCfg={setCfg} onDirty={setDirty} />
        )
      case 'people':
        return (
          <section className="ad-section">
            <Head title="PEOPLE" />
            <PeoplePanel />
          </section>
        )
      case 'sessions':
        return <Sessions />
      case 'preview':
        return <Preview />
      case 'access':
        return <Access cfg={cfg} onCfg={setCfg} />
    }
  }

  // Two boxes, not one: `.admin` is pinned to the viewport and `.ad-frame`
  // carries the 1100px floor. A fixed box's containing block is the viewport
  // itself, so whatever a floor pushes past the edge can never be scrolled
  // back — the floor has to sit inside the shell instead (VOICE.md §5.4).
  return (
    <div className="admin">
      <div className={`ad-frame${pending !== null ? ' warned' : ''}`}>
        <header className="ad-top">
          <span className="wordmark">POPPY</span>
          <span className="ad-word">ADMIN</span>
          {cfg?.error != null && (
            <span className="ad-fault" title={cfg.error}>
              CONFIG IGNORED
              <span className="ad-sub">
                {cfg.error} — editing here overwrites it
              </span>
            </span>
          )}
          {voiceOn && (
            <span className="ad-live">TAKES EFFECT AT THE NEXT SESSION</span>
          )}
          {/* sticky: it stays against the window's edge even when the frame is
              wider than the window, so the way back is never off-screen */}
          <button type="button" className="ad-close" onClick={close}>
            CLOSE
          </button>
        </header>

        {pending !== null && (
          <div className="ad-warn">
            <span className="ad-warnword">UNSAVED EDITS</span>
            <button
              type="button"
              className="ad-mini warn"
              onClick={() => {
                const p = pending
                setPending(null)
                setDirty(false)
                p.run()
              }}
            >
              DISCARD
            </button>
            <button
              type="button"
              className="ad-mini"
              onClick={() => setPending(null)}
            >
              STAY
            </button>
          </div>
        )}

        <nav className="ad-nav">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`ad-navkey${section === s.id ? ' on' : ''}`}
              onClick={() => go(s.id)}
            >
              {s.label}
              {dirty && section === s.id && <span className="ad-dot" />}
            </button>
          ))}
        </nav>

        <div className="ad-body">
          {body()}
          {token === null && <Login />}
        </div>
      </div>
    </div>
  )
}
