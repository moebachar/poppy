import { create } from 'zustand'
import type {
  ChatRow,
  EventLine,
  FullState,
  HealthMotors,
  Motor,
  Move,
  Person,
  Power,
  RecordingInfo,
  VoiceState,
} from './types'
import { EXPECTED_IDS, MOTOR_NAMES } from './types'

export type HoverSource = 'row' | 'holo'
export type SideTab = 'seq' | 'voice' | 'people'

/** VOICE.md §2.2 — the bridge keeps this many rows, so we keep the same. */
const CHAT_MAX = 80

export interface DeckState {
  // ---- mirror of FullState ----
  power: Power
  port: string | null
  error: string | null
  playing: string | null
  recording: RecordingInfo | null
  moves: Move[]
  motors: Motor[]
  /** true once any FullState arrived from the server */
  seenState: boolean

  // ---- live telemetry ----
  latestPos: Record<string, number>
  health: HealthMotors

  // ---- events ring (max 40, newest first) ----
  events: EventLine[]

  // ---- ui state ----
  wsConnected: boolean
  hoveredMotor: number | null
  hoverSource: HoverSource | null
  /** teach flow entered (picking until power hits 'recording') */
  teachActive: boolean
  /** picked motor id -> teach feel pct (0 = free, 20 loose, 100 rigid) */
  picked: Record<number, number>
  /** local ms timestamp when we saw power enter 'recording' */
  recStartedAt: number | null
  /** true from power-on press until holo finishes its awakening choreography */
  awaitingAwaken: boolean
  /** move whose description / 'when' list is open for editing */
  editingMove: string | null
  /** which panel the side column is showing above TEACH / EVENT LOG */
  sideTab: SideTab

  // ---- voice (web/VOICE.md) ----
  voice: VoiceState | null
  /** the conversation, oldest first — newest is the last row */
  chat: ChatRow[]
  people: Person[]

  // ---- actions ----
  applyState(s: FullState): void
  setPos(pos: Record<string, number>): void
  setHealth(h: HealthMotors): void
  pushEvent(ts: string, line: string): void
  setWsConnected(on: boolean): void
  setHovered(id: number | null, source: HoverSource): void
  startTeach(): void
  cancelTeach(): void
  togglePick(id: number): void
  stepPct(id: number, delta: number): void
  clearAwaken(): void
  setEditingMove(name: string | null): void
  setSideTab(tab: SideTab): void
  setVoice(v: VoiceState | null): void
  setChat(rows: ChatRow[]): void
  pushChat(row: ChatRow): void
  setPeople(p: Person[]): void
}

function initialMotors(): Motor[] {
  return EXPECTED_IDS.map((id) => ({
    id,
    name: MOTOR_NAMES[id],
    model: '',
    present: false,
    ok: false,
    pos: null,
    temp: null,
    volt: null,
  }))
}

export const useStore = create<DeckState>()((set, get) => ({
  power: 'off',
  port: null,
  error: null,
  playing: null,
  recording: null,
  moves: [],
  motors: initialMotors(),
  seenState: false,

  latestPos: {},
  health: { maxtemp: null, motors: {} },

  events: [],

  wsConnected: false,
  hoveredMotor: null,
  hoverSource: null,
  teachActive: false,
  picked: {},
  recStartedAt: null,
  awaitingAwaken: false,
  editingMove: null,
  sideTab: 'seq',

  voice: null,
  chat: [],
  people: [],

  applyState(s) {
    const prev = get()
    const patch: Partial<DeckState> = {
      power: s.power,
      port: s.port,
      error: s.error,
      playing: s.playing,
      recording: s.recording,
      moves: s.moves,
      motors: s.motors,
      seenState: true,
    }
    // The voice link is independent of the body: it rides along in FullState
    // only so a reload restores it in one round trip.
    if (s.voice) patch.voice = s.voice
    if (s.power === 'recording' && prev.power !== 'recording') {
      // Only trust a locally observed transition; on reload fall back to
      // the server's recording.started timestamp.
      patch.recStartedAt = prev.seenState ? Date.now() : null
    }
    if (s.power !== 'recording' && prev.power === 'recording') {
      // RECORD_SAVED / RECORD_ABORTED / release — teach flow is over.
      patch.recStartedAt = null
      patch.teachActive = false
      patch.picked = {}
    }
    if (s.power === 'starting' && prev.power !== 'starting') {
      patch.awaitingAwaken = true
    }
    if (s.power === 'off' || s.power === 'error') {
      patch.teachActive = false
      patch.picked = {}
      patch.recStartedAt = null
      patch.awaitingAwaken = false
      patch.editingMove = null
      patch.latestPos = {}
      patch.health = { maxtemp: null, motors: {} }
    }
    set(patch)
  },

  setPos(pos) {
    set({ latestPos: pos })
  },

  setHealth(h) {
    set({ health: h })
  },

  pushEvent(ts, line) {
    set({ events: [{ ts, line }, ...get().events].slice(0, 40) })
  },

  setWsConnected(on) {
    set({ wsConnected: on })
  },

  setHovered(id, source) {
    set({ hoveredMotor: id, hoverSource: id === null ? null : source })
  },

  startTeach() {
    if (get().power !== 'ready') return
    set({ teachActive: true, picked: {} })
  },

  cancelTeach() {
    set({ teachActive: false, picked: {} })
  },

  togglePick(id) {
    const { teachActive, power, picked, motors } = get()
    if (!teachActive || power !== 'ready') return
    const m = motors.find((x) => x.id === id)
    if (!m || !m.present) return
    const next = { ...picked }
    if (id in next) delete next[id]
    else next[id] = 20
    set({ picked: next })
  },

  stepPct(id, delta) {
    const { picked } = get()
    if (!(id in picked)) return
    const v = Math.max(0, Math.min(100, picked[id] + delta))
    set({ picked: { ...picked, [id]: v } })
  },

  clearAwaken() {
    set({ awaitingAwaken: false })
  },

  setEditingMove(name) {
    set({ editingMove: name })
  },

  setSideTab(tab) {
    set({ sideTab: tab })
  },

  setVoice(v) {
    set({ voice: v })
  },

  setChat(rows) {
    set({ chat: rows.slice(-CHAT_MAX) })
  },

  pushChat(row) {
    const chat = get().chat
    const last = chat[chat.length - 1]
    // The bridge renumbers from 1 when a session starts; a row that goes
    // backwards means what is on screen belongs to a conversation that is over.
    const base = last && row.n <= last.n ? [] : chat
    set({ chat: [...base, row].slice(-CHAT_MAX) })
  },

  setPeople(p) {
    set({ people: p })
  },
}))
