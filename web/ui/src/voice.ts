// Hands-free stop word for teach mode: both hands are on the robot, so the
// take is ended by saying "stop" (or "arrête", "fini", "terminé").
// Chrome's SpeechRecognition — no key, no server, but it does need the net.

// Stems, matched anywhere in the phrase: the recogniser returns "stoppe",
// "stop.", "arrête !", "c'est fini" — near-misses must still stop the take.
const STEMS = [
  'stop', 'arret', 'arrêt', 'fini', 'termin', 'finish', 'sauve', 'save',
]

/** strip accents + punctuation so "arrête," matches "arret" */
function flatten(s: string): string {
  return s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')   // drop combining accents
    .replace(/[^a-z0-9\s]/g, ' ')
}

export function heardStopWord(transcript: string): boolean {
  const flat = flatten(transcript)
  return STEMS.some((stem) => flat.includes(flatten(stem)))
}

export type VoiceStatus = 'idle' | 'listening' | 'denied' | 'offline' | 'unsupported'

interface Recognizer {
  start(): void
  stop(): void
  abort(): void
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
}

function recognizerClass(): (new () => Recognizer) | null {
  const w = window as unknown as {
    SpeechRecognition?: new () => Recognizer
    webkitSpeechRecognition?: new () => Recognizer
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export function voiceSupported(): boolean {
  return recognizerClass() !== null
}

/** Ask for the mic up front — never while the operator's hands are busy. */
export async function primeMicPermission(): Promise<boolean> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    stream.getTracks().forEach((t) => t.stop())
    return true
  } catch {
    return false
  }
}

/**
 * Listen until the stop word is heard, then fire `onStop` once.
 * Returns a cancel function. `onStatus` reports what the mic is doing so the
 * panel can say so out loud rather than failing silently.
 */
export function listenForStop(
  onStop: () => void,
  onStatus: (s: VoiceStatus, heard?: string) => void,
  log: (line: string) => void = () => {},
): () => void {
  const Klass = recognizerClass()
  if (!Klass) {
    onStatus('unsupported')
    return () => {}
  }

  let cancelled = false
  let fired = false
  let lastSeen = ''
  const rec = new Klass()
  rec.lang = 'fr-FR'          // "stop" reads the same in both languages
  rec.continuous = true
  rec.interimResults = true   // act on the interim guess: ~0.5 s faster

  rec.onresult = (e) => {
    for (let i = 0; i < e.results.length; i++) {
      const text = e.results[i][0]?.transcript ?? ''
      if (!text) continue
      onStatus('listening', text.trim().slice(-40))
      if (fired) continue
      if (heardStopWord(text)) {
        fired = true
        cancelled = true
        log(`VOICE heard "${text.trim()}" — finishing`)
        try {
          rec.abort()
        } catch {
          /* already gone */
        }
        onStop()
        return
      }
      lastSeen = text.trim()
    }
  }

  rec.onerror = (e) => {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      cancelled = true
      onStatus('denied')
      log('VOICE mic blocked — allow the microphone for this page')
    } else if (e.error === 'network') {
      onStatus('offline')
      log('VOICE offline — speech recognition needs the network')
    }
    // 'no-speech' / 'aborted' are normal: onend restarts us
  }

  rec.onend = () => {
    if (cancelled) return
    try {
      rec.start()               // Chrome stops on silence — keep listening
    } catch {
      /* restarting too fast: the next onend will retry */
    }
  }

  try {
    rec.start()
    onStatus('listening')
  } catch {
    onStatus('idle')
  }

  return () => {
    cancelled = true
    if (!fired && lastSeen) log(`VOICE last heard "${lastSeen}" (no stop word)`)
    try {
      rec.abort()
    } catch {
      /* already gone */
    }
    onStatus('idle')
  }
}
