'use client';
import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import type * as THREE from 'three';
import { CastleAnimator } from './animator';

/** À placer dans le Canvas : crée l'animateur sur le groupe `castle` et le met à jour à chaque frame. */
export function CastleAnimation({ rootRef, onReady, ready }: { rootRef: React.RefObject<THREE.Group | null>; onReady: (a: CastleAnimator | null) => void; ready: boolean }) {
  const animator = useRef<CastleAnimator | null>(null);
  useEffect(() => {
    if (!ready) return;
    const castle = rootRef.current?.getObjectByName('castle');
    if (!castle) return;
    const a = new CastleAnimator(castle);
    animator.current = a;
    onReady(a);
    return () => {
      a.dispose();
      animator.current = null;
      onReady(null);
    };
  }, [ready, rootRef, onReady]);
  useFrame((_, dt) => animator.current?.update(Math.min(dt, 0.1)));
  return null;
}
