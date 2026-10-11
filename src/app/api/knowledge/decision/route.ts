import { isLocalRequest } from '@/lib/local-request';
import { localBackendBase, privateValue } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const headers = { 'Cache-Control': 'no-store' };

export async function POST(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Disponible uniquement en local.' }, { status: 403, headers });
  let input: unknown;
  try { input = await request.json(); } catch { return Response.json({ error: 'Demande invalide.' }, { status: 400, headers }); }
  if (!input || typeof input !== 'object') return Response.json({ error: 'Demande invalide.' }, { status: 400, headers });
  const { table, id, decision } = input as Record<string, unknown>;
  if (!['documents', 'repo_files'].includes(String(table)) || typeof id !== 'string'
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
    || !['approve', 'reject'].includes(String(decision))) {
    return Response.json({ error: 'Décision invalide.' }, { status: 400, headers });
  }
  const base = await localBackendBase();
  const token = await privateValue('ANALYSTE_TOKEN');
  if (!base || !token) return Response.json({ error: 'Validation analyste indisponible.' }, { status: 503, headers });
  try {
    const response = await fetch(`${base}/knowledge/${table}/${id}/decision`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, analyst: 'analyste-local' }), cache: 'no-store',
      signal: AbortSignal.timeout(12_000),
    });
    if (!response.ok) return Response.json({ error: response.status === 409
      ? 'Cette connaissance a déjà été traitée.' : 'Décision non enregistrée.' }, { status: response.status, headers });
    return Response.json(await response.json(), { headers });
  } catch {
    return Response.json({ error: 'La défense est momentanément indisponible.' }, { status: 503, headers });
  }
}
