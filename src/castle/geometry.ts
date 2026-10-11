import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const geoCache = new Map<string, THREE.BufferGeometry>();
function cached<T extends THREE.BufferGeometry>(key: string, make: () => T): T {
  let g = geoCache.get(key) as T | undefined;
  if (!g) {
    g = make();
    geoCache.set(key, g);
  }
  return g;
}

/** Contour en plein cintre : rectangle surmonté d'un demi-cercle, base en y = 0, centré en x. */
export function archShape(width: number, height: number): THREE.Shape {
  const r = width / 2;
  const spring = Math.max(0, height - r);
  const s = new THREE.Shape();
  s.moveTo(-r, 0);
  s.lineTo(r, 0);
  s.lineTo(r, spring);
  s.absarc(0, spring, r, 0, Math.PI, false);
  s.lineTo(-r, 0);
  return s;
}

/** Plaque en arche (fenêtres, portes) extrudée sur `depth` le long de +z. */
export function archGeometry(width: number, height: number, depth: number): THREE.ExtrudeGeometry {
  return cached(`arch:${width}:${height}:${depth}`, () => {
    const g = new THREE.ExtrudeGeometry(archShape(width, height), { depth, bevelEnabled: false });
    g.translate(0, 0, -depth / 2);
    return g;
  });
}

/**
 * Bloc au-dessus d'une ouverture en arche : remplit la zone entre la ligne d'imposte
 * et `top`, en épargnant le demi-cercle. Base du passage en y = 0.
 */
export function spandrelGeometry(width: number, archHeight: number, top: number, depth: number): THREE.ExtrudeGeometry {
  return cached(`spandrel:${width}:${archHeight}:${top}:${depth}`, () => {
    const r = width / 2;
    const spring = archHeight - r;
    const s = new THREE.Shape();
    s.moveTo(-r, spring);
    s.lineTo(-r, top);
    s.lineTo(r, top);
    s.lineTo(r, spring);
    s.absarc(0, spring, r, 0, Math.PI, false);
    const g = new THREE.ExtrudeGeometry(s, { depth, bevelEnabled: false });
    g.translate(0, 0, -depth / 2);
    return g;
  });
}

export interface MerlonSpec { width: number; gap: number; height: number; thickness?: number }

/** Rangée de merlons le long de x, centrée, base en y = 0, épaisseur selon z. */
export function merlonRowGeometry(length: number, m: MerlonSpec, thickness = m.thickness ?? 1): THREE.BufferGeometry {
  return cached(`merlonRow:${length}:${m.width}:${m.gap}:${m.height}:${thickness}`, () => {
    const pitch = m.width + m.gap;
    const count = Math.max(1, Math.floor((length + m.gap) / pitch));
    const span = count * pitch - m.gap;
    const parts: THREE.BufferGeometry[] = [];
    for (let i = 0; i < count; i++) {
      const b = new THREE.BoxGeometry(m.width, m.height, thickness);
      b.translate(-span / 2 + m.width / 2 + i * pitch, m.height / 2, 0);
      parts.push(b);
    }
    return mergeGeometries(parts, false)!;
  });
}

/** Couronne de merlons sur un cercle, base en y = 0, orientés vers l'extérieur. */
export function merlonRingGeometry(radius: number, count: number, width: number, height: number, thickness: number): THREE.BufferGeometry {
  return cached(`merlonRing:${radius}:${count}:${width}:${height}:${thickness}`, () => {
    const parts: THREE.BufferGeometry[] = [];
    for (let i = 0; i < count; i++) {
      const a = (i / count) * Math.PI * 2;
      const b = new THREE.BoxGeometry(width, height, thickness);
      b.translate(0, height / 2, radius - thickness / 2);
      b.rotateY(a);
      parts.push(b);
    }
    return mergeGeometries(parts, false)!;
  });
}

/** Parapet rectangulaire (4 murets) autour d'un rectangle w × d, base en y = 0. */
export function rectParapetGeometry(w: number, d: number, thickness: number, height: number): THREE.BufferGeometry {
  return cached(`parapet:${w}:${d}:${thickness}:${height}`, () => {
    const parts: THREE.BufferGeometry[] = [];
    const zs = new THREE.BoxGeometry(w, height, thickness);
    zs.translate(0, height / 2, d / 2 - thickness / 2);
    parts.push(zs, zs.clone().translate(0, 0, -(d - thickness)));
    const xs = new THREE.BoxGeometry(thickness, height, d - 2 * thickness);
    xs.translate(w / 2 - thickness / 2, height / 2, 0);
    parts.push(xs, xs.clone().translate(-(w - thickness), 0, 0));
    return mergeGeometries(parts, false)!;
  });
}

/** Merlons sur les 4 côtés d'un rectangle w × d, base en y = 0. */
export function rectMerlonsGeometry(w: number, d: number, m: MerlonSpec, thickness: number): THREE.BufferGeometry {
  return cached(`rectMerlons:${w}:${d}:${m.width}:${m.gap}:${m.height}:${thickness}`, () => {
    const parts: THREE.BufferGeometry[] = [];
    const corner = thickness + 0.4;
    const rowZ = merlonRowGeometry(w - 2 * corner - 0.4, m, thickness);
    parts.push(rowZ.clone().translate(0, 0, d / 2 - thickness / 2), rowZ.clone().translate(0, 0, -(d / 2 - thickness / 2)));
    const rowX = merlonRowGeometry(d - 2 * corner - 0.4, m, thickness);
    rowX.rotateY(Math.PI / 2);
    parts.push(rowX.clone().translate(w / 2 - thickness / 2, 0, 0), rowX.clone().translate(-(w / 2 - thickness / 2), 0, 0));
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      const c = new THREE.BoxGeometry(corner, m.height, corner);
      c.translate(sx * (w / 2 - corner / 2), m.height / 2, sz * (d / 2 - corner / 2));
      parts.push(c);
    }
    return mergeGeometries(parts, false)!;
  });
}

/** Toit pyramidal à base carrée alignée sur les axes, base en y = 0. */
export function pyramidGeometry(side: number, height: number): THREE.BufferGeometry {
  return cached(`pyramid:${side}:${height}`, () => {
    const g = new THREE.ConeGeometry(side / Math.SQRT2, height, 4, 1);
    g.rotateY(Math.PI / 4);
    g.translate(0, height / 2, 0);
    return g;
  });
}

/** Dôme en bulbe aplati (profil tourné), base en y = 0. */
export function domeGeometry(radius: number, height: number, segments: number): THREE.LatheGeometry {
  return cached(`dome:${radius}:${height}:${segments}`, () => {
    const profile = [
      [1, 0], [0.98, 0.3], [0.9, 0.58], [0.74, 0.8], [0.5, 0.93], [0.24, 0.99], [0, 1],
    ].map(([r, y]) => new THREE.Vector2(r * radius, y * height));
    return new THREE.LatheGeometry(profile, segments);
  });
}

/** Pignon triangulaire (profil d'un toit à deux pans) extrudé sur `depth` le long de +z, centré. */
export function gableGeometry(width: number, rise: number, depth: number): THREE.ExtrudeGeometry {
  return cached(`gable:${width}:${rise}:${depth}`, () => {
    const s = new THREE.Shape();
    s.moveTo(-width / 2, 0);
    s.lineTo(width / 2, 0);
    s.lineTo(0, rise);
    s.lineTo(-width / 2, 0);
    const g = new THREE.ExtrudeGeometry(s, { depth, bevelEnabled: false });
    g.translate(0, 0, -depth / 2);
    return g;
  });
}

/** Grille de herse (barreaux verticaux + horizontaux fusionnés), centrée en x, base en y = 0, dans le plan xy. */
export function portcullisGeometry(width: number, height: number, bars = 6, rows = 5, r = 0.14): THREE.BufferGeometry {
  return cached(`portcullis:${width}:${height}:${bars}:${rows}`, () => {
    const parts: THREE.BufferGeometry[] = [];
    for (let i = 0; i < bars; i++) {
      const b = new THREE.CylinderGeometry(r, r, height, 6);
      b.translate(-width / 2 + (i / (bars - 1)) * width, height / 2, 0);
      parts.push(b);
    }
    for (let j = 0; j < rows; j++) {
      const b = new THREE.CylinderGeometry(r, r, width, 6);
      b.rotateZ(Math.PI / 2);
      b.translate(0, (j / (rows - 1)) * (height - 0.3) + 0.15, 0);
      parts.push(b);
    }
    return mergeGeometries(parts, false)!;
  });
}

/** Drapeau légèrement ondulé (plan déformé), attaché au mât en x = 0, flottant vers +x. */
export function flagGeometry(width: number, height: number): THREE.PlaneGeometry {
  return cached(`flag:${width}:${height}`, () => {
    const g = new THREE.PlaneGeometry(width, height, 12, 3);
    g.translate(width / 2, 0, 0);
    const pos = g.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      pos.setZ(i, Math.sin((x / width) * Math.PI * 2) * 0.25 * (x / width));
    }
    g.computeVertexNormals();
    return g;
  });
}
