'use client';
import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { Castle, CastleLights, DEFAULT_TOWER_IDS } from './Castle';
import { CastleGlb } from './CastleGlb';
import { PALETTE } from './params';
import { downloadBlob, exportCastleGlb } from './export';
import { CastleAnimation } from './animation/CastleAnimation';
import type { CastleAnimator } from './animation/animator';

export type CastleSource = 'procedural' | 'glb';

export interface CastleSceneProps {
  source?: CastleSource;
  towerIds?: readonly string[];
  /** Reçoit l'animateur dès que le château est monté (null au démontage). */
  onAnimator?: (a: CastleAnimator | null) => void;
}

declare global {
  interface Window {
    /** Déclenche le téléchargement de castle.glb (utilisé par scripts/castle/export_glb.py). */
    __castleExport?: () => Promise<void>;
    /** Animateur courant, pour les scripts et la console. */
    __castle?: CastleAnimator | null;
  }
}

/** Signale que le sous-arbre (procédural ou GLB) est monté — rendu après la résolution du Suspense. */
function Mounted({ onMount }: { onMount: (v: boolean) => void }) {
  useEffect(() => {
    onMount(true);
    return () => onMount(false);
  }, [onMount]);
  return null;
}

/** Scène principale : vue orbitale du château, procédural ou chargé depuis castle.glb, avec animateur. */
export function CastleScene({ source = 'procedural', towerIds = DEFAULT_TOWER_IDS, onAnimator }: CastleSceneProps) {
  const rootRef = useRef<THREE.Group>(null);
  const [ready, setReady] = useState(false);
  const handleAnimator = useCallback(
    (a: CastleAnimator | null) => {
      window.__castle = a;
      onAnimator?.(a);
    },
    [onAnimator],
  );
  useEffect(() => {
    window.__castleExport = async () => {
      const castle = rootRef.current?.getObjectByName('castle');
      if (!castle) throw new Error('Groupe « castle » introuvable');
      const props = castle.getObjectByName('animated_props');
      if (props) props.visible = false;
      try {
        downloadBlob(await exportCastleGlb(castle), 'castle.glb');
      } finally {
        if (props) props.visible = true;
      }
    };
    return () => {
      delete window.__castleExport;
    };
  }, []);
  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [80, 62, 135], fov: 32, near: 0.5, far: 1500 }}
      gl={{ preserveDrawingBuffer: true, antialias: true, toneMapping: THREE.NoToneMapping }}
      style={{ position: 'absolute', inset: 0 }}
    >
      <color attach="background" args={[PALETTE.background]} />
      <CastleLights />
      <group ref={rootRef}>
        <Suspense fallback={null}>
          {source === 'glb' ? <CastleGlb /> : <Castle towerIds={towerIds} />}
          <Mounted onMount={setReady} />
        </Suspense>
      </group>
      <CastleAnimation rootRef={rootRef} ready={ready} onReady={handleAnimator} />
      <OrbitControls target={[0, 8, 12]} maxPolarAngle={Math.PI / 2 - 0.03} minDistance={30} maxDistance={450} />
    </Canvas>
  );
}
