import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'TRACE — Vue d’ensemble',
  description: 'Tableau de bord de travail : connexions, agents, packages et incidents.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr"><body>{children}</body></html>;
}
