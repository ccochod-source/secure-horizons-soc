import { isLocalRequest } from '@/lib/local-request';
import { privateValue } from '@/lib/soc-server';
import { TESTS, type RunOutcome, type TestKind } from '@/castle/animation/run-types';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
const GATEWAY = 'http://127.0.0.1:8002';

/**
 * Lance un test réel sur la passerelle (port 8002). Le château retrouve sa session dans `public.events`
 * par la demande d'origine (texte exact) et l'heure de lancement (voir /api/castle/trace) :
 * - `leurres`  : DevBot cherche une clé secrète ; s'il touche un leurre, la passerelle le déroute vers le bac à sable ;
 * - `packages` : DevBot suit un guide interne piégé et demande « pdfreport-turbo » ; le contrôle des packages bloque,
 *   puis le backend de défense enquête (règle « installation de package bloquée »).
 * La session est ensuite relayée au backend de défense (port 8000), comme en production.
 */
export async function POST(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  let body: { kind?: string };
  try { body = await request.json(); } catch { return Response.json({ error: 'Corps invalide.' }, { status: 400, headers }); }
  const kind = body.kind as TestKind;
  if (!(kind in TESTS)) {
    return Response.json({ error: 'Type de test ou identifiant invalide.' }, { status: 400, headers });
  }
  const token = (await privateValue('GATEWAY_TOKEN')) || (await privateValue('VICTIM_GATEWAY_TOKEN'));
  const auth = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  const t0 = Date.now();
  const done = (o: Omit<RunOutcome, 'kind' | 'durationMs'>, status = 200) =>
    Response.json({ kind, durationMs: Date.now() - t0, ...o } satisfies RunOutcome, { status, headers });
  try {
    // Les deux tests passent par l'agent DevBot (vrai modèle OpenAI) : seule la question change.
    const r = await fetch(`${GATEWAY}/chat`, {
      method: 'POST', headers: auth, body: JSON.stringify({ question: TESTS[kind].prompt }),
      cache: 'no-store', signal: AbortSignal.timeout(300_000),
    });
    const d = (await r.json()) as { trace_id?: string; answer?: string; diverted?: boolean; detail?: string; pipeline_delivery?: { incident_id?: string | null } };
    if (!r.ok) return done({ ok: false, error: d.detail ?? `Passerelle : ${r.status}` }, 502);
    return done({ ok: true, traceId: d.trace_id, answer: d.answer, diverted: d.diverted, defenseIncidentId: d.pipeline_delivery?.incident_id ?? null });
  } catch {
    return done({ ok: false, error: 'Passerelle injoignable sur le port 8002 (scripts/castle/run_gateway.sh).' }, 503);
  }
}
