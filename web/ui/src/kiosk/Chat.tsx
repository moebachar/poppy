// KIOSK.md §3.3 — the conversation, for a reader rather than an operator:
// no scores, no verdicts, just who said what and when.
import { useEffect, useRef } from 'react'
import { useKiosk } from './store'
import type { ChatRow } from '../types'

/** Bubbles from one speaker in a row share a name cap and a timestamp. */
interface Run {
  key: number
  speaker: 'say' | 'heard'
  who: string
  rows: ChatRow[]
}

type Item =
  | { key: number; kind: 'run'; run: Run }
  | { key: number; kind: 'tool' | 'note'; row: ChatRow }

function speakerOf(r: ChatRow): string {
  if (r.kind === 'say') return 'Poppy'
  return r.who ?? "Quelqu'un"
}

function group(chat: ChatRow[]): Item[] {
  const out: Item[] = []
  for (const r of chat) {
    if (r.kind === 'tool' || r.kind === 'note') {
      out.push({ key: r.n, kind: r.kind, row: r })
      continue
    }
    const who = speakerOf(r)
    const last = out[out.length - 1]
    if (last && last.kind === 'run' && last.run.speaker === r.kind && last.run.who === who) {
      last.run.rows.push(r)
    } else {
      out.push({ key: r.n, kind: 'run', run: { key: r.n, speaker: r.kind, who, rows: [r] } })
    }
  }
  return out
}

function Chip({ row }: { row: ChatRow }) {
  const tail = row.ok === null ? '' : row.ok ? ' · fait' : ' · raté'
  return (
    <div className={`chip${row.ok === false ? ' failed' : ''}`}>
      {row.text}
      {tail}
    </div>
  )
}

function Bubbles({ run }: { run: Run }) {
  const last = run.rows[run.rows.length - 1]
  return (
    <div className={`run ${run.speaker}`}>
      <div className="cap">{run.who}</div>
      {run.rows.map((r) => (
        <div key={r.n} className="bubble">
          {r.text}
        </div>
      ))}
      <div className="ts">{last.ts}</div>
    </div>
  )
}

export default function Chat() {
  const chat = useKiosk((s) => s.chat)
  // "Press Voice" is advice; with no deck behind the button it is a lie, and
  // the header is already saying what is wrong
  const deckDown = useKiosk((s) => s.deckUp === false)
  const logRef = useRef<HTMLDivElement | null>(null)
  const stickRef = useRef(true)
  // Not chat.length: past 80 rows the ring stops growing and only `n` moves.
  const newest = chat.length ? chat[chat.length - 1].n : 0

  // Only chase the newest row when the reader is already at the bottom —
  // never yank the view while they are reading back.
  useEffect(() => {
    const el = logRef.current
    if (!el || !stickRef.current) return
    el.scrollTop = el.scrollHeight
  }, [newest])

  const onScroll = () => {
    const el = logRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  }

  return (
    <div className="chat" ref={logRef} onScroll={onScroll}>
      {chat.length === 0 && !deckDown && (
        <div className="empty">Appuyez sur Voix et dites bonjour.</div>
      )}
      {group(chat).map((it) => {
        if (it.kind === 'run') return <Bubbles key={it.key} run={it.run} />
        if (it.kind === 'tool') return <Chip key={it.key} row={it.row} />
        return (
          <div key={it.key} className="note">
            {it.row.text}
          </div>
        )
      })}
    </div>
  )
}
