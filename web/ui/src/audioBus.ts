// The 30 Hz voice levels, deliberately kept OUT of the zustand store: one
// store write per frame would re-render the whole deck thirty times a second.
// api.ts pushes here straight from the socket; the aura and the panel meter
// each pull from their own animation frame.

export interface Levels {
  out: number
  in: number
  bands: number[]
  at: number
}

const BANDS = 8
const FRESH_MS = 120 // a dropped frame or two is normal at 30 Hz
const DECAY_MS = 260 // past that the feed is gone — bleed it to silence

function clamp01(v: number): number {
  // NaN falls through both tests and lands on 0, which is what we want.
  return v > 1 ? 1 : v > 0 ? v : 0
}

function bandsOf(b: number[]): number[] {
  const out = new Array<number>(BANDS)
  for (let i = 0; i < BANDS; i++) out[i] = clamp01(b[i] ?? 0)
  return out
}

const SILENT: Levels = { out: 0, in: 0, bands: bandsOf([]), at: 0 }

let latest: Levels = SILENT
const subs = new Set<(l: Levels) => void>()

export function pushLevels(o: number, i: number, b: number[]): void {
  latest = {
    out: clamp01(o),
    in: clamp01(i),
    bands: bandsOf(b),
    at: performance.now(),
  }
  for (const cb of subs) cb(latest)
}

/** Latest levels, faded toward silence when the feed has stopped arriving. */
export function readLevels(): Levels {
  if (latest.at === 0) return latest
  const age = performance.now() - latest.at - FRESH_MS
  if (age <= 0) return latest
  const k = Math.exp(-age / DECAY_MS)
  if (k < 0.002) return SILENT
  return {
    out: latest.out * k,
    in: latest.in * k,
    bands: latest.bands.map((v) => v * k),
    at: latest.at,
  }
}

export function subscribeLevels(cb: (l: Levels) => void): () => void {
  subs.add(cb)
  return () => {
    subs.delete(cb)
  }
}
