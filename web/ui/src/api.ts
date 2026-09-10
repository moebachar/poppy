// REST helpers + reconnecting WebSocket client. Feeds the zustand store.
import { pushLevels } from './audioBus'
import { useStore } from './state'
import type {
  AdminConfig,
  AdminLogin,
  AdminPatch,
  AdminPreview,
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

/** The server's own sentence when it sent one, the status line otherwise. */
function errText(body: unknown, res: Response): string {
  return body && typeof body === 'object' && 'error' in body
    ? String((body as { error: unknown }).error)
    : `${res.status} ${res.statusText}`
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
    const msg = errText(body, res)
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

// ---- gated REST (VOICE.md §5.2) ------------------------------------------
// Everything under /api/admin/* (except login) and every /api/people/* route
// carries X-Admin-Token. A 401 means the gate closed under us: drop the token
// so the page falls back to its login field, and stay quiet in the event log —
// the login field IS the message, and a stale token would 401 for ever.
// The one exception is /api/admin/password, which answers a wrong CURRENT with
// a 401 of its own: see `answers401` below.

function adminHeaders(json: boolean): Record<string, string> {
  const h: Record<string, string> = {}
  if (json) h['Content-Type'] = 'application/json'
  const t = useStore.getState().adminToken
  if (t !== null) h['X-Admin-Token'] = t
  return h
}

/** `answers401` marks a route where 401 is the server's ANSWER to what was
 *  sent, not a verdict on the token — the password change is the only one. */
async function gated<T>(
  path: string,
  payload?: unknown,
  answers401 = false,
): Promise<T> {
  const init: RequestInit =
    payload === undefined
      ? { headers: adminHeaders(false) }
      : {
          method: 'POST',
          headers: adminHeaders(true),
          body: JSON.stringify(payload),
        }
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
  const msg = errText(body, res)
  if (res.status === 401) {
    // Signing the page out here would cost the caller everything it was doing,
    // so only a 401 that really is the gate closing may do it. Either way the
    // sentence goes back to the caller and not into the event log.
    if (!answers401) useStore.getState().setAdminToken(null)
    throw new Error(msg)
  }
  if (!res.ok) {
    useStore.getState().pushEvent(nowTs(), `ERR ${msg}`)
    throw new Error(msg)
  }
  return body as T
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

// Start / stop the session, and nothing else. This route used to take the
// speech preferences too, which put one setting behind two doors with only one
// of them locked; the bridge now answers any preference key here with a 400,
// so `on` is the whole body and the type says so — a future caller cannot
// reopen the hole by accident. Preferences go through apiSpeechSet below.
// The bridge broadcasts the new state AND returns it: a caller whose socket is
// down still gets an answer, so callers that need to know it landed read the
// body.
export function apiVoiceSet(body: { on: boolean }): Promise<VoiceState> {
  return post<VoiceState>('/api/voice', body)
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

// ---- REST: people (VOICE.md §2.4, §2.5 — behind the gate since §5.2) -----

export function apiPeople(): Promise<PeopleReply> {
  return gated<PeopleReply>('/api/people')
}

export function apiAddFact(name: string, fact: string): Promise<unknown> {
  return gated('/api/people/fact', { name, fact })
}

export function apiDeleteFact(name: string, index: number): Promise<unknown> {
  return gated('/api/people/fact/delete', { name, index })
}

export function apiRenamePerson(from: string, to: string): Promise<unknown> {
  return gated('/api/people/rename', { from, to })
}

export function apiForgetPerson(name: string): Promise<unknown> {
  return gated('/api/people/forget', { name })
}

export function apiEnrollStart(name: string): Promise<VoiceState> {
  return gated<VoiceState>('/api/people/enroll/start', { name })
}

export function apiEnrollRecord(): Promise<VoiceState> {
  return gated<VoiceState>('/api/people/enroll/record', {})
}

export function apiEnrollFinish(): Promise<VoiceState> {
  return gated<VoiceState>('/api/people/enroll/finish', {})
}

export function apiEnrollCancel(): Promise<VoiceState> {
  return gated<VoiceState>('/api/people/enroll/cancel', {})
}

// ---- REST: admin (VOICE.md §5.3) -----------------------------------------

/** The only ungated admin route — and the only one that must not log a 401,
 *  since a wrong password is an answer, not a fault. */
export async function apiAdminLogin(password: string): Promise<AdminLogin> {
  let res: Response
  try {
    res = await fetch('/api/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    })
  } catch {
    throw new Error('server unreachable')
  }
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) throw new Error(errText(body, res))
  return body as AdminLogin
}

export function apiAdminConfig(): Promise<AdminConfig> {
  return gated<AdminConfig>('/api/admin/config')
}

export function apiAdminSave(patch: AdminPatch): Promise<AdminConfig> {
  return gated<AdminConfig>('/api/admin/config', patch)
}

/** The SPEECH block (web/voice_prefs.json). These are per-machine session
 *  parameters rather than agent overrides, but they ride the same gated route
 *  because they are the same settings page: POST /api/voice now refuses every
 *  preference key, and this is the door it points at. The answer carries
 *  `params` — what is actually on disk after the write — so a caller can
 *  settle its own draft without waiting for a {"t":"voice"} broadcast that a
 *  dropped socket will never deliver. */
export function apiSpeechSet(params: VoicePrefs): Promise<AdminConfig> {
  return gated<AdminConfig>('/api/admin/config', { params })
}

/** Drop one override, or every one of them with '*'. */
export function apiAdminReset(path: string): Promise<unknown> {
  return gated('/api/admin/config/reset', { path })
}

export function apiAdminPreview(): Promise<AdminPreview> {
  return gated<AdminPreview>('/api/admin/preview')
}

/** A wrong CURRENT comes back as 401, exactly like a wrong password at the
 *  login field — an answer, not an expiry. Treating it as one would drop the
 *  token on a typo and mount the gate over the very sentence that explains it,
 *  so this is the one gated route that keeps the token on a 401. */
export function apiAdminPassword(
  current: string,
  next: string,
): Promise<unknown> {
  return gated('/api/admin/password', { current, next }, true)
}

// ---- REST: devices & sessions (VOICE.md §2.6) ----------------------------

export function apiAudioDevices(): Promise<AudioDevices> {
  return req<AudioDevices>('/api/audio/devices')
}

/** Gated, like /api/people and for the same reason: a past transcript is the
 *  raw material the personal facts were mined out of, and SESSIONS lives on
 *  the admin page (VOICE.md §5.4). Through req() these would be a guaranteed
 *  401 and an ERR row in the event log on every mount. */
export function apiSessions(): Promise<SessionInfo[]> {
  return gated<SessionInfo[]>('/api/sessions')
}

export function apiSession(file: string): Promise<{ rows: SessionRow[] }> {
  return gated<{ rows: SessionRow[] }>(
    `/api/sessions/${encodeURIComponent(file)}`,
  )
}

/** Re-read the roster. The bridge only tells us that it changed.
 *  Without a token the request is a guaranteed 401 (VOICE.md §5.2), and the
 *  deck asks on every hello — so it stays silent until the gate is open. */
export function refreshPeople(): void {
  if (useStore.getState().adminToken === null) return
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
