// Shared hologram materials + procedural sprite textures.
import * as THREE from 'three';

export const PALETTE = {
  fill: 0x79c4ff,    // additive body fill
  edge: 0x9fd8ff,    // structure lines
  ok: 0x43ff9e,      // healthy motor
  fault: 0xff4b3b,   // dead motor / errors
  warn: 0xffb03a,    // teach-picked marker
  ring: 0xffffff,    // hover ring
  gridCenter: 0x4fc3ff,
  gridLine: 0x2e4152,
} as const;

/** The three-layer hologram recipe: additive fill, edge lines, back-face rim. */
export interface SharedMats {
  fill: THREE.MeshBasicMaterial;
  fillZ: THREE.MeshBasicMaterial; // contours along local z (the base link is z-up)
  edge: THREE.LineBasicMaterial;
  rim: THREE.MeshBasicMaterial;
  accent: THREE.MeshBasicMaterial; // brighter bits (camera-eye ring)
}

/**
 * Sci-fi hologram contour rings: bright slice lines wrapping each printed
 * part, cut in the mesh's OWN frame (axis = the part's long axis) so the
 * rings ride along when a limb moves. One ring every 8 mm of part.
 */
function contourize(mat: THREE.MeshBasicMaterial, axis: 'y' | 'z'): THREE.MeshBasicMaterial {
  mat.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vObjPos;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvObjPos = position;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vObjPos;')
      .replace(
        'vec4 diffuseColor = vec4( diffuse, opacity );',
        `vec4 diffuseColor = vec4( diffuse, opacity );
        {
          float c = vObjPos.${axis} * 80.0;
          float d = abs(fract(c + 0.5) - 0.5);
          float w = max(fwidth(c) * 0.9, 0.04);
          float line = 1.0 - smoothstep(w, w * 2.2, d);
          diffuseColor.a += opacity * 1.1 * line;
        }`,
      );
  };
  return mat;
}

export function makeSharedMats(): SharedMats {
  const fillOpts = {
    color: PALETTE.fill,
    blending: THREE.AdditiveBlending,
    transparent: true,
    opacity: 0.10,
    depthWrite: false,
  } as const;
  const fill = contourize(new THREE.MeshBasicMaterial(fillOpts), 'y');
  const fillZ = contourize(new THREE.MeshBasicMaterial(fillOpts), 'z');
  const edge = new THREE.LineBasicMaterial({
    color: PALETTE.edge,
    blending: THREE.AdditiveBlending,
    transparent: true,
    opacity: 0.45,
    depthWrite: false,
  });
  const rim = new THREE.MeshBasicMaterial({
    color: PALETTE.fill,
    blending: THREE.AdditiveBlending,
    transparent: true,
    opacity: 0.06,
    depthWrite: false,
    side: THREE.BackSide,
  });
  const accent = new THREE.MeshBasicMaterial({
    color: PALETTE.edge,
    blending: THREE.AdditiveBlending,
    transparent: true,
    opacity: 0.5,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  return { fill, fillZ, edge, rim, accent };
}

export function disposeSharedMats(m: SharedMats): void {
  m.fill.dispose();
  m.fillZ.dispose();
  m.edge.dispose();
  m.rim.dispose();
  m.accent.dispose();
}

function canvasTexture(size: number, draw: (ctx: CanvasRenderingContext2D, s: number) => void): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const ctx = c.getContext('2d');
  if (ctx) draw(ctx, size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** Soft radial glow for marker sprites. */
export function makeGlowTexture(): THREE.CanvasTexture {
  return canvasTexture(64, (ctx, s) => {
    const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    g.addColorStop(0, 'rgba(255,255,255,1)');
    g.addColorStop(0.28, 'rgba(255,255,255,0.45)');
    g.addColorStop(0.65, 'rgba(255,255,255,0.10)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, s, s);
  });
}

/** Thin circle for hover / picked rings (billboarded as a sprite). */
export function makeRingTexture(): THREE.CanvasTexture {
  return canvasTexture(64, (ctx, s) => {
    ctx.strokeStyle = 'rgba(255,255,255,1)';
    ctx.lineWidth = s * 0.06;
    ctx.beginPath();
    ctx.arc(s / 2, s / 2, s * 0.36, 0, Math.PI * 2);
    ctx.stroke();
  });
}

/** Horizontal soft band, swept vertically over the body while dormant. */
export function makeBandTexture(): THREE.CanvasTexture {
  return canvasTexture(64, (ctx, s) => {
    const g = ctx.createLinearGradient(0, 0, 0, s);
    g.addColorStop(0, 'rgba(255,255,255,0)');
    g.addColorStop(0.5, 'rgba(255,255,255,1)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, s, s);
  });
}
