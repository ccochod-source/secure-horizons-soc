import { isLocalRequest } from '@/lib/local-request';
import { localBackendBase, privateValue } from '@/lib/soc-server';
import type { DefenseIncident } from '@/castle/animation/run-types';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };

/** Incident du backend de défense (port 8000) : enquête, conclusions vérifiées, mesure proposée, décision, exécution. */
export async function GET(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  const id = new URL(request.url).searchParams.get('id') ?? '';
  if (!/^INC-\d{4,}$/.test(id)) return Response.json({ error: 'Identifiant invalide.' }, { status: 400, headers });
  const base = await localBackendBase();
  const token = await privateValue('ANALYSTE_TOKEN');
  if (!base) return Response.json({ error: 'Backend de défense non configuré.' }, { status: 503, headers });
  try {
    const r = await fetch(`${base}/incidents/${id}`, { headers: token ? { Authorization: `Bearer ${token}` } : {}, cache: 'no-store', signal: AbortSignal.timeout(8000) });
    if (!r.ok) return Response.json({ error: `Backend de défense : ${r.status}` }, { status: 502, headers });
    const i = (await r.json()) as Record<string, unknown>;
    const ex = (i.execution ?? {}) as Record<string, unknown>;
    const action = i.action as Record<string, unknown> | null;
    const incident: DefenseIncident = {
      id: String(i.id), title: String(i.title ?? ''), description: String(i.description ?? ''), severity: String(i.severity ?? ''),
      status: String(i.status ?? ''), confidence: Number(i.confidence ?? 0),
      conclusions: Array.isArray(i.conclusions) ? (i.conclusions as Record<string, unknown>[]).map((c) => ({ type: String(c.type), affirmation: String(c.affirmation ?? ''), verifiee: c.verifiee === true, raison: String(c.raison ?? '') })) : [],
      proposal: String(i.proposal ?? ''), impact: String(i.impact ?? ''), decision: String(i.decision ?? 'pending'),
      action: action ? { type: String(action.type), cible: String(action.cible), origine: String(action.origine ?? '') } : null,
      execution: { etat: String(ex.etat ?? 'non_demandee'), detail: String(ex.detail ?? '') },
    };
    return Response.json(incident, { headers });
  } catch {
    return Response.json({ error: 'Backend de défense injoignable.' }, { status: 503, headers });
  }
}
