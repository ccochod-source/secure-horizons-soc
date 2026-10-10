import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'TRACE — Agent Security Operations',
  description: 'Console de démonstration pour enquêter sur les incidents des agents IA.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr"><body>{children}</body></html>;
}
