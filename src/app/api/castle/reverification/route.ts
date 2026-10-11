import { isLocalRequest } from '@/lib/local-request';
import { localBackendBase, privateValue } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };

async function defense(path: string, init: RequestInit = {}) {
  const base = await localBackendBase();
  const token = await privateValue('ANALYSTE_TOKEN');
  if (!base) throw new Error('Backend de défense non configuré.');
  return fetch(`${base}${path}`, {
    ...init, cache: 'no-store', signal: AbortSignal.timeout(30_000),
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
}

/** Contre-vérification des agents pour un package approuvé (par identifiant de revue). */
export async function GET(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  const reviewId = new URL(request.url).searchParams.get('review_id') ?? '';
  if (!/^[0-9a-f-]{36}$/i.test(reviewId)) return Response.json({ error: 'Identifiant invalide.' }, { status: 400, headers });
  try {
    const r = await defense(`/contre-verifications?review_id=${reviewId}`);
    const list = (await r.json()) as unknown[];
    return Response.json({ contreVerification: Array.isArray(list) ? list[0] ?? null : null }, { status: r.ok ? 200 : 502, headers });
  } catch {
    return Response.json({ error: 'Backend de défense injoignable.' }, { status: 503, headers });
  }
}

/**
 * Réponse de l'analyste à la question « voulez-vous toujours l'ajouter ? ». Son identité vient de sa session
 * Supabase (jeton de la connexion analyste) : le backend de défense n'accepte que l'analyste qui a approuvé.
 */
export async function POST(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  let body: { id?: unknown; maintenir?: unknown };
  try { body = await request.json(); } catch { return Response.json({ error: 'Corps invalide.' }, { status: 400, headers }); }
  if (typeof body.id !== 'string' || !/^CV-\d{4,}$/.test(body.id) || typeof body.maintenir !== 'boolean') {
    return Response.json({ error: 'Réponse invalide.' }, { status: 400, headers });
  }
  const access = request.headers.get('Authorization') ?? '';
  if (!access.startsWith('Bearer ')) return Response.json({ error: 'Connectez-vous avec le compte analyste qui a approuvé.' }, { status: 401, headers });
  const supabase = (await privateValue('SUPABASE_URL')).replace(/\/+$/, '');
  const key = (await privateValue('SUPABASE_ANON_KEY')) || (await privateValue('SUPABASE_SERVICE_ROLE_KEY'));
  try {
    const who = await fetch(`${supabase}/auth/v1/user`, { headers: { apikey: key, Authorization: access }, cache: 'no-store', signal: AbortSignal.timeout(10_000) });
    if (!who.ok) return Response.json({ error: 'Session analyste expirée : reconnectez-vous.' }, { status: 401, headers });
    const { id: analyste } = (await who.json()) as { id?: string };
    if (!analyste) return Response.json({ error: 'Session analyste invalide.' }, { status: 401, headers });
    const r = await defense(`/contre-verifications/${body.id}/confirmation`, { method: 'POST', body: JSON.stringify({ maintenir: body.maintenir, analyste }) });
    const result = (await r.json()) as { detail?: string };
    if (!r.ok) return Response.json({ error: result.detail ?? `Backend de défense : ${r.status}` }, { status: r.status, headers });
    return Response.json(result, { headers });
  } catch {
    return Response.json({ error: 'Service injoignable.' }, { status: 503, headers });
  }
}
