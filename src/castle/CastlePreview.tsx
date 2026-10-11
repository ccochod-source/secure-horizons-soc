'use client';
import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { CastleLights } from './Castle';
import { CastleGlb } from './CastleGlb';

/** Aperçu du château (castle.glb) qui tourne lentement, sans interaction : vignette du tableau de bord. */
export function CastlePreview() {
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [120, 70, 120], fov: 26, near: 1, far: 1000 }}
      gl={{ alpha: true, antialias: true, toneMapping: THREE.NoToneMapping }}
      style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
    >
      <CastleLights />
      <Suspense fallback={null}>
        <CastleGlb />
      </Suspense>
      <OrbitControls autoRotate autoRotateSpeed={0.9} enableZoom={false} enablePan={false} enableRotate={false} target={[0, 10, 0]} />
    </Canvas>
  );
}
