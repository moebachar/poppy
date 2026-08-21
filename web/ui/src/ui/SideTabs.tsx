// The side column's tab strip. TEACH / RECORD and EVENT LOG stay pinned
// below whatever is selected here — they are always reachable.
import { useStore } from '../state'
import type { SideTab } from '../state'

const TABS: { id: SideTab; label: string }[] = [
  { id: 'seq', label: 'SEQUENCES' },
  { id: 'voice', label: 'VOICE' },
  { id: 'people', label: 'PEOPLE' },
]

export default function SideTabs() {
  const sideTab = useStore((s) => s.sideTab)
  const setSideTab = useStore((s) => s.setSideTab)
  const voice = useStore((s) => s.voice)

  const live = voice?.on === true
  const speaking = live && voice?.phase === 'speaking'

  return (
    <nav className="sidetabs">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          className={`sidetab${sideTab === t.id ? ' on' : ''}`}
          onClick={() => setSideTab(t.id)}
        >
          {t.label}
          {t.id === 'voice' && live && sideTab !== 'voice' && (
            <span className={`sidetab-dot${speaking ? ' pulse' : ''}`} />
          )}
        </button>
      ))}
    </nav>
  )
}
