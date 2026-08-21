// The hand-drawn glyphs allowed by DESIGN.md — power arc, play triangle,
// stop square, record dot, camera, plus the level bars VOICE.md §4.2 adds
// for the voice key. currentColor everywhere.

interface IconProps {
  size?: number
}

function frame(size: number | undefined) {
  const s = size ?? 12
  return {
    width: s,
    height: s,
    viewBox: '0 0 12 12',
    'aria-hidden': true as const,
    focusable: false as const,
  }
}

export function IconPower({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M6 1.1 L6 5.2" stroke="currentColor" strokeWidth="1.4" fill="none" />
      <path
        d="M3.9 2.9 A4.3 4.3 0 1 0 8.1 2.9"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
      />
    </svg>
  )
}

export function IconPlay({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M3.2 1.9 L10.1 6 L3.2 10.1 Z" fill="currentColor" />
    </svg>
  )
}

export function IconStop({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M2.9 2.9 L9.1 2.9 L9.1 9.1 L2.9 9.1 Z" fill="currentColor" />
    </svg>
  )
}

export function IconRec({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M6 2.5 A3.5 3.5 0 1 0 6.01 2.5 Z" fill="currentColor" />
    </svg>
  )
}

/** Three level bars — the voice key. */
export function IconLevel({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path d="M2.5 6.6 L2.5 9.7" stroke="currentColor" strokeWidth="1.4" fill="none" />
      <path d="M6 2.3 L6 9.7" stroke="currentColor" strokeWidth="1.4" fill="none" />
      <path d="M9.5 4.8 L9.5 9.7" stroke="currentColor" strokeWidth="1.4" fill="none" />
    </svg>
  )
}

export function IconCam({ size }: IconProps) {
  return (
    <svg {...frame(size)}>
      <path
        d="M1.4 3.9 L4.4 3.9 L5.3 2.6 L6.9 2.6 L7.8 3.9 L10.6 3.9 L10.6 9.6 L1.4 9.6 Z"
        stroke="currentColor"
        strokeWidth="1.1"
        fill="none"
      />
      <path
        d="M6 5.1 A1.7 1.7 0 1 0 6.01 5.1 Z"
        stroke="currentColor"
        strokeWidth="1.1"
        fill="none"
      />
    </svg>
  )
}
