// Small easing / interpolation toolbox. No dependencies.

export function clamp01(t: number): number {
  return t < 0 ? 0 : t > 1 ? 1 : t;
}

export function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export function easeOutQuart(t: number): number {
  const u = 1 - clamp01(t);
  return 1 - u * u * u * u;
}

export function easeInOutCubic(t: number): number {
  t = clamp01(t);
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

/** CSS-style cubic-bezier(x1,y1,x2,y2) easing, solved with Newton + bisection. */
export function cubicBezier(x1: number, y1: number, x2: number, y2: number): (t: number) => number {
  const sx = (u: number) => 3 * x1 * u * (1 - u) * (1 - u) + 3 * x2 * u * u * (1 - u) + u * u * u;
  const sy = (u: number) => 3 * y1 * u * (1 - u) * (1 - u) + 3 * y2 * u * u * (1 - u) + u * u * u;
  const dx = (u: number) => 3 * x1 * (1 - u) * (1 - 3 * u) + 3 * x2 * u * (2 - 3 * u) + 3 * u * u;
  return (t: number) => {
    if (t <= 0) return 0;
    if (t >= 1) return 1;
    let u = t;
    for (let i = 0; i < 6; i++) {
      const err = sx(u) - t;
      if (Math.abs(err) < 1e-5) return sy(u);
      const d = dx(u);
      if (Math.abs(d) < 1e-6) break;
      u -= err / d;
      if (u < 0 || u > 1) break;
    }
    let lo = 0;
    let hi = 1;
    while (hi - lo > 1e-4) {
      u = (lo + hi) / 2;
      if (sx(u) < t) lo = u; else hi = u;
    }
    return sy((lo + hi) / 2);
  };
}

/** Per-value critically damped smoothing state. */
export interface DampState {
  v: number;
  vel: number;
}

/**
 * Critically damped spring step toward `target` (Game Programming Gems
 * SmoothDamp). `smoothTime` is roughly the time to close most of the gap.
 */
export function smoothDampTo(s: DampState, target: number, smoothTime: number, dt: number): void {
  const omega = 2 / Math.max(smoothTime, 1e-4);
  const x = omega * dt;
  const exp = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x);
  const change = s.v - target;
  const temp = (s.vel + omega * change) * dt;
  s.vel = (s.vel - omega * temp) * exp;
  s.v = target + (change + temp) * exp;
}
