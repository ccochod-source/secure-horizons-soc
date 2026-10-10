import { isLocalRequest } from '@/lib/local-request';
import { localBackendBase, privateValue } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };

export async function POST(request: Request) {
  if (!isLocalRequest(request)) {
    return Response.json({ error: 'Les décisions sont disponibles uniquement depuis l’interface locale.' }, { status: 403, headers });
  }
  let body: unknown;
  try { body = await request.json(); }
  catch { return Response.json({ error: 'La décision envoyée est invalide.' }, { status: 400, headers }); }
  if (!body || typeof body !== 'object') return Response.json({ error: 'La décision envoyée est invalide.' }, { status: 400, headers });
  const input = body as Record<string, unknown>;
  if (typeof input.id !== 'string' || !/^INC-\d{4,}$/.test(input.id)
    || !['approved', 'rejected'].includes(String(input.decision))
    || (input.reason !== undefined && (typeof input.reason !== 'string' || input.reason.length > 500))) {
    return Response.json({ error: 'Identifiant ou décision invalide.' }, { status: 400, headers });
  }

  const base = await localBackendBase();
  const analystToken = await privateValue('ANALYSTE_TOKEN');
  if (!base || !analystToken) return Response.json({ error: 'La pipeline ou le jeton analyste est indisponible.' }, { status: 503, headers });
  try {
    const upstream = await fetch(`${base}/incidents/${encodeURIComponent(input.id)}/decision`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${analystToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision: input.decision, reason: input.reason ?? '', analyst: 'analyste-interface' }),
      cache: 'no-store',
      signal: AbortSignal.timeout(15_000),
    });
    const result: unknown = await upstream.json();
    if (!upstream.ok) {
      const message = result && typeof result === 'object' && 'detail' in result && typeof result.detail === 'string'
        ? result.detail : 'La pipeline a refusé la décision.';
      return Response.json({ error: message }, { status: upstream.status >= 400 && upstream.status < 500 ? upstream.status : 502, headers });
    }
    return Response.json(result, { headers });
  } catch {
    return Response.json({ error: 'Impossible de joindre la pipeline de défense.' }, { status: 503, headers });
  }
}
