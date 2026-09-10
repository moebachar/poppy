// Raw motor degrees -> model joint angle, per CONTRACT.md §4.
//   modelAngleRad = sign * wrap180(rawDeg - offset) * PI/180
// offsets = the robot's recorded stand pose (scripts/motion/poses/stand.json):
// this 2013 unit has stale factory zeros, so the stand is our model zero.
// signs = pypot orientation (poppy_torso.json config) x URDF joint-axis sign,
// so directions follow the official Poppy model; tune here if a joint
// mirrors when watched against the real robot.
export const CAL: Record<
  number,
  { node: string; axis: 'x' | 'y' | 'z'; sign: 1 | -1; offset: number }
> = {
  // signs verified live against the hardware (2026-08-19): only the two
  // vertical-axis joints (33 abs_z, 36 head_z) kept the derived sense —
  // every other joint reads mirrored, hence the flips.
  33: { node: 'absZ',       axis: 'y', sign:  1, offset: -161.93 },
  34: { node: 'bustY',      axis: 'x', sign: -1, offset:   89.63 },
  35: { node: 'bustX',      axis: 'z', sign: -1, offset:   -1.27 },  // live-verified
  36: { node: 'headZ',      axis: 'y', sign:  1, offset:   -1.03 },
  37: { node: 'headY',      axis: 'x', sign: -1, offset:  -33.87 },
  41: { node: 'lShoulderY', axis: 'x', sign:  1, offset: -108.44 },  // live-verified
  42: { node: 'lShoulderX', axis: 'z', sign:  1, offset:  178.07 },
  43: { node: 'lArmZ',      axis: 'y', sign:  1, offset:   -6.11 },
  44: { node: 'lElbowY',    axis: 'x', sign:  1, offset: -161.19 },  // live-verified
  51: { node: 'rShoulderY', axis: 'x', sign: -1, offset:   75.74 },
  52: { node: 'rShoulderX', axis: 'z', sign: -1, offset:   20.70 },
  53: { node: 'rArmZ',      axis: 'y', sign:  1, offset:  -77.14 },
  54: { node: 'rElbowY',    axis: 'x', sign: -1, offset: -129.80 },  // new motor 2026-09-09
};

export const MOTOR_IDS = Object.keys(CAL).map(Number);
