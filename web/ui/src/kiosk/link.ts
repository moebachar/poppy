// KIOSK.md §3.6 — REST helpers and the reconnecting socket to the kiosk
// process. The kiosk speaks the deck's protocol plus one frame of its own,
// {"t":"deck"}, which says whether there is a deck behind it at all.
import { pushLevels } from '../audioBus'
import { useKiosk } from './store'
import type { ChatRow, FullState, VoiceState } from '../types'

/** The server's own sentence when it sent one, the status line otherwise. */
function errText(body: unknown, res: Response): string {
  return body && typeof body === 'object' && 'error' in body
    ? String((body as { error: unknown }).error)
    : `${res.status} ${res.statusText}`
}

// There is no event log here: a failure is thrown as a sentence and the
// caller decides whether it is worth a toast.
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new Error('Poppy est injoignable')
  }
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) throw new Error(errText(body, res))
  return body as T
}

function post<T>(path: string, payload: unknown): Promise<T> {
  return req<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

// ---- REST: the allowlist (KIOSK.md §1.1), one helper each ----------------

export function getState(): Promise<FullState> {
  return req<FullState>('/api/state')
}

export function getChat(): Promise<{ rows: ChatRow[] }> {
  return req<{ rows: ChatRow[] }>('/api/voice/chat')
}

export function setPower(on: boolean): Promise<unknown> {
  return post('/api/power', { on })
}

export function stand(): Promise<unknown> {
  return post('/api/cmd', { cmd: 'hold' })
}

export function setVoice(on: boolean): Promise<VoiceState> {
  return post<VoiceState>('/api/voice', { on })
}

export function ptt(down: boolean): Promise<unknown> {
  return post('/api/voice/ptt', { down })
}

// ---- WebSocket -----------------------------------------------------------

type WsMsg =
  | { t: 'hello'; state: FullState }
  | { t: 'pos'; pos: Record<string, number> }
  | { t: 'health' }
  | { t: 'state'; state: FullState }
  | { t: 'event'; ts: string; line: string }
  | { t: 'voice'; voice: VoiceState }
  | { t: 'lvl'; o: number; i: number; b: number[] }
  | { t: 'chat'; row: ChatRow }
  | { t: 'deck'; up: boolean }

// The conversation is not in FullState — pull it on every hello so a reload,
// and a reconnect that missed rows, both land on a full chat.
function hydrateChat(): void {
  getChat()
    .then((r) => useKiosk.getState().setChat(r.rows))
    .catch(() => {})
}

const BACKOFF_MS = [1000, 2000, 5000]
let wsStarted = false
let attempt = 0

export function connect(): void {
  if (wsStarted) return
  wsStarted = true
  open()
}

function open(): void {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/ws`)
  const store = useKiosk.getState

  ws.onopen = () => {
    attempt = 0
    store().setWsUp(true)
  }

  ws.onmessage = (ev) => {
    let msg: WsMsg
    try {
      msg = JSON.parse(ev.data as string) as WsMsg
    } catch {
      return
    }
    switch (msg.t) {
      case 'deck':
        store().setDeckUp(msg.up)
        break
      case 'hello':
        // A hello only ever comes from a live deck — the kiosk process cuts
        // it from the deck's own state, and the deck itself sends one when
        // this page is opened straight from :8000/kiosk.html, where no
        // {"t":"deck"} frame will ever come.
        store().setDeckUp(true)
        store().applyState(msg.state)
        hydrateChat()
        break
      case 'state':
        store().applyState(msg.state)
        break
      case 'pos':
        store().setPos(msg.pos)
        break
      case 'voice':
        store().setVoice(msg.voice)
        break
      case 'lvl':
        // 30 Hz — straight to the bus, never through the store.
        pushLevels(msg.o, msg.i, msg.b)
        break
      case 'chat':
        store().pushChat(msg.row)
        break
      case 'health':
      case 'event':
        // Operator telemetry; the kiosk shows neither.
        break
    }
  }

  ws.onclose = () => {
    store().setWsUp(false)
    const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]
    attempt += 1
    setTimeout(open, wait)
  }

  ws.onerror = () => {
    ws.close()
  }
}
