import type { Metadata } from 'next';
import { SocConsole } from '@/components/soc-console';

export const metadata: Metadata = {
  title: 'TRACE — Console SOC',
  description: 'Console de travail : connexions, agents, packages et incidents.',
};

export default function Page() { return <SocConsole />; }
