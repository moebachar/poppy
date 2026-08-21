import CommandDeck from './ui/CommandDeck'
import EventLog from './ui/EventLog'
import HoloStage from './ui/HoloStage'
import MotorRegister from './ui/MotorRegister'
import PeoplePanel from './ui/PeoplePanel'
import Sequences from './ui/Sequences'
import SideTabs from './ui/SideTabs'
import TeachPanel from './ui/TeachPanel'
import TopBar from './ui/TopBar'
import VoicePanel from './ui/VoicePanel'
import { useStore } from './state'

export default function App() {
  const sideTab = useStore((s) => s.sideTab)

  return (
    <div className="app">
      <TopBar />
      <MotorRegister />
      <aside className="side tabbed">
        <SideTabs />
        {sideTab === 'seq' && <Sequences />}
        {sideTab === 'voice' && <VoicePanel />}
        {sideTab === 'people' && <PeoplePanel />}
        <TeachPanel />
        <EventLog />
      </aside>
      <CommandDeck />
      <main className="stage">
        <HoloStage />
      </main>
    </div>
  )
}
