// VOICE.md §5.4 — what Poppy can do. One row per tool: on/off, and the exact
// description the model is given. A move's own text stays in its file and is
// still edited from SEQUENCES; here a move is only turned on or off.
import { useEffect, useState } from 'react'
import { apiAdminConfig, apiAdminReset, apiAdminSave } from '../../api'
import { useStore } from '../../state'
import type { AdminConfig, AdminTool, AdminTools } from '../../types'
import { ADMIN_LIMITS, builtinTools } from '../../types'
import { Chips, Head, SaveBar, clone, toolLabel } from './bits'

const LIMIT = ADMIN_LIMITS.description

/** What he loses when a built-in is off — two words, then one line. */
const LOSS: Record<string, [string, string] | undefined> = {
  enroll_speaker: [
    'NO NAMES',
    'He still hears a voice and still tells voices apart. He can never learn whose it is.',
  ],
  remember_person: [
    'NO MEMORY',
    'Nothing new is written down; what he already knows about people still reaches him.',
  ],
  stop_moving: [
    'NO ABORT',
    'A move he has started runs to the end — only the STOP key can cut it short.',
  ],
}

function asTool(v: AdminTool | Record<string, AdminTool> | undefined): AdminTool | undefined {
  return v !== undefined && typeof (v as { enabled?: unknown }).enabled === 'boolean'
    ? (v as AdminTool)
    : undefined
}

export default function Tools({
  cfg,
  onCfg,
  onDirty,
  onOpenMove,
}: {
  cfg: AdminConfig
  onCfg: (c: AdminConfig) => void
  onDirty: (d: boolean) => void
  onOpenMove: (name: string) => void
}) {
  const moves = useStore((s) => s.moves)
  const [draft, setDraft] = useState<AdminTools>(() => clone(cfg.tools))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const builtins = builtinTools(draft)
  const dirty = JSON.stringify(draft) !== JSON.stringify(cfg.tools)
  const over = builtins.some(([, t]) => (t.description ?? '').length > LIMIT)
  // agent_config.py refuses a description that is present but blank, and one
  // POST carries every row: emptying one box and pressing SAVE would take the
  // other rows' edits down with it in a 400. Refuse it here, where the box
  // that did it is on screen, and keep the round trip for what can be saved.
  const blank = builtins.some(
    ([, t]) => t.description !== undefined && t.description.trim() === '',
  )

  useEffect(() => onDirty(dirty), [dirty, onDirty])

  const edit = (name: string, patch: Partial<AdminTool>) => {
    setDraft((d) => {
      const cur = asTool(d[name])
      if (cur === undefined) return d
      const next: AdminTools = { ...d }
      next[name] = { ...cur, ...patch }
      return next
    })
  }

  // A move nobody listed is simply on (agent_config.MOVE_DEFAULT), so the
  // config only carries the ones that were turned off — the rows themselves
  // come from the moves on disk.
  const enabledOf = (name: string): boolean => {
    const row = draft.moves[name] as AdminTool | undefined
    return row === undefined || row.enabled !== false
  }

  const editMove = (name: string, enabled: boolean) => {
    setDraft((d) => {
      const next: AdminTools = { ...d, moves: { ...d.moves } }
      next.moves[name] = { enabled }
      return next
    })
  }

  const save = () => {
    setBusy(true)
    setErr(null)
    apiAdminSave({ tools: clone(draft) })
      .then((next) => {
        setDraft(clone(next.tools))
        setErr(null)
        onCfg(next)
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  const resetTool = (name: string) => {
    setBusy(true)
    setErr(null)
    apiAdminReset(`tools.${name}`)
      .then(() => apiAdminConfig())
      .then((fresh) => {
        // Only this row goes back; the other rows may be mid-edit.
        const back = asTool(fresh.tools[name])
        if (back !== undefined) {
          setDraft((d) => {
            const next: AdminTools = { ...d }
            next[name] = back
            return next
          })
        }
        onCfg(fresh)
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }

  const defMap = new Map(builtinTools(cfg.defaults?.tools ?? { moves: {} }))
  const resettable = (name: string, t: AdminTool): boolean => {
    const def = defMap.get(name)
    if (def === undefined) return cfg.changed.some((p) => p.startsWith(`tools.${name}`))
    return (
      def.enabled !== t.enabled ||
      (def.description ?? '') !== (t.description ?? '')
    )
  }

  const moveNames = [
    ...new Set([...moves.map((m) => m.name), ...Object.keys(draft.moves)]),
  ].sort()

  return (
    <section className="ad-section">
      <Head title="TOOLS" />
      <div className="ad-scroll">
        {builtins.map(([name, t]) => {
          const desc = t.description ?? ''
          const loss = LOSS[name]
          const tooLong = desc.length > LIMIT
          const isBlank = t.description !== undefined && desc.trim() === ''
          const mark = tooLong ? ' over' : isBlank ? ' bad' : ''
          return (
            <div key={name} className={`ad-row${t.enabled ? '' : ' off'}`}>
              <div className="ad-rowhead">
                <span className="ad-name">{toolLabel(name)}</span>
                <div className="ad-toggle">
                  <Chips
                    values={['on', 'off'] as const}
                    now={t.enabled ? 'on' : 'off'}
                    onPick={(v) => edit(name, { enabled: v === 'on' })}
                  />
                </div>
                <div className="ad-keys">
                  <span className={`ad-count${mark}`}>
                    {desc.length} / {LIMIT}
                  </span>
                  <button
                    type="button"
                    className="ad-mini"
                    disabled={busy || !resettable(name, t)}
                    onClick={() => resetTool(name)}
                  >
                    RESET
                  </button>
                </div>
              </div>
              {!t.enabled && loss !== undefined && (
                <div className="ad-loss">
                  <span className="ad-lossword">{loss[0]}</span>
                  <span className="ad-sub">{loss[1]}</span>
                </div>
              )}
              <textarea
                className={`ad-desc${mark}`}
                rows={3}
                spellCheck={false}
                value={desc}
                onChange={(e) => edit(name, { description: e.target.value })}
              />
            </div>
          )
        })}

        <div className="ad-head">
          <span className="ad-title">MOVES</span>
          <span className="ad-def">{moveNames.length}</span>
        </div>
        {moveNames.length === 0 && <div className="v-empty">EMPTY</div>}
        {moveNames.map((name) => {
          const on = enabledOf(name)
          const m = moves.find((x) => x.name === name)
          return (
            <div key={`move-${name}`} className={`ad-row${on ? '' : ' off'}`}>
              <div className="ad-rowhead">
                <span className="ad-name">{name}</span>
                <div className="ad-toggle">
                  <Chips
                    values={['on', 'off'] as const}
                    now={on ? 'on' : 'off'}
                    onPick={(v) => editMove(name, v === 'on')}
                  />
                </div>
                <div className="ad-keys">
                  {m !== undefined && (
                    <span className="ad-def">{m.seconds.toFixed(1)}s</span>
                  )}
                  <button
                    type="button"
                    className="ad-mini"
                    // A flag can outlive the move file it names; there is
                    // nothing in SEQUENCES to open for one of those.
                    disabled={m === undefined}
                    onClick={() => onOpenMove(name)}
                  >
                    EDIT
                  </button>
                </div>
              </div>
              <div className="ad-sub">
                {m?.description ? m.description : 'no description'}
              </div>
            </div>
          )
        })}
      </div>
      <SaveBar
        dirty={dirty}
        blocked={over || blank}
        busy={busy}
        err={
          err ??
          (blank
            ? 'a tool description cannot be empty — RESET puts the default back'
            : null)
        }
        onSave={save}
        onRevert={() => {
          setDraft(clone(cfg.tools))
          setErr(null)
        }}
      />
    </section>
  )
}
