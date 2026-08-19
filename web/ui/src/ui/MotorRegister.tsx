import { useStore } from '../state'
import type { Motor } from '../types'
import { motorLabel } from '../types'

function tempClass(t: number): string {
  return t >= 50 ? 'fault' : t >= 45 ? 'warn' : ''
}

function Row({ motor }: { motor: Motor }) {
  const latestPos = useStore((s) => s.latestPos)
  const health = useStore((s) => s.health)
  const seenState = useStore((s) => s.seenState)
  const hovered = useStore((s) => s.hoveredMotor)
  const setHovered = useStore((s) => s.setHovered)

  const id = motor.id
  const live = health.motors[String(id)]
  const pos = latestPos[String(id)] ?? motor.pos
  const temp = live ? live.t : motor.temp
  const volt = live ? live.v : motor.volt

  const dead = seenState && !motor.present
  const idFault = seenState && motor.present && !motor.ok
  const hi = hovered === id

  return (
    <div
      className={`mrow${dead ? ' dead' : ''}${hi ? ' hi' : ''}`}
      onMouseEnter={() => setHovered(id, 'row')}
      onMouseLeave={() => setHovered(null, 'row')}
    >
      <div className="mrow-l1">
        <span
          className="mrow-id"
          style={idFault ? { color: 'var(--fault)' } : undefined}
        >
          {id}
        </span>
        <span className="mrow-name">{motorLabel(motor.name)}</span>
        {dead ? (
          <span className="mrow-faulttag">FAULT</span>
        ) : (
          <span className="mrow-pos">
            {pos === null ? '—' : pos.toFixed(1)}
            <span className="unit">°</span>
          </span>
        )}
      </div>
      <div className="mrow-l2">
        {dead ? (
          <span className="tickbar" />
        ) : (
          <>
            <span className="tickbar">
              <span
                className={`tickbar-fill ${temp === null ? '' : tempClass(temp)}`}
                style={{
                  width:
                    temp === null
                      ? '0%'
                      : `${Math.min(100, Math.max(0, (temp / 52) * 100))}%`,
                }}
              />
            </span>
            <span className={`mrow-temp ${temp === null ? '' : tempClass(temp)}`}>
              {temp === null ? '—' : `${temp}°`}
            </span>
            <span className="mrow-volt">
              {volt === null ? '—' : `${volt.toFixed(1)}V`}
            </span>
          </>
        )}
      </div>
    </div>
  )
}

export default function MotorRegister() {
  const motors = useStore((s) => s.motors)
  return (
    <section className="register">
      <div className="panel-label">MOTOR REGISTER</div>
      <div className="register-rows">
        {motors.map((m) => (
          <Row key={m.id} motor={m} />
        ))}
      </div>
    </section>
  )
}
