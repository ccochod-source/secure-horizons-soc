import type { Metadata } from 'next';
import { Arsenal } from '@/components/arsenal/arsenal';

export const metadata: Metadata = {
  title: 'Arsenal & centre de décision — TRACE.',
  description: 'Lancer de vraies simulations d’attaque et trancher les décisions humaines en attente.',
};

export default function ArsenalPage() {
  return <Arsenal />;
}
