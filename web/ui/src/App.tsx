import CommandDeck from './ui/CommandDeck'
import EventLog from './ui/EventLog'
import HoloStage from './ui/HoloStage'
import MotorRegister from './ui/MotorRegister'
import Sequences from './ui/Sequences'
import TeachPanel from './ui/TeachPanel'
import TopBar from './ui/TopBar'

export default function App() {
  return (
    <div className="app">
      <TopBar />
      <MotorRegister />
      <aside className="side">
        <Sequences />
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
