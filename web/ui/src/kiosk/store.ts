// KIOSK.md §3.6 — the kiosk's own store. A strict subset of the deck's: no
// teach, no admin, no token, no events. What a visitor may see and nothing more.
import { create } from 'zustand'
import type { ChatRow, FullState, Motor, Power, VoiceState } from '../types'
import { EXPECTED_IDS, MOTOR_NAMES } from '../types'

/** VOICE.md §2.2 — the bridge keeps this many rows, so we keep the same. */
const CHAT_MAX = 80

export interface KioskState {
  /** null until the first `deck` frame — the kiosk has not said yet */
  deckUp: boolean | null
  /** the browser's socket to the kiosk process */
  wsUp: boolean
  power: Power
  error: string | null
  playing: string | null
  motors: Motor[]
  latestPos: Record<string, number>
  voice: VoiceState | null
  chat: ChatRow[]
  /** a refused request's sentence, shown above the buttons for a moment.
   *  Wrapped with a serial so the SAME sentence twice is still a new toast
   *  and re-arms the timer — an equal string would be no change at all. */
  toast: { text: string; n: number } | null

  applyState(s: FullState): void
  setPos(pos: Record<string, number>): void
  setDeckUp(up: boolean): void
  setWsUp(on: boolean): void
  setVoice(v: VoiceState | null): void
  setChat(rows: ChatRow[]): void
  pushChat(row: ChatRow): void
  setToast(t: string | null): void
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

export const useKiosk = create<KioskState>()((set, get) => ({
  deckUp: null,
  wsUp: false,
  power: 'off',
  error: null,
  playing: null,
  motors: initialMotors(),
  latestPos: {},
  voice: null,
  chat: [],
  toast: null,

  applyState(s) {
    const patch: Partial<KioskState> = {
      power: s.power,
      error: s.error,
      playing: s.playing,
      motors: s.motors,
    }
    // The voice link rides in FullState so a reload restores it in one trip.
    if (s.voice) patch.voice = s.voice
    // A body that is off has no pose worth keeping; the twin goes dormant.
    if (s.power === 'off' || s.power === 'error') patch.latestPos = {}
    set(patch)
  },

  setPos(pos) {
    set({ latestPos: pos })
  },

  setDeckUp(up) {
    set({ deckUp: up })
  },

  setWsUp(on) {
    set({ wsUp: on })
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

  setToast(t) {
    const n = (get().toast?.n ?? 0) + 1
    set({ toast: t === null ? null : { text: t, n } })
  },
}))
