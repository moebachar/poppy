// KIOSK.md §3 — the grid: the twin on the left, the column on the right.
import Chat from './Chat'
import Controls from './Controls'
import Header, { Logo } from './Header'
import Stage from './Stage'

export default function KioskApp() {
  return (
    <div className="kiosk">
      <section className="stage">
        <Stage />
        <div className="stage-logo">
          <Logo />
        </div>
        <div className="stage-hint">
          Molette pour le faire tourner · double-clic pour le remettre de face
        </div>
      </section>
      <aside className="column">
        <Header />
        <Chat />
        <Controls />
      </aside>
    </div>
  )
}
