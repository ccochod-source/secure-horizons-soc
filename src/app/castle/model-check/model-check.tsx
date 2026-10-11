'use client';
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { useSearchParams } from 'next/navigation';
import { Castle, CastleLights } from '@/castle/Castle';
import { PALETTE } from '@/castle/params';

type ViewKey = 'top' | 'front' | 'back' | 'left' | 'right';

interface ViewDef {
  key: ViewKey;
  label: string;
  ref: string;
  aspect: number;
}

const VIEWS: ViewDef[] = [
  { key: 'top', label: 'top — dessus, nord en haut', ref: '/castle/top.jpg', aspect: 1 },
  { key: 'front', label: 'front — caméra au sud', ref: '/castle/front.jpg', aspect: 1456 / 1088 },
  { key: 'back', label: 'back — caméra au nord', ref: '/castle/back.jpg', aspect: 1456 / 1088 },
  { key: 'left', label: 'left — caméra à l’ouest (sud à droite)', ref: '/castle/left.jpg', aspect: 1456 / 1088 },
  { key: 'right', label: 'right — caméra à l’est (nord à droite)', ref: '/castle/right.jpg', aspect: 1456 / 1088 },
];

const DIRS: Record<Exclude<ViewKey, 'top'>, [number, number]> = { front: [0, 1], back: [0, -1], left: [-1, 0], right: [1, 0] };

/** Paramètres de cadrage, tous surchargeables par la query string (`?tilt=10&fov=12`). */
export interface CheckParams {
  tilt: number; // inclinaison de la vue de dessus vers le sud (degrés)
  topWidth: number; // largeur du cadre orthographique (u)
  topCz: number; // point visé en z (u)
  fov: number; // vues latérales
  dist: number;
  elev: number; // élévation de la caméra (degrés)
  cy: number; // hauteur du point visé (u)
  width: number; // largeur des vignettes (px)
  overlay: boolean;
  opacity: number;
}

const DEFAULTS: CheckParams = { tilt: 12, topWidth: 123, topCz: -1, fov: 12.6, dist: 420, elev: 7, cy: 24, width: 560, overlay: false, opacity: 0.5 };
/** Surcharges par vue (les références n'ont pas toutes la même élévation ni le même cadrage) ; `?elev_back=14` les remplace. */
const VIEW_DEFAULTS: Partial<Record<ViewKey, Partial<CheckParams>>> = {
  back: { elev: 12, cy: 19.5, fov: 12.4 },
  left: { elev: 8, fov: 13 },
  right: { elev: 8, cy: 22 },
};
const NUMERIC: (keyof CheckParams)[] = ['tilt', 'topWidth', 'topCz', 'fov', 'dist', 'elev', 'cy', 'width', 'opacity'];

function readNum(sp: URLSearchParams, key: string): number | undefined {
  const v = sp.get(key);
  const n = v === null ? NaN : Number(v);
  return Number.isFinite(n) ? n : undefined;
}

function parseParams(sp: URLSearchParams): CheckParams {
  const out = { ...DEFAULTS, overlay: sp.get('overlay') === '1' };
  for (const k of NUMERIC) {
    const n = readNum(sp, k);
    if (n !== undefined) (out as unknown as Record<string, number>)[k] = n;
  }
  return out;
}

function paramsForView(sp: URLSearchParams, base: CheckParams, view: ViewKey): CheckParams {
  const out: CheckParams = { ...base, ...VIEW_DEFAULTS[view] };
  for (const k of NUMERIC) {
    const n = readNum(sp, `${k}_${view}`);
    if (n !== undefined) (out as unknown as Record<string, number>)[k] = n;
  }
  return out;
}

function Rig({ view, p }: { view: ViewDef; p: CheckParams }) {
  const { camera, size, invalidate } = useThree();
  useLayoutEffect(() => {
    if (view.key === 'top') {
      const cam = camera as THREE.OrthographicCamera;
      const halfW = p.topWidth / 2;
      const halfH = halfW * (size.height / size.width);
      cam.left = -halfW;
      cam.right = halfW;
      cam.top = halfH;
      cam.bottom = -halfH;
      cam.near = 1;
      cam.far = 2000;
      cam.zoom = 1;
      const t = THREE.MathUtils.degToRad(p.tilt);
      cam.position.set(0, 600 * Math.cos(t), p.topCz + 600 * Math.sin(t));
      cam.up.set(0, 0, -1);
      cam.lookAt(0, 0, p.topCz);
    } else {
      const cam = camera as THREE.PerspectiveCamera;
      const [dx, dz] = DIRS[view.key];
      const e = THREE.MathUtils.degToRad(p.elev);
      cam.fov = p.fov;
      cam.aspect = size.width / size.height;
      cam.near = 1;
      cam.far = 3000;
      cam.position.set(dx * p.dist * Math.cos(e), p.cy + p.dist * Math.sin(e), dz * p.dist * Math.cos(e));
      cam.up.set(0, 1, 0);
      cam.lookAt(0, p.cy, 0);
    }
    camera.updateProjectionMatrix();
    invalidate();
  }, [view, p, camera, size, invalidate]);
  return null;
}

function Ready({ onReady }: { onReady: () => void }) {
  const done = useRef(false);
  useFrame(() => {
    if (!done.current) {
      done.current = true;
      onReady();
    }
  });
  return null;
}

function Panel({ view, p, onReady }: { view: ViewDef; p: CheckParams; onReady: () => void }) {
  const sp = useSearchParams();
  const pv = useMemo(() => paramsForView(sp, p, view.key), [sp, p, view.key]);
  const w = p.width;
  const h = Math.round(w / view.aspect);
  const [ready, setReady] = useState(false);
  const ready1 = useCallback(() => {
    setReady(true);
    onReady();
  }, [onReady]);
  return (
    <section data-view={view.key} data-ready={ready ? '1' : '0'} style={{ marginBottom: 22 }}>
      <h2 style={{ fontSize: 14, margin: '0 0 6px', color: '#333' }}>
        {view.label}{' '}
        <span style={{ color: '#888', fontWeight: 400 }}>
          {view.key === 'top' ? `tilt=${pv.tilt} topWidth=${pv.topWidth} topCz=${pv.topCz}` : `fov=${pv.fov} dist=${pv.dist} elev=${pv.elev} cy=${pv.cy}`}
        </span>
      </h2>
      <figure style={{ position: 'relative', display: 'flex', gap: 12, margin: 0, width: p.overlay ? w : 2 * w + 12 }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={view.ref} alt={view.label} width={w} height={h} style={{ display: 'block', width: w, height: h }} />
        <div style={p.overlay ? { position: 'absolute', inset: 0, width: w, height: h, opacity: p.opacity } : { width: w, height: h }}>
          <Canvas
            orthographic={view.key === 'top'}
            camera={{ manual: true }}
            frameloop="demand"
            shadows
            dpr={[1, 2]}
            gl={{ preserveDrawingBuffer: true, antialias: true, toneMapping: THREE.NoToneMapping }}
            style={{ width: w, height: h }}
          >
            <color attach="background" args={[PALETTE.background]} />
            <CastleLights />
            <Castle />
            <Rig view={view} p={pv} />
            <Ready onReady={ready1} />
          </Canvas>
        </div>
      </figure>
    </section>
  );
}

/** Page de contrôle : chaque image de référence à côté du rendu du modèle sous le même angle. */
export function ModelCheck() {
  const sp = useSearchParams();
  const p = useMemo(() => parseParams(sp), [sp]);
  const [readyCount, setReadyCount] = useState(0);
  const onReady = useCallback(() => setReadyCount((c) => c + 1), []);
  const toggle = new URLSearchParams(sp.toString());
  toggle.set('overlay', p.overlay ? '0' : '1');
  return (
    <main data-ready-count={readyCount} style={{ padding: '16px 20px', background: '#f4f3ef', minHeight: '100vh', maxWidth: 'none' }}>
      <header style={{ marginBottom: 14 }}>
        <h1 style={{ fontSize: 20 }}>Château — vérification des vues</h1>
        <p style={{ color: '#666', fontSize: 13, marginTop: 4 }}>
          Référence à gauche, rendu à droite. Paramètres globaux (surcharge par vue : <code>elev_back=12</code>) ·{' '}
          <a href={`?${toggle.toString()}`}>{p.overlay ? 'côte à côte' : 'superposer'}</a> · rendus prêts : {readyCount}/5
        </p>
      </header>
      {VIEWS.map((v) => (
        <Panel key={v.key} view={v} p={p} onReady={onReady} />
      ))}
    </main>
  );
}
