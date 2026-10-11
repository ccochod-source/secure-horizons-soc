import type { Metadata } from 'next';
import { Suspense } from 'react';
import { CastleView } from './castle-view';

export const metadata: Metadata = { title: 'TRACE — Château', description: 'Modèle 3D du château (React Three Fiber).' };

export default function Page() {
  return (
    <Suspense fallback={null}>
      <CastleView />
    </Suspense>
  );
}
