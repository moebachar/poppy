// Motor markers: octahedron core + glow sprite + hover/picked rings.
// Healthy = --ok with a gentle pulse; dead = --fault with an irregular
// 4-7 Hz "dying neon" flicker; teach-picked = --warn.
import * as THREE from 'three';
import { PALETTE } from './materials';
import { lerp } from './easing';

export interface MarkerVisualState {
  ok: boolean;
  present: boolean;
  picked: boolean;
  extHover: boolean;
}

const COL_OK = new THREE.Color(PALETTE.ok);
const COL_FAULT = new THREE.Color(PALETTE.fault);
const COL_WARN = new THREE.Color(PALETTE.warn);

export class MotorMarker {
  readonly id: number;
  readonly group: THREE.Group;
  readonly hitProxy: THREE.Mesh;
  state: MarkerVisualState;

  private core: THREE.Mesh;
  private coreMat: THREE.MeshBasicMaterial;
  private glowMat: THREE.SpriteMaterial;
  private hoverMat: THREE.SpriteMaterial;
  private pickMat: THREE.SpriteMaterial;
  private coreGeom: THREE.OctahedronGeometry;
  private proxyGeom: THREE.SphereGeometry;
  private proxyMat: THREE.MeshBasicMaterial;
  private flickerLeft: number;
  private flickerVal: number;
  private pulsePhase: number;
  private hoverOp: number;
  private pickOp: number;

  constructor(id: number, glowTex: THREE.Texture, ringTex: THREE.Texture) {
    this.id = id;
    this.state = { ok: true, present: true, picked: false, extHover: false };
    this.flickerLeft = 0;
    this.flickerVal = 1;
    this.pulsePhase = (id * 2.399) % (Math.PI * 2);
    this.hoverOp = 0;
    this.pickOp = 0;

    this.group = new THREE.Group();

    this.coreGeom = new THREE.OctahedronGeometry(0.017);
    this.coreMat = new THREE.MeshBasicMaterial({
      color: COL_OK,
      transparent: true,
      opacity: 0.95,
      depthTest: false,
      depthWrite: false,
    });
    this.core = new THREE.Mesh(this.coreGeom, this.coreMat);
    this.core.renderOrder = 20;
    this.group.add(this.core);

    this.glowMat = new THREE.SpriteMaterial({
      map: glowTex,
      color: COL_OK,
      transparent: true,
      opacity: 0.5,
      depthTest: false,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const glow = new THREE.Sprite(this.glowMat);
    glow.scale.setScalar(0.085);
    glow.renderOrder = 18;
    this.group.add(glow);

    this.hoverMat = new THREE.SpriteMaterial({
      map: ringTex,
      color: PALETTE.ring,
      transparent: true,
      opacity: 0,
      depthTest: false,
      depthWrite: false,
    });
    const hoverRing = new THREE.Sprite(this.hoverMat);
    hoverRing.scale.setScalar(0.085);
    hoverRing.renderOrder = 22;
    this.group.add(hoverRing);

    this.pickMat = new THREE.SpriteMaterial({
      map: ringTex,
      color: COL_WARN,
      transparent: true,
      opacity: 0,
      depthTest: false,
      depthWrite: false,
    });
    const pickRing = new THREE.Sprite(this.pickMat);
    pickRing.scale.setScalar(0.11);
    pickRing.renderOrder = 22;
    this.group.add(pickRing);

    // Invisible-but-raycastable pick proxy (bigger than the octahedron).
    this.proxyGeom = new THREE.SphereGeometry(0.045, 8, 6);
    this.proxyMat = new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: false, depthTest: false });
    this.hitProxy = new THREE.Mesh(this.proxyGeom, this.proxyMat);
    this.hitProxy.userData.motorId = id;
    this.group.add(this.hitProxy);
  }

  /** `hovered` = raycast hover OR external row-hover OR setHighlight match. */
  update(dt: number, time: number, hovered: boolean, globalDim: number): void {
    const s = this.state;
    const dead = !s.present || !s.ok;

    const col = s.picked ? COL_WARN : dead ? COL_FAULT : COL_OK;
    this.coreMat.color.copy(col);
    this.glowMat.color.copy(col);

    let intensity: number;
    if (dead && !s.picked) {
      // Irregular flicker, 4-7 Hz, like a dying neon tube.
      this.flickerLeft -= dt;
      if (this.flickerLeft <= 0) {
        this.flickerLeft = 1 / 7 + Math.random() * (1 / 4 - 1 / 7);
        this.flickerVal = Math.random() < 0.35 ? 0.05 + Math.random() * 0.2 : 0.45 + Math.random() * 0.55;
      }
      intensity = this.flickerVal * (s.present ? 1 : 0.55);
    } else {
      // Gentle pulse on healthy / picked markers.
      intensity = 0.8 + 0.2 * Math.sin(time * 2 * Math.PI * 0.9 + this.pulsePhase);
    }

    this.coreMat.opacity = 0.95 * intensity * globalDim;
    this.glowMat.opacity = 0.5 * intensity * globalDim;
    this.core.rotation.y += dt * 0.8;

    const ease = 1 - Math.exp(-dt * 14);
    this.hoverOp = lerp(this.hoverOp, hovered ? 0.9 : 0, ease);
    this.pickOp = lerp(this.pickOp, s.picked ? 0.9 : 0, ease);
    this.hoverMat.opacity = this.hoverOp * globalDim;
    this.pickMat.opacity = this.pickOp * globalDim;
  }

  dispose(): void {
    this.coreGeom.dispose();
    this.proxyGeom.dispose();
    this.coreMat.dispose();
    this.glowMat.dispose();
    this.hoverMat.dispose();
    this.pickMat.dispose();
    this.proxyMat.dispose();
  }
}
