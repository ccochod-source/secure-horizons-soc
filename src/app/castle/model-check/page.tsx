import type { Metadata } from 'next';
import { Suspense } from 'react';
import { ModelCheckLoader } from './loader';

export const metadata: Metadata = { title: 'TRACE — Château, vérification des vues' };

export default function Page() {
  return (
    <Suspense fallback={null}>
      <ModelCheckLoader />
    </Suspense>
  );
}
