// REST helpers + reconnecting WebSocket client. Feeds the zustand store.
import { useStore } from './state'
import type { FullState, HealthMotors, Move } from './types'

function nowTs(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    useStore.getState().pushEvent(nowTs(), 'ERR server unreachable')
    throw new Error('server unreachable')
  }
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const msg =
      body && typeof body === 'object' && 'error' in body
        ? String((body as { error: unknown }).error)
        : `${res.status} ${res.statusText}`
    useStore.getState().pushEvent(nowTs(), `ERR ${msg}`)
    throw new Error(msg)
  }
  return body as T
}

function post<T>(path: string, payload?: unknown): Promise<T> {
  return req<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload === undefined ? '{}' : JSON.stringify(payload),
  })
}

// ---- REST ----------------------------------------------------------------

export function apiState(): Promise<FullState> {
  return req<FullState>('/api/state')
}

export function apiPower(on: boolean): Promise<unknown> {
  return post('/api/power', { on })
}

export function apiCmd(cmd: 'hold' | 'release' | 'look' | 'stop'): Promise<unknown> {
  return post('/api/cmd', { cmd })
}

export function apiPlay(name: string): Promise<unknown> {
  return post('/api/play', { name })
}

export function apiRecordStart(loose: Record<number, number>): Promise<unknown> {
  return post('/api/record/start', { loose })
}

export function apiRecordStop(name: string): Promise<unknown> {
  return post('/api/record/stop', { name })
}

export function apiRecordAbort(): Promise<unknown> {
  return post('/api/record/abort')
}

export function apiMoves(): Promise<Move[]> {
  return req<Move[]>('/api/moves')
}

export function apiScan(): Promise<FullState> {
  return post<FullState>('/api/scan')
}

// ---- WebSocket -----------------------------------------------------------

type WsMsg =
  | { t: 'hello'; state: FullState }
  | { t: 'pos'; pos: Record<string, number> }
  | ({ t: 'health' } & HealthMotors & { holding: boolean })
  | { t: 'state'; state: FullState }
  | { t: 'event'; ts: string; line: string }

// One powered-off bus survey per page load, so the register and hologram
// show real health colors instead of 13 assumed faults.
let scannedOnce = false
function maybeAutoScan(s: FullState): void {
  if (scannedOnce || s.power !== 'off') return
  if (s.motors.some((m) => m.present)) return
  scannedOnce = true
  apiScan().catch(() => {}) // failure already lands in the event log
}

const BACKOFF_MS = [1000, 2000, 5000]
let wsStarted = false
let attempt = 0

export function connectWS(): void {
  if (wsStarted) return
  wsStarted = true
  open()
}

function open(): void {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/ws`)
  const store = useStore.getState

  ws.onopen = () => {
    attempt = 0
    store().setWsConnected(true)
  }

  ws.onmessage = (ev) => {
    let msg: WsMsg
    try {
      msg = JSON.parse(ev.data as string) as WsMsg
    } catch {
      return
    }
    switch (msg.t) {
      case 'hello':
        store().applyState(msg.state)
        maybeAutoScan(msg.state)
        break
      case 'state':
        store().applyState(msg.state)
        break
      case 'pos':
        store().setPos(msg.pos)
        break
      case 'health':
        store().setHealth({ maxtemp: msg.maxtemp, motors: msg.motors })
        break
      case 'event':
        store().pushEvent(msg.ts, msg.line)
        break
    }
  }

  ws.onclose = () => {
    store().setWsConnected(false)
    const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]
    attempt += 1
    setTimeout(open, wait)
  }

  ws.onerror = () => {
    ws.close()
  }
}
