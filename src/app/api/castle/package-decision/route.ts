import { isLocalRequest } from '@/lib/local-request';
import { localBackendBase, privateValue } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
const GATEWAY = (process.env.GATEWAY_API_URL || 'http://127.0.0.1:8002').replace(/\/+$/, '');

/**
 * Décision UNIQUE de l'analyste sur un package bloqué, avec sa session Supabase :
 * 1. la passerelle enregistre la décision (elle vérifie le compte et son droit d'approuver les packages) ;
 * 2. l'incident ouvert par les agents sur cette session est tranché dans la foulée, au nom du même analyste :
 *    refus + « appliquer la mesure » → la mesure proposée est appliquée ; sinon → pas de mesure (surveillance).
 */
export async function POST(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  let body: { reviewId?: unknown; decision?: unknown; incidentId?: unknown; applyMeasure?: unknown };
  try { body = await request.json(); } catch { return Response.json({ error: 'Corps invalide.' }, { status: 400, headers }); }
  const { reviewId, decision, incidentId, applyMeasure } = body;
  if (typeof reviewId !== 'string' || !/^[0-9a-f-]{36}$/i.test(reviewId) || (decision !== 'approve' && decision !== 'reject')
    || (incidentId !== undefined && incidentId !== null && (typeof incidentId !== 'string' || !/^INC-\d{4,}$/.test(incidentId)))) {
    return Response.json({ error: 'Décision invalide.' }, { status: 400, headers });
  }
  const access = request.headers.get('Authorization') ?? '';
  if (!access.startsWith('Bearer ')) return Response.json({ error: 'Connectez-vous avec un compte analyste.' }, { status: 401, headers });
  try {
    // 1. décision sur le package (authentification et droits vérifiés par la passerelle)
    const g = await fetch(`${GATEWAY}/packages/${reviewId}/decision`, {
      method: 'POST', headers: { Authorization: access, 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, note: 'Décision prise depuis la vue château' }), cache: 'no-store', signal: AbortSignal.timeout(90_000),
    });
    const packageResult = (await g.json()) as Record<string, unknown>;
    if (!g.ok) {
      const message = g.status === 401 ? 'Session analyste invalide ou expirée.' : g.status === 403 ? 'Ce compte n’a pas le droit de décider sur les packages.' : String(packageResult.detail ?? `Passerelle : ${g.status}`);
      return Response.json({ error: message }, { status: g.status, headers });
    }
    // 2. l'incident des agents, au nom du même analyste
    let incidentResult: Record<string, unknown> | null = null;
    if (typeof incidentId === 'string') {
      const supabase = (await privateValue('SUPABASE_URL')).replace(/\/+$/, '');
      const key = (await privateValue('SUPABASE_ANON_KEY')) || (await privateValue('SUPABASE_SERVICE_ROLE_KEY'));
      const who = await fetch(`${supabase}/auth/v1/user`, { headers: { apikey: key, Authorization: access }, cache: 'no-store', signal: AbortSignal.timeout(10_000) });
      const analyst = who.ok ? ((await who.json()) as { id?: string }).id ?? 'analyste' : 'analyste';
      const base = await localBackendBase();
      const token = await privateValue('ANALYSTE_TOKEN');
      const apply = decision === 'reject' && applyMeasure === true;
      const d = await fetch(`${base}/incidents/${incidentId}/decision`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ decision: apply ? 'approved' : 'rejected', analyst,
          reason: decision === 'approve' ? 'Package autorisé par l’analyste : pas de mesure.' : apply ? 'Package refusé, mesure des agents appliquée.' : 'Package refusé, sans mesure supplémentaire.' }),
        cache: 'no-store', signal: AbortSignal.timeout(30_000),
      });
      incidentResult = (await d.json()) as Record<string, unknown>;
      if (!d.ok && d.status !== 409) incidentResult = { error: String(incidentResult.detail ?? `Backend de défense : ${d.status}`) };
    }
    return Response.json({ package: packageResult, incident: incidentResult }, { headers });
  } catch {
    return Response.json({ error: 'Service injoignable.' }, { status: 503, headers });
  }
}
