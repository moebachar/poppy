// Shared shapes mirroring web/CONTRACT.md — FullState + WS messages —
// and web/VOICE.md for everything under "voice".
import type { VoicePhase } from './holo'

export type Power =
  | 'off'
  | 'starting'
  | 'ready'
  | 'playing'
  | 'recording'
  | 'released'
  | 'cooling'
  | 'error'

export interface Motor {
  id: number
  name: string
  model: string
  present: boolean
  ok: boolean
  pos: number | null
  temp: number | null
  volt: number | null
}

export interface Move {
  name: string
  seconds: number
  frames: number
  /** What the move looks like — read by the voice agent when choosing moves. */
  description?: string
  /** Situations that call for this move, one per entry. */
  when?: string[]
}

export interface RecordingInfo {
  loose: Record<string, number>
  started: string // "14:01:59"
}

export interface FullState {
  power: Power
  port: string | null
  error: string | null
  playing: string | null
  recording: RecordingInfo | null
  moves: Move[]
  motors: Motor[]
  /** VOICE.md §2.7 — absent from a bridge built before the voice track. */
  voice?: VoiceState
}

// ---- voice (web/VOICE.md) -------------------------------------------------

/** The bridge's phase: the hologram's own union plus its two bridge-only states. */
export type VoiceLinkPhase = VoicePhase | 'starting' | 'error'

export type VoiceVad = 'semantic' | 'server'
export type VoiceDuplex = 'full' | 'gate' | 'ptt'
export type EnrollStatus = 'loading' | 'ready' | 'recording' | 'done'

export interface EnrollState {
  name: string
  step: number
  of: number
  status: EnrollStatus
  prompt: string
  note: string | null
  clips: number
}

export interface VoiceState {
  on: boolean
  phase: VoiceLinkPhase
  error: string | null
  started: string | null
  voice: string
  model: string
  vad: VoiceVad
  fx: number
  nudge: number
  duplex: VoiceDuplex
  identify: boolean
  /** small idle + talking motions while a session is up */
  gestures: boolean
  input: number | null
  output: number | null
  /** the push-to-talk key as a KeyboardEvent.code, e.g. "KeyV" (src/pttKey.ts) */
  ptt_key: string
  people: number
  moves: number
  resp: { avg: number; n: number } | null
  enroll: EnrollState | null
}

/** The eleven speech settings — voicelink.PREF_KEYS, one for one. They are NOT
 *  part of POST /api/voice any more (that route takes `on` and refuses these);
 *  they are written through the gated POST /api/admin/config as `params`. */
export type VoicePrefs = Partial<
  Pick<
    VoiceState,
    | 'voice'
    | 'model'
    | 'vad'
    | 'fx'
    | 'nudge'
    | 'duplex'
    | 'identify'
    | 'gestures'
    | 'input'
    | 'output'
    | 'ptt_key'
  >
>

export type ChatKind = 'say' | 'heard' | 'tool' | 'note'
export type Verdict = 'confident' | 'tentative' | 'unknown' | 'nobody-enrolled'

export interface ChatRow {
  n: number
  ts: string // "14:02:11"
  kind: ChatKind
  who: string | null // "poppy" | a person's name | null
  text: string
  score: number | null
  verdict: Verdict | null
  ok: boolean | null
}

export interface PersonFact {
  t: string // "2026-08-21"
  text: string
}

export interface Person {
  name: string
  slug: string
  prints: number
  adaptive: number
  encounters: number
  created: string
  last_seen: string // "2026-08-21 10:53"
  facts: PersonFact[]
}

export interface PeopleReply {
  people: Person[]
  model: 'cached' | 'missing'
  voice_on: boolean
}

export interface AudioDevice {
  i: number
  name: string
}

export interface AudioDevices {
  input: AudioDevice[]
  output: AudioDevice[]
  default: { input: number | null; output: number | null }
}

export interface SessionInfo {
  file: string // "20260821-104900.jsonl"
  when: string // "2026-08-21 10:49"
  lines: number
  who: string[]
}

export interface SessionRow {
  t: string
  who: string
  text: string
}

/** The realtime voices live_agent.py accepts, in its own order. */
export const REALTIME_VOICES = [
  'cedar',
  'marin',
  'alloy',
  'ash',
  'ballad',
  'coral',
  'echo',
  'sage',
  'shimmer',
  'verse',
] as const

export const REALTIME_MODELS = ['gpt-realtime-2.1', 'gpt-realtime-2.1-mini'] as const

// ---- admin (web/VOICE.md §5) ---------------------------------------------

export interface AdminPrompt {
  instructions: string
  greeting: string
  nudge_prompt: string
}

/** A tool the model may be handed. A move carries no description here — its
 *  own lives in the move file and is still edited from SEQUENCES. */
export interface AdminTool {
  enabled: boolean
  description?: string
}

/** The built-ins by name (stop_moving, enroll_speaker, remember_person),
 *  plus `moves` — one entry per recorded move. */
export interface AdminTools {
  moves: Record<string, AdminTool>
  [name: string]: AdminTool | Record<string, AdminTool>
}

/** The seven numbers that decide who is speaking (VOICE.md §5.1). */
export interface AdminRecognition {
  confident: number
  tentative: number
  margin: number
  min_seconds: number
  adapt_score: number
  adapt_margin: number
  adapt_seconds: number
}

export interface AdminTree {
  prompt: AdminPrompt
  tools: AdminTools
  recognition: AdminRecognition
}

export interface AdminConfig extends AdminTree {
  /** per-machine session parameters, echoed from web/voice_prefs.json */
  params?: VoicePrefs
  /** the full default tree, so a field can be diffed and offered a reset */
  defaults?: AdminTree
  /** dotted paths that currently differ from the default */
  changed: string[]
  /** why perception/agent_config.json is being ignored, when it is. The tree
   *  above is then pure defaults and `changed` is empty — which would
   *  otherwise read as "nothing was ever changed". */
  error?: string | null
}

/** POST /api/admin/config — a patch of the same shape. `params` is the SPEECH
 *  block: per-machine, so it is written straight to web/voice_prefs.json
 *  rather than stored as an agent override, but it travels this gated route
 *  because POST /api/voice no longer accepts a preference key. */
export interface AdminPatch {
  prompt?: Partial<AdminPrompt>
  tools?: AdminTools
  recognition?: Partial<AdminRecognition>
  params?: VoicePrefs
}

export interface AdminPreview {
  instructions: string
  roster: string
  tools: unknown[]
  session: Record<string, unknown>
}

export interface AdminLogin {
  token: string
  expires: string
}

/** VOICE.md §5.3 — anything longer comes back as a 400. */
export const ADMIN_LIMITS = {
  instructions: 20000,
  greeting: 2000,
  nudge_prompt: 2000,
  description: 1000,
} as const

function isTool(v: AdminTool | Record<string, AdminTool>): v is AdminTool {
  return typeof (v as { enabled?: unknown }).enabled === 'boolean'
}

/** The built-in tools, in the order the bridge sent them — `moves` is not one. */
export function builtinTools(t: AdminTools): [string, AdminTool][] {
  const out: [string, AdminTool][] = []
  for (const k of Object.keys(t)) {
    if (k === 'moves') continue
    const v = t[k]
    if (isTool(v)) out.push([k, v])
  }
  return out
}

export interface HealthMotors {
  maxtemp: number | null
  motors: Record<string, { t: number; v: number }>
}

export interface EventLine {
  ts: string // "14:02:11"
  line: string
}

/** Fixed register order — the EXPECTED map from scripts/motion/00_read_only.py */
export const EXPECTED_IDS = [
  33, 34, 35, 36, 37, 41, 42, 43, 44, 51, 52, 53, 54,
] as const

export const MOTOR_NAMES: Record<number, string> = {
  33: 'abs_z',
  34: 'bust_y',
  35: 'bust_x',
  36: 'head_z',
  37: 'head_y',
  41: 'l_shoulder_y',
  42: 'l_shoulder_x',
  43: 'l_arm_z',
  44: 'l_elbow_y',
  51: 'r_shoulder_y',
  52: 'r_shoulder_x',
  53: 'r_arm_z',
  54: 'r_elbow_y',
}

/** "l_shoulder_y" -> "L.SHOULDER.Y" */
export function motorLabel(name: string): string {
  return name.toUpperCase().replace(/_/g, '.')
}
