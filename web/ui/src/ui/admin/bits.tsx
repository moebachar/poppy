// Small pieces every admin section shares: the section head, the SAVE/REVERT
// bar, the chip row moved out of the VOICE tab's old CONFIG block, and the two
// helpers that decide whether a field still differs from its default.
import type { ReactNode } from 'react'

/** "2026-08-21 10:53" -> "21/08 10:53" */
export function fmtWhen(s: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/.exec(s)
  return m ? `${m[3]}/${m[2]} ${m[4]}` : s
}

/** A draft is edited in place, so it never shares structure with the server's
 *  copy — that copy is what REVERT and the dirty flag are measured against. */
export function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T
}

/** "stop_moving" -> "STOP MOVING" */
export function toolLabel(name: string): string {
  return name.toUpperCase().replace(/_/g, ' ')
}

export function Head({
  title,
  tag,
  children,
}: {
  title: string
  tag?: string
  children?: ReactNode
}) {
  return (
    <div className="ad-head">
      <span className="ad-title">{title}</span>
      {tag !== undefined && <span className="ad-tag">{tag}</span>}
      {children}
    </div>
  )
}

export function SaveBar({
  dirty,
  blocked,
  busy,
  err,
  onSave,
  onRevert,
}: {
  dirty: boolean
  blocked: boolean
  busy: boolean
  err: string | null
  onSave: () => void
  onRevert: () => void
}) {
  return (
    <div className="ad-savebar">
      <button
        type="button"
        className="key"
        disabled={!dirty || blocked || busy}
        onClick={onSave}
      >
        SAVE
      </button>
      <button
        type="button"
        className="key"
        disabled={!dirty || busy}
        onClick={onRevert}
      >
        REVERT
      </button>
      {err !== null && <span className="ad-bad">{err}</span>}
    </div>
  )
}

export function Chips<T extends string>({
  values,
  now,
  onPick,
}: {
  values: readonly T[]
  now: T
  onPick: (v: T) => void
}) {
  return (
    <div className="v-chips">
      {values.map((v) => (
        <button
          key={v}
          type="button"
          className={`chip${v === now ? ' on' : ''}`}
          onClick={() => onPick(v)}
        >
          {v}
        </button>
      ))}
    </div>
  )
}
