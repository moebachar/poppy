// VOICE.md §5.4 — who Poppy is. The instructions box is the centrepiece: full
// height, monospace, and a tab in it is a tab.
import { useEffect, useRef, useState } from 'react'
import { apiAdminConfig, apiAdminReset, apiAdminSave } from '../../api'
import type { AdminConfig, AdminPrompt } from '../../types'
import { ADMIN_LIMITS } from '../../types'
import { Head, SaveBar, clone } from './bits'

type FieldName = keyof AdminPrompt

const FIELDS: { name: FieldName; label: string; limit: number; rows: number }[] = [
  { name: 'instructions', label: 'INSTRUCTIONS', limit: ADMIN_LIMITS.instructions, rows: 0 },
  { name: 'greeting', label: 'GREETING', limit: ADMIN_LIMITS.greeting, rows: 4 },
  { name: 'nudge_prompt', label: 'NUDGE', limit: ADMIN_LIMITS.nudge_prompt, rows: 4 },
]

/** One field, holding its own text. A 20 000-character box must not re-render
 *  the page on every keystroke — the parent only hears about the two things
 *  that change rarely: dirty, and past the limit. */
function PromptField({
  label,
  limit,
  seed,
  rows,
  def,
  changed,
  onEdit,
  onReset,
}: {
  label: string
  limit: number
  seed: string
  rows: number
  def: string | undefined
  changed: boolean
  onEdit: (text: string) => void
  onReset: () => void
}) {
  const [text, setText] = useState(seed)
  const over = text.length > limit
  // Judged against the live text, not the saved one: a field typed back to the
  // default has nothing left to reset.
  const canReset = def === undefined ? changed : text !== def

  const type = (t: string) => {
    setText(t)
    onEdit(t)
  }

  return (
    <div className={`ad-field${rows === 0 ? ' grow' : ''}`}>
      <div className="ad-fhead">
        <span className="ad-title">{label}</span>
        <span
          className={`ad-count${over ? ' over' : text.length > limit * 0.9 ? ' warn' : ''}`}
        >
          {text.length} / {limit}
        </span>
        <button
          type="button"
          className="ad-mini"
          disabled={!canReset}
          onClick={onReset}
        >
          RESET
        </button>
      </div>
      <textarea
        className={`ad-ta${over ? ' over' : ''}`}
        value={text}
        rows={rows === 0 ? undefined : rows}
        spellCheck={false}
        onChange={(e) => type(e.target.value)}
        onKeyDown={(e) => {
          // A tab belongs to the text, not to the focus order. Shift+Tab is
          // left alone so the keyboard still has a way out of the box.
          if (e.key !== 'Tab' || e.shiftKey) return
          if (e.ctrlKey || e.altKey || e.metaKey) return
          e.preventDefault()
          const el = e.currentTarget
          el.setRangeText('\t', el.selectionStart, el.selectionEnd, 'end')
          type(el.value)
        }}
      />
    </div>
  )
}

export default function Personality({
  cfg,
  onCfg,
  onDirty,
}: {
  cfg: AdminConfig
  onCfg: (c: AdminConfig) => void
  onDirty: (d: boolean) => void
}) {
  const draft = useRef<AdminPrompt>(clone(cfg.prompt))
  const [seed, setSeed] = useState(0)
  const [dirty, setDirty] = useState(false)
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => onDirty(dirty), [dirty, onDirty])

  const recheck = (base: AdminPrompt) => {
    const d = draft.current
    const nd = FIELDS.some((f) => d[f.name] !== base[f.name])
    const no = FIELDS.some((f) => d[f.name].length > f.limit)
    setDirty((v) => (v === nd ? v : nd))
    setOver((v) => (v === no ? v : no))
  }

  const reseed = (c: AdminConfig) => {
    draft.current = clone(c.prompt)
    setSeed((s) => s + 1)
    setDirty(false)
    setOver(false)
    setErr(null)
    onCfg(c)
  }

  const save = () => {
    setBusy(true)
    setErr(null)
    apiAdminSave({ prompt: clone(draft.current) })
      .then(reseed)
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  const resetField = (name: FieldName) => {
    setBusy(true)
    setErr(null)
    // The reset drops an override on the server; re-reading is what tells us
    // what the default actually was, and keeps `changed` honest.
    apiAdminReset(`prompt.${name}`)
      .then(() => apiAdminConfig())
      .then((fresh) => {
        // Only this field goes back — edits in the other two are not this
        // key's business.
        draft.current[name] = fresh.prompt[name]
        setSeed((s) => s + 1)
        onCfg(fresh)
        recheck(fresh.prompt)
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  return (
    <section className="ad-section">
      <Head title="PERSONALITY" />
      <div className="ad-fields">
        {FIELDS.map((f) => (
          <PromptField
            key={`${f.name}-${seed}`}
            label={f.label}
            limit={f.limit}
            rows={f.rows}
            seed={draft.current[f.name]}
            def={cfg.defaults?.prompt?.[f.name]}
            changed={cfg.changed.includes(`prompt.${f.name}`)}
            onEdit={(t) => {
              draft.current[f.name] = t
              recheck(cfg.prompt)
            }}
            onReset={() => resetField(f.name)}
          />
        ))}
      </div>
      <SaveBar
        dirty={dirty}
        blocked={over}
        busy={busy}
        err={err}
        onSave={save}
        onRevert={() => reseed(cfg)}
      />
    </section>
  )
}
