import { isLocalRequest } from '@/lib/local-request';
import { localBackendBase, privateValue } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };

export async function POST(request: Request) {
  if (!isLocalRequest(request)) {
    return Response.json({ error: 'La simulation est disponible uniquement en local.' }, { status: 403, headers });
  }
  const base = await localBackendBase();
  const token = await privateValue('PASSERELLE_TOKEN');
  if (!base || !token) return Response.json({ error: 'La défense est indisponible.' }, { status: 503, headers });
  try {
    const response = await fetch(`${base}/knowledge/demo`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }, cache: 'no-store',
      signal: AbortSignal.timeout(20_000),
    });
    if (!response.ok) return Response.json({ error: 'L’ajout de démonstration a échoué.' }, { status: 502, headers });
    const raw: unknown = await response.json();
    if (!raw || typeof raw !== 'object') throw new Error('invalid response');
    const outcome = raw as Record<string, unknown>;
    return Response.json({
      id: typeof outcome.id === 'string' ? outcome.id : '',
      title: typeof outcome.title === 'string' ? outcome.title : '',
      status: typeof outcome.status === 'string' ? outcome.status : 'pending',
      reason: typeof outcome.reason === 'string' ? outcome.reason : null,
    }, { headers });
  } catch {
    return Response.json({ error: 'La défense n’a pas répondu. Vérifiez le service sur le port 8000.' }, { status: 503, headers });
  }
}
