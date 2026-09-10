// VOICE.md §5.4 — the seven numbers that decide who is speaking. This is where
// somebody goes when Poppy keeps calling a friend a stranger, so every row
// carries its default, its range, and what raising it does.
import { useEffect, useState } from 'react'
import { apiAdminConfig, apiAdminReset, apiAdminSave } from '../../api'
import type { AdminConfig, AdminRecognition } from '../../types'
import { Head, SaveBar } from './bits'

type Key = keyof AdminRecognition

interface Row {
  key: Key
  label: string
  min: number
  max: number
  says: string
}

// The ranges are agent_config.RECOGNITION_RANGE verbatim — identity.py holds
// the same bounds, and a value one of them refuses is a value the other would
// refuse at startup. Change them there, then here.
const ROWS: Row[] = [
  {
    key: 'confident',
    label: 'CONFIDENT',
    min: 0.05,
    max: 0.95,
    says: 'Raise it and he needs a closer match before he uses your name.',
  },
  {
    key: 'tentative',
    label: 'TENTATIVE',
    min: 0.05,
    max: 0.95,
    says: 'Raise it and a weak match stops counting even as a guess.',
  },
  {
    key: 'margin',
    label: 'MARGIN',
    min: 0,
    max: 0.5,
    says: 'Raise it and the runner-up must be further behind before he picks anyone.',
  },
  {
    key: 'min_seconds',
    label: 'MIN SECONDS',
    min: 0.2,
    max: 10,
    says: 'Raise it and short replies stop being matched to anybody.',
  },
  {
    key: 'adapt_score',
    label: 'ADAPT SCORE',
    min: 0.05,
    max: 0.99,
    says: 'Raise it and he only learns from clips he was already sure about.',
  },
  {
    key: 'adapt_margin',
    label: 'ADAPT MARGIN',
    min: 0,
    max: 0.5,
    says: 'Raise it and he only learns when no other voice came close.',
  },
  {
    key: 'adapt_seconds',
    label: 'ADAPT SECONDS',
    min: 0.5,
    max: 30,
    says: 'Raise it and only longer clips are added to a voiceprint.',
  },
]

type Raw = Record<string, string>

function seedOf(r: AdminRecognition): Raw {
  const out: Raw = {}
  for (const row of ROWS) {
    const v = r[row.key]
    if (typeof v === 'number') out[row.key] = String(v)
  }
  return out
}

export default function Recognition({
  cfg,
  onCfg,
  onDirty,
}: {
  cfg: AdminConfig
  onCfg: (c: AdminConfig) => void
  onDirty: (d: boolean) => void
}) {
  const [raw, setRaw] = useState<Raw>(() => seedOf(cfg.recognition))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // A row the bridge did not send is a row this deck has no business inventing.
  const rows = ROWS.filter((r) => r.key in raw)

  const bad = (r: Row): boolean => {
    const s = raw[r.key]
    if (typeof s !== 'string' || s.trim() === '') return true
    const n = Number(s)
    return !Number.isFinite(n) || n < r.min || n > r.max
  }

  // The bridge refuses a confident gate that sits below the tentative one —
  // it is the higher of the two by definition. Say so before the round trip.
  const inverted =
    !bad(ROWS[0]) && !bad(ROWS[1]) && Number(raw.confident) < Number(raw.tentative)

  const blocked = rows.some(bad) || inverted

  // DIRTY means "there are edits to lose", and nothing else. A stored value can
  // arrive out of range on its own — the file is hand-editable — and counting
  // that as an edit locks the page behind an UNSAVED EDITS warning for work
  // nobody did: SAVE is rightly dead, REVERT re-seeds the same bad number, and
  // DISCARD is the only way out of a section the operator never typed in.
  // Measured against the seed, so "0.360" for 0.36 is not an edit either.
  const saved = seedOf(cfg.recognition)
  const dirty = rows.some((r) => {
    const now = raw[r.key]
    const was = saved[r.key]
    if (now === was) return false
    const a = Number(now)
    const b = Number(was)
    return !(Number.isFinite(a) && Number.isFinite(b) && a === b)
  })

  // Out of range is a fault, not an edit — so it has to be said in words, or a
  // red box with a dead SAVE key is the whole explanation.
  const offender = rows.find(bad)

  useEffect(() => onDirty(dirty), [dirty, onDirty])

  const save = () => {
    const patch: Partial<AdminRecognition> = {}
    for (const r of rows) patch[r.key] = Number(raw[r.key])
    setBusy(true)
    setErr(null)
    apiAdminSave({ recognition: patch })
      .then((next) => {
        setRaw(seedOf(next.recognition))
        onCfg(next)
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  const resetOne = (key: Key) => {
    setBusy(true)
    setErr(null)
    apiAdminReset(`recognition.${key}`)
      .then(() => apiAdminConfig())
      .then((fresh) => {
        const v = fresh.recognition[key]
        if (typeof v === 'number') setRaw((p) => ({ ...p, [key]: String(v) }))
        onCfg(fresh)
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  return (
    <section className="ad-section">
      <Head title="RECOGNITION" />
      <div className="ad-scroll">
        {rows.map((r) => {
          const def = cfg.defaults?.recognition?.[r.key]
          const isBad = bad(r)
          const flagged =
            isBad ||
            (inverted && (r.key === 'confident' || r.key === 'tentative'))
          const canReset =
            def === undefined
              ? cfg.changed.includes(`recognition.${r.key}`)
              : isBad || Number(raw[r.key]) !== def
          return (
            <div key={r.key} className="ad-crow">
              <span className="ad-clabel">{r.label}</span>
              <input
                className={`ad-num${flagged ? ' bad' : ''}`}
                value={raw[r.key]}
                inputMode="decimal"
                spellCheck={false}
                autoComplete="off"
                onChange={(e) =>
                  setRaw((p) => ({ ...p, [r.key]: e.target.value }))
                }
              />
              <span className="ad-def">
                {def === undefined ? '—' : `DEF ${def}`} · {r.min}–{r.max}
              </span>
              <span className="ad-says">{r.says}</span>
              <button
                type="button"
                className="ad-mini"
                disabled={busy || !canReset}
                onClick={() => resetOne(r.key)}
              >
                RESET
              </button>
            </div>
          )
        })}
      </div>
      <SaveBar
        dirty={dirty}
        blocked={blocked}
        busy={busy}
        err={
          err ??
          (offender !== undefined
            ? `${offender.label} must be between ${offender.min} and ` +
              `${offender.max} — RESET puts the default back`
            : inverted
              ? 'the confident gate is the higher of the two'
              : null)
        }
        onSave={save}
        onRevert={() => {
          setRaw(seedOf(cfg.recognition))
          setErr(null)
        }}
      />
    </section>
  )
}
