import * as THREE from 'three';

export type FigureKind = 'warrior' | 'knight' | 'archer';

/** Personnage low-poly (≈ 4 u de haut, volontairement grand pour rester lisible depuis la vue orbitale). */
export interface Figure {
  group: THREE.Group;
  kind: FigureKind;
  legs: [THREE.Object3D, THREE.Object3D];
  arm: THREE.Object3D;
  alive: boolean;
}

const mats = new Map<string, THREE.MeshStandardMaterial>();
function mat(color: string, extra: THREE.MeshStandardMaterialParameters = {}) {
  const key = color + JSON.stringify(extra);
  let m = mats.get(key);
  if (!m) {
    m = new THREE.MeshStandardMaterial({ color, roughness: 0.8, flatShading: true, ...extra });
    mats.set(key, m);
  }
  return m;
}

const SKIN = '#e7b98f';
const STEEL = '#b9c3cc';

function box(w: number, h: number, d: number, color: string): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(color));
  m.castShadow = true;
  return m;
}

export function makeFigure(kind: FigureKind): Figure {
  const g = new THREE.Group();
  const isWarrior = kind === 'warrior';
  const tunic = isWarrior ? '#7a2e24' : kind === 'knight' ? '#2d4f9e' : '#4c6b3a';
  const trousers = isWarrior ? '#3b2a22' : '#2b2f3a';

  // jambes (pivot à la hanche)
  const legs: THREE.Object3D[] = [];
  for (const side of [-1, 1]) {
    const pivot = new THREE.Group();
    pivot.position.set(side * 0.3, 1.6, 0);
    const leg = box(0.5, 1.6, 0.5, trousers);
    leg.position.y = -0.8;
    pivot.add(leg);
    g.add(pivot);
    legs.push(pivot);
  }
  const torso = box(1.3, 1.6, 0.8, tunic);
  torso.position.y = 2.4;
  g.add(torso);
  if (kind === 'knight') {
    const cross = box(0.3, 1.1, 0.1, '#f2f2f2');
    cross.position.set(0, 2.45, 0.45);
    g.add(cross);
    const bar = box(0.9, 0.3, 0.1, '#f2f2f2');
    bar.position.set(0, 2.6, 0.45);
    g.add(bar);
  }
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.48, 7, 6), mat(SKIN));
  head.position.y = 3.65;
  head.castShadow = true;
  g.add(head);
  // casque
  if (isWarrior) {
    const helm = new THREE.Mesh(new THREE.ConeGeometry(0.52, 0.9, 6), mat('#4a4a4f'));
    helm.position.y = 4.15;
    g.add(helm);
    const horn = new THREE.Mesh(new THREE.ConeGeometry(0.12, 0.6, 5), mat('#d9d2c2'));
    horn.position.set(0.45, 4.1, 0);
    horn.rotation.z = -0.9;
    g.add(horn);
    const horn2 = horn.clone();
    horn2.position.x = -0.45;
    horn2.rotation.z = 0.9;
    g.add(horn2);
  } else {
    const helm = new THREE.Mesh(new THREE.CylinderGeometry(0.52, 0.55, 0.7, 8), mat(STEEL));
    helm.position.y = 3.95;
    g.add(helm);
    if (kind === 'knight') {
      const plume = box(0.12, 0.6, 0.5, '#e0433c');
      plume.position.y = 4.5;
      g.add(plume);
    }
  }
  // bras droit (pivot à l'épaule) portant l'arme
  const arm = new THREE.Group();
  arm.position.set(0.85, 3.05, 0);
  const upper = box(0.4, 1.3, 0.4, isWarrior ? SKIN : STEEL);
  upper.position.y = -0.6;
  arm.add(upper);
  if (kind === 'archer') {
    const bow = new THREE.Mesh(new THREE.TorusGeometry(0.9, 0.06, 5, 10, Math.PI), mat('#6e4e33'));
    bow.position.set(0.2, -1.1, 0.3);
    bow.rotation.y = Math.PI / 2;
    bow.rotation.z = -Math.PI / 2;
    arm.add(bow);
  } else {
    const blade = box(0.14, isWarrior ? 1.4 : 1.7, 0.14, isWarrior ? '#8a8a8a' : STEEL);
    blade.position.y = isWarrior ? -1.9 : -2.1;
    arm.add(blade);
    if (isWarrior) {
      const axe = box(0.7, 0.5, 0.12, '#8a8a8a');
      axe.position.set(0.3, -2.4, 0);
      arm.add(axe);
    }
  }
  arm.rotation.x = -0.4;
  g.add(arm);
  // bras gauche + bouclier
  const left = box(0.4, 1.3, 0.4, isWarrior ? SKIN : STEEL);
  left.position.set(-0.85, 2.45, 0);
  g.add(left);
  if (kind !== 'archer') {
    const shield = isWarrior
      ? new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.75, 0.15, 8), mat('#b5443a'))
      : box(1, 1.3, 0.15, '#2d4f9e');
    if (isWarrior) shield.rotation.x = Math.PI / 2;
    shield.position.set(-1.05, 2.4, 0.45);
    shield.castShadow = true;
    g.add(shield);
    if (!isWarrior) {
      const emblem = box(0.3, 0.8, 0.05, '#f2f2f2');
      emblem.position.set(-1.05, 2.4, 0.55);
      g.add(emblem);
    }
  }
  g.scale.setScalar(1.3);
  return { group: g, kind, legs: [legs[0], legs[1]], arm, alive: true };
}

/** Pose de marche : balancement des jambes et léger rebond. */
export function walkPose(f: Figure, phase: number, amplitude = 0.7) {
  f.legs[0].rotation.x = Math.sin(phase) * amplitude;
  f.legs[1].rotation.x = -Math.sin(phase) * amplitude;
  f.group.position.y += 0; // la hauteur de base est gérée par l'appelant
}

export function idlePose(f: Figure) {
  f.legs[0].rotation.x = 0;
  f.legs[1].rotation.x = 0;
}

/** Flèche (petit cylindre) orientée selon sa direction de vol. */
export function makeArrow(): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 1.6, 4), mat('#5a4330'));
  m.rotation.x = Math.PI / 2;
  const wrapper = new THREE.Mesh();
  wrapper.add(m);
  return wrapper;
}
