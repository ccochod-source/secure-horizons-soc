'use client';
import { useEffect } from 'react';
import { useGLTF } from '@react-three/drei';
import type * as THREE from 'three';

export const CASTLE_GLB_URL = '/castle/castle.glb';

/** Charge la version exportée du château (plus rapide au démarrage) ; les noms de groupes sont ceux du modèle procédural. */
export function CastleGlb() {
  const { scene } = useGLTF(CASTLE_GLB_URL);
  useEffect(() => {
    scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.isMesh) {
        m.castShadow = true;
        m.receiveShadow = true;
      }
    });
  }, [scene]);
  return <primitive object={scene} />;
}
