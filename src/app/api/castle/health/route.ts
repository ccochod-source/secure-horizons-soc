import { isLocalRequest } from '@/lib/local-request';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store' };

async function up(url: string) {
  try { return (await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(3000) })).ok; } catch { return false; }
}

/** État des deux services réels suivis par le château : passerelle (8002) et backend de défense (8000). */
export async function GET(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  const [gateway, defense] = await Promise.all([up('http://127.0.0.1:8002/health'), up('http://127.0.0.1:8000/health')]);
  return Response.json({ gateway, defense }, { headers });
}
