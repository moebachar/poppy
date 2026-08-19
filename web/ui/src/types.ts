// Shared shapes mirroring web/CONTRACT.md — FullState + WS messages.

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
