// The push-to-talk key, shared by the deck's HOLD TO TALK, the admin page's
// picker and the kiosk's bar. Stored as a KeyboardEvent.code — the physical
// key — so the same setting means the same key on an AZERTY laptop and a
// QWERTY tablet. The bridge (web/voicelink.py PTT_KEY_RE) is the authority on
// what is allowed; this is the same rule, so the picker can refuse before
// asking.

export const DEFAULT_PTT_KEY = 'KeyV'

export const PTT_KEY_RE =
  /^(Key[A-Z]|Digit[0-9]|F([1-9]|1[0-2])|(Shift|Control|Alt)(Left|Right)|Enter|NumpadEnter|Numpad[0-9]|Backquote|Backslash|Slash|Period|Comma|Semicolon|Quote|BracketLeft|BracketRight|Minus|Equal|CapsLock|Insert|Home|End|PageUp|PageDown)$/

const NAMES: Record<string, string> = {
  ShiftLeft: 'LEFT SHIFT',
  ShiftRight: 'RIGHT SHIFT',
  ControlLeft: 'LEFT CTRL',
  ControlRight: 'RIGHT CTRL',
  AltLeft: 'LEFT ALT',
  AltRight: 'RIGHT ALT',
  NumpadEnter: 'NUMPAD ENTER',
  Backquote: '`',
  Backslash: '\\',
  Slash: '/',
  Period: '.',
  Comma: ',',
  Semicolon: ';',
  Quote: "'",
  BracketLeft: '[',
  BracketRight: ']',
  Minus: '-',
  Equal: '=',
  CapsLock: 'CAPS LOCK',
  PageUp: 'PAGE UP',
  PageDown: 'PAGE DOWN',
}

/** "KeyV" → "V", "Digit3" → "3", "ShiftRight" → "RIGHT SHIFT". */
export function pttKeyLabel(code: string): string {
  if (code.startsWith('Key')) return code.slice(3)
  if (code.startsWith('Digit')) return code.slice(5)
  if (code.startsWith('Numpad') && code !== 'NumpadEnter') return `NUMPAD ${code.slice(6)}`
  return NAMES[code] ?? code.toUpperCase()
}

/** Why a pressed key is refused, or null when it is fine. */
export function pttKeyProblem(code: string): string | null {
  if (code === 'Space') return 'SPACE IS STOP'
  if (code === 'Escape' || code === 'Tab') return 'THAT KEY IS THE BROWSER’S'
  if (!PTT_KEY_RE.test(code)) return 'NOT A KEY POPPY CAN USE'
  return null
}

/** The key alone: with a modifier held it is a shortcut, not the button. */
export function isPttKey(e: KeyboardEvent, code: string): boolean {
  if (e.code !== code) return false
  // the modifier keys ARE the key when chosen — only refuse OTHER modifiers
  const mod = (e.ctrlKey && !code.startsWith('Control'))
    || (e.altKey && !code.startsWith('Alt'))
    || e.metaKey
  return !mod
}
