import AdminPage from './ui/AdminPage'
import CommandDeck from './ui/CommandDeck'
import EventLog from './ui/EventLog'
import HoloStage from './ui/HoloStage'
import MotorRegister from './ui/MotorRegister'
import Sequences from './ui/Sequences'
import SideTabs from './ui/SideTabs'
import TeachPanel from './ui/TeachPanel'
import TopBar from './ui/TopBar'
import VoicePanel from './ui/VoicePanel'
import { useStore } from './state'

export default function App() {
  const sideTab = useStore((s) => s.sideTab)
  const page = useStore((s) => s.page)
  const admin = page === 'admin'

  // The deck is never unmounted for the admin page (VOICE.md §5.4): the
  // hologram owns a WebGL context and a running awakening, and both are gone
  // for good if this tree is torn down. The admin page is opaque and covers
  // it; `inert` keeps the covered deck out of the focus order underneath.
  return (
    <>
      <div className="app" inert={admin}>
        <TopBar />
        <MotorRegister />
        <aside className="side tabbed">
          <SideTabs />
          {sideTab === 'seq' && <Sequences />}
          {sideTab === 'voice' && <VoicePanel />}
          <TeachPanel />
          <EventLog />
        </aside>
        <CommandDeck />
        <main className="stage">
          <HoloStage />
        </main>
      </div>
      {admin && <AdminPage />}
    </>
  )
}
