// REST helpers + reconnecting WebSocket client. Feeds the zustand store.
import { pushLevels } from './audioBus'
import { useStore } from './state'
import type {
  AudioDevices,
  ChatRow,
  FullState,
  HealthMotors,
  Move,
  PeopleReply,
  SessionInfo,
  SessionRow,
  VoicePrefs,
  VoiceState,
} from './types'

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

export function apiDeleteMove(name: string): Promise<FullState> {
  return post<FullState>('/api/moves/delete', { name })
}

export function apiRenameMove(
  from: string,
  to: string,
  meta?: { description?: string; when?: string[] },
): Promise<FullState> {
  return post<FullState>('/api/moves/rename', {
    from,
    to,
    description: meta?.description ?? '',
    when: meta?.when ?? [],
  })
}

export function apiScan(): Promise<FullState> {
  return post<FullState>('/api/scan')
}

// ---- REST: voice (VOICE.md §2.3) -----------------------------------------

export function apiVoice(): Promise<VoiceState> {
  return req<VoiceState>('/api/voice')
}

// Start / stop the session, write preferences, or both in one call. The new
// state comes back over the socket, so nothing here reads the response body.
export function apiVoiceSet(body: VoicePrefs & { on?: boolean }): Promise<unknown> {
  return post('/api/voice', body)
}

export function apiVoiceCmd(cmd: 'interrupt' | 'nudge'): Promise<unknown> {
  return post('/api/voice/cmd', { cmd })
}

export function apiVoicePtt(down: boolean): Promise<unknown> {
  return post('/api/voice/ptt', { down })
}

export function apiVoiceTag(name: string): Promise<unknown> {
  return post('/api/voice/tag', { name })
}

export function apiVoiceChat(): Promise<{ rows: ChatRow[] }> {
  return req<{ rows: ChatRow[] }>('/api/voice/chat')
}

// ---- REST: people (VOICE.md §2.4, §2.5) ----------------------------------

export function apiPeople(): Promise<PeopleReply> {
  return req<PeopleReply>('/api/people')
}

export function apiAddFact(name: string, fact: string): Promise<unknown> {
  return post('/api/people/fact', { name, fact })
}

export function apiDeleteFact(name: string, index: number): Promise<unknown> {
  return post('/api/people/fact/delete', { name, index })
}

export function apiRenamePerson(from: string, to: string): Promise<unknown> {
  return post('/api/people/rename', { from, to })
}

export function apiForgetPerson(name: string): Promise<unknown> {
  return post('/api/people/forget', { name })
}

export function apiEnrollStart(name: string): Promise<VoiceState> {
  return post<VoiceState>('/api/people/enroll/start', { name })
}

export function apiEnrollRecord(): Promise<VoiceState> {
  return post<VoiceState>('/api/people/enroll/record')
}

export function apiEnrollFinish(): Promise<VoiceState> {
  return post<VoiceState>('/api/people/enroll/finish')
}

export function apiEnrollCancel(): Promise<VoiceState> {
  return post<VoiceState>('/api/people/enroll/cancel')
}

// ---- REST: devices & sessions (VOICE.md §2.6) ----------------------------

export function apiAudioDevices(): Promise<AudioDevices> {
  return req<AudioDevices>('/api/audio/devices')
}

export function apiSessions(): Promise<SessionInfo[]> {
  return req<SessionInfo[]>('/api/sessions')
}

export function apiSession(file: string): Promise<{ rows: SessionRow[] }> {
  return req<{ rows: SessionRow[] }>(`/api/sessions/${encodeURIComponent(file)}`)
}

/** Re-read the roster. The bridge only tells us that it changed. */
export function refreshPeople(): void {
  apiPeople()
    .then((r) => useStore.getState().setPeople(r.people))
    .catch(() => {}) // already in the event log
}

// ---- WebSocket -----------------------------------------------------------

type WsMsg =
  | { t: 'hello'; state: FullState }
  | { t: 'pos'; pos: Record<string, number> }
  | ({ t: 'health' } & HealthMotors & { holding: boolean })
  | { t: 'state'; state: FullState }
  | { t: 'event'; ts: string; line: string }
  | { t: 'voice'; voice: VoiceState }
  | { t: 'lvl'; o: number; i: number; b: number[] }
  | { t: 'chat'; row: ChatRow }
  | { t: 'people' }

// One powered-off bus survey per page load, so the register and hologram
// show real health colors instead of 13 assumed faults.
let scannedOnce = false
function maybeAutoScan(s: FullState): void {
  if (scannedOnce || s.power !== 'off') return
  if (s.motors.some((m) => m.present)) return
  scannedOnce = true
  apiScan().catch(() => {}) // failure already lands in the event log
}

// The conversation and the roster are not in FullState — pull them on every
// hello so a reload, and a reconnect that missed rows, both land on a full
// VOICE tab instead of an empty one.
function hydrateVoice(): void {
  apiVoiceChat()
    .then((r) => useStore.getState().setChat(r.rows))
    .catch(() => {})
  refreshPeople()
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
        hydrateVoice()
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
      case 'people':
        refreshPeople()
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
