// The real Poppy Torso — meshes and kinematics taken directly from the
// official URDF (poppy-project/poppy-torso: software/poppy_torso/poppy_torso.urdf).
// Each entry in LINKS is one URDF joint: the rotating child frame ("node",
// what CAL drives) positioned by the joint's exact origin xyz / rpy, carrying
// the child link's visual STL. URDF frames are Z-up meters; a container
// converts to the Y-up stage and scales to stage units.
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { CAL } from './calibration';
import { MotorMarker } from './markers';
import { makeGlowTexture, makeRingTexture } from './materials';
import type { SharedMats } from './materials';

export interface RobotRig {
  root: THREE.Group;
  nodes: Record<string, THREE.Group>;
  markers: Map<number, MotorMarker>;
  proxies: THREE.Object3D[];
  /** Hide the printed parts at & below these joints (dead motors can't move them). */
  applyDeadParts(nodeNames: string[]): void;
  dispose(): void;
}

const ROOT_SCALE = 1.9;          // URDF meters -> stage units
const FLOAT_Y = 0.0;             // grounded: the base sits on the grid floor
const MESH_BASE = '/meshes/';    // served from web/ui/public/meshes

type Vec3 = [number, number, number];

// node, visual mesh of the child link, parent node (null = base frame),
// joint origin xyz (m), joint origin rpy (rad) — verbatim from the URDF.
const LINKS: Array<[string, string, string | null, Vec3, Vec3]> = [
  ['absZ',       'spine_visual.STL',            null,         [0, 0, 0.08965],          [1.5708, 0, 0.018388]],
  ['bustY',      'bust_motors_visual.STL',      'absZ',       [0, 0.07985, 0.0028],     [0, 0, 0]],
  ['bustX',      'chest_visual.STL',            'bustY',      [0, 0, 0],                [0, 0, 0]],
  ['headZ',      'neck_visual.STL',             'bustX',      [0, 0.084, 0.005],        [0, 0, 0]],
  ['headY',      'head_visual.STL',             'headZ',      [0, 0.02, 0],             [-0.349066, 0, 0]],
  ['lShoulderY', 'l_shoulder_visual.STL',       'bustX',      [0.0771, 0.05, 0.004],    [-1.570796, 0, 0]],
  ['lShoulderX', 'l_shoulder_motor_visual.STL', 'lShoulderY', [0.0284, 0, 0],           [3.141593, 0, 1.570796]],
  ['lArmZ',      'l_upper_arm_visual.STL',      'lShoulderX', [0, 0.03625, 0.0185],     [0, 0, 0]],
  ['lElbowY',    'l_forearm_visual.STL',        'lArmZ',      [0, 0.11175, -0.01],      [0, 0, 0]],
  ['rShoulderY', 'r_shoulder_visual.STL',       'bustX',      [-0.0771, 0.05, 0.004],   [-1.570796, 0, 0]],
  ['rShoulderX', 'r_shoulder_motor_visual.STL', 'rShoulderY', [-0.0284, 0, 0],          [3.141593, 0, -1.570796]],
  ['rArmZ',      'r_upper_arm_visual.STL',      'rShoulderX', [0, 0.03625, 0.0185],     [0, 0, 0]],
  ['rElbowY',    'r_forearm_visual.STL',        'rArmZ',      [0, 0.11175, -0.01],      [0, 0, 0]],
];

// Marker offsets inside the joint's frame (meters). Motors sit at their
// joints on Poppy; only bust_x needs a nudge (it shares bust_y's origin).
const MARKER_POS: Record<number, Vec3> = {
  35: [0, 0.035, -0.005],
};

// The URDF's zero pose is a T-pose; the robot's model-zero (its stand) hangs
// the arms — in this URDF that is a shoulder-Y twist followed by the
// shoulder-X drop. Baked as static rotations between joint origin and rotor
// so the module's joint values stay zero-at-stand.
const NEUTRAL: Record<string, { axis: 'x' | 'y' | 'z'; rad: number }> = {
  // level the gaze: the neck mounts the head 20 deg back; the real stand
  // holds it looking straight ahead
  headY: { axis: 'x', rad: 0.33 },
  lShoulderY: { axis: 'x', rad: Math.PI / 2 },
  lShoulderX: { axis: 'z', rad: Math.PI / 2 },
  rShoulderY: { axis: 'x', rad: Math.PI / 2 },
  rShoulderX: { axis: 'z', rad: -Math.PI / 2 },
  // the robot's stand holds the forearms ~90 deg forward of the biceps
  // (probe-verified: both world yDir ≈ +Z)
  lElbowY: { axis: 'x', rad: -Math.PI / 2 },
  rElbowY: { axis: 'x', rad: -Math.PI / 2 },
};

export function buildRobot(mats: SharedMats): RobotRig {
  const root = new THREE.Group();
  // no yaw: verified live-on-hardware — URDF front already faces the camera

  // Z-up URDF world -> Y-up stage; floated so the hanging hands clear the grid
  const zup = new THREE.Group();
  zup.rotation.x = -Math.PI / 2;
  zup.scale.setScalar(ROOT_SCALE);
  zup.position.y = FLOAT_Y;
  root.add(zup);

  const geoms: THREE.BufferGeometry[] = [];
  let dead = false;

  let deadNodes: string[] = [];
  const loader = new STLLoader();
  const addMesh = (parent: THREE.Object3D, file: string,
                   fill: THREE.Material = mats.fill) => {
    loader.load(MESH_BASE + file, (geom) => {
      if (dead) {
        geom.dispose();
        return;
      }
      geoms.push(geom);
      const m = new THREE.Mesh(geom, fill);
      m.userData.bodyPart = true;
      parent.add(m);
      const rim = new THREE.Mesh(geom, mats.rim);
      rim.scale.setScalar(1.02);
      rim.userData.bodyPart = true;
      parent.add(rim);
      applyDeadParts(deadNodes);       // late-loading mesh honors current state
    });
  };

  // base link is z-up. No rotation: with the stand pose fixed at the root
  // (abs_z rotated 180 on 2026-08-19), the URDF base is correct as-is —
  // clamp lever at the back when the torso faces the viewer.
  const baseMount = new THREE.Group();
  zup.add(baseMount);
  addMesh(baseMount, 'base_visual.STL', mats.fillZ);

  const nodes: Record<string, THREE.Group> = {};
  for (const [name, mesh, parentName, xyz, rpy] of LINKS) {
    // static joint-origin frame (URDF rpy is extrinsic XYZ == intrinsic ZYX)
    const origin = new THREE.Group();
    origin.position.set(xyz[0], xyz[1], xyz[2]);
    origin.rotation.set(rpy[0], rpy[1], rpy[2], 'ZYX');
    (parentName ? nodes[parentName] : zup).add(origin);
    let mount: THREE.Object3D = origin;
    const neutral = NEUTRAL[name];
    if (neutral) {
      const n = new THREE.Group();
      n.rotation[neutral.axis] = neutral.rad;
      origin.add(n);
      mount = n;
    }
    // rotating child frame — CAL drives node.rotation[axis]
    const node = new THREE.Group();
    mount.add(node);
    nodes[name] = node;
    addMesh(node, mesh);
  }

  // ---- motor markers ------------------------------------------------------
  const glowTex = makeGlowTexture();
  const ringTex = makeRingTexture();
  const markers = new Map<number, MotorMarker>();
  const proxies: THREE.Object3D[] = [];
  for (const idStr of Object.keys(CAL)) {
    const id = Number(idStr);
    const marker = new MotorMarker(id, glowTex, ringTex);
    const pos = MARKER_POS[id] ?? [0, 0, 0];
    marker.group.position.set(pos[0], pos[1], pos[2]);
    marker.group.scale.setScalar(1 / ROOT_SCALE);   // undo the rig scale
    nodes[CAL[id].node].add(marker.group);
    markers.set(id, marker);
    proxies.push(marker.hitProxy);
  }

  const setBodyVisible = (obj: THREE.Object3D, on: boolean) => {
    obj.traverse((o) => {
      if (o.userData.bodyPart) o.visible = on;
    });
  };

  const applyDeadParts = (nodeNames: string[]) => {
    deadNodes = nodeNames;
    setBodyVisible(root, true);
    for (const name of nodeNames) {
      const node = nodes[name];
      if (node) setBodyVisible(node, false);
    }
  };

  const dispose = () => {
    dead = true;
    for (const m of markers.values()) m.dispose();
    for (const g of geoms) g.dispose();
    glowTex.dispose();
    ringTex.dispose();
  };

  return { root, nodes, markers, proxies, applyDeadParts, dispose };
}
