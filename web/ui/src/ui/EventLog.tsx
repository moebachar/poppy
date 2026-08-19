import { useStore } from '../state'

export default function EventLog() {
  const events = useStore((s) => s.events)
  return (
    <section className="eventlog">
      <div className="panel-label">EVENT LOG</div>
      <div className="ev-rows">
        {events.slice(0, 6).map((e, i) => (
          <div key={`${e.ts}-${e.line}-${i}`} className="evrow">
            <span className="ev-ts">{e.ts}</span>
            <span className="ev-line">{e.line}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
