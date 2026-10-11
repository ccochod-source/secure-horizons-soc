import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { isLocalRequest } from '@/lib/local-request';
import { privateValue } from '@/lib/soc-server';
import { ATTACK_BY_ID } from '@/castle/arsenal-catalog';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
const GATEWAY = 'http://127.0.0.1:8002';

/**
 * Lance une simulation d'attaque réelle de l'arsenal (environnement de test autorisé de notre propre SOC).
 * L'identifiant doit figurer dans le catalogue (liste blanche) ; on exécute alors l'opération correspondante :
 *   - document : plante un document piégé dans public.documents (l'admission des connaissances l'analyse) ;
 *   - package  : introduit un package via la passerelle (contrôle réel PyPI/npm/OSV, jamais exécuté) ;
 *   - chat     : vraie conversation avec l'agent DevBot derrière la passerelle.
 * Aucun package n'est jamais installé : il est seulement téléchargé en quarantaine pour analyse statique.
 */
export async function POST(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'L’arsenal est disponible uniquement depuis l’interface locale.' }, { status: 403, headers });
  let body: { id?: unknown };
  try { body = await request.json(); } catch { return Response.json({ error: 'Demande invalide.' }, { status: 400, headers }); }
  const attack = typeof body.id === 'string' ? ATTACK_BY_ID[body.id] : undefined;
  if (!attack) return Response.json({ error: 'Attaque inconnue.' }, { status: 400, headers });

  try {
    if (attack.kind === 'document') {
      const root = process.cwd();
      const python = process.env.CASTLE_PYTHON || [root, '.venv', 'bin', 'python'].join('/');
      const script = [root, 'scripts', 'castle', 'plant_doc.py'].join('/');
      // Chemins construits à l'exécution : le bundler ne doit pas embarquer l'environnement Python.
      const { stdout } = await promisify(execFile)(/* turbopackIgnore: true */ python, [script, '--id', attack.docId ?? attack.id], { cwd: root, timeout: 30_000 });
      const out = JSON.parse(stdout.trim().split('\n').pop() ?? '{}') as { id?: string; title?: string; status?: string };
      if (!out.id) return Response.json({ error: 'Document introuvable dans l’arsenal.' }, { status: 404, headers });
      return Response.json({
        kind: 'document', attackId: attack.id, docId: out.id, title: out.title, status: out.status ?? 'pending',
        message: 'Document piégé déposé dans la base. L’admission des connaissances l’analyse ; retrouvez-le dans le centre de décision.',
      }, { headers });
    }

    const token = (await privateValue('GATEWAY_TOKEN')) || (await privateValue('VICTIM_GATEWAY_TOKEN'));
    if (!token) return Response.json({ error: 'Jeton de la passerelle absent (port 8002).' }, { status: 503, headers });
    const auth = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

    if (attack.kind === 'package') {
      const session = await fetch(`${GATEWAY}/gateway/sessions`, { method: 'POST', headers: auth, body: JSON.stringify({ agent_id: 'dev-01', query: `Installer ${attack.name}` }), cache: 'no-store', signal: AbortSignal.timeout(10_000) });
      if (!session.ok) throw new Error('session');
      const { trace_id } = (await session.json()) as { trace_id: string };
      const args: Record<string, string> = { name: attack.name ?? '', ecosystem: attack.ecosystem ?? 'pypi' };
      if (attack.version) args.version = attack.version;
      const r = await fetch(`${GATEWAY}/gateway/sessions/${trace_id}/tools/install_package`, { method: 'POST', headers: auth, body: JSON.stringify({ arguments: args }), cache: 'no-store', signal: AbortSignal.timeout(90_000) });
      const result = (await r.json()) as { result?: { status?: string; review_id?: string; risk_level?: string; recommendation?: string; reason?: string } };
      const delivery = await fetch(`${GATEWAY}/gateway/sessions/${trace_id}/complete`, { method: 'POST', headers: auth, cache: 'no-store', signal: AbortSignal.timeout(100_000) });
      const d = (await delivery.json()) as { incident_id?: string | null };
      const pkg = result.result ?? {};
      return Response.json({
        kind: 'package', attackId: attack.id, traceId: trace_id,
        status: pkg.status ?? 'inconnu', reviewId: pkg.review_id ?? null, risk: pkg.risk_level ?? null,
        recommendation: pkg.recommendation ?? pkg.reason ?? null, incidentId: d.incident_id ?? null,
        message: pkg.status === 'blocked_pending_review'
          ? 'Package bloqué : introduit dans la base en attente d’une décision analyste. Il n’a jamais été exécuté.'
          : `Statut du contrôle : ${pkg.status ?? 'inconnu'}.`,
      }, { status: r.ok ? 200 : 502, headers });
    }

    // chat
    const r = await fetch(`${GATEWAY}/chat`, { method: 'POST', headers: auth, body: JSON.stringify({ question: attack.question, poisoned: attack.poisoned === true }), cache: 'no-store', signal: AbortSignal.timeout(300_000) });
    const d = (await r.json()) as { trace_id?: string; answer?: string; diverted?: boolean; neutralized?: boolean; tool_calls?: string[]; detail?: string; pipeline_delivery?: { incident_id?: string | null } };
    if (!r.ok || !d.trace_id) return Response.json({ error: d.detail ?? `La passerelle a répondu ${r.status}.` }, { status: r.status >= 500 ? 502 : r.status, headers });
    const defenses = { decoy: false, sandbox: false, packageBlocked: false, outboundBlocked: false, secretsMasked: 0 };
    const supabase = (await privateValue('SUPABASE_URL')).replace(/\/+$/, '');
    const key = await privateValue('SUPABASE_SERVICE_ROLE_KEY');
    if (supabase && key) {
      try {
        const er = await fetch(`${supabase}/rest/v1/events?select=event_type,action,result,metadata&trace_id=eq.${d.trace_id}`, { headers: { apikey: key, Authorization: `Bearer ${key}` }, cache: 'no-store', signal: AbortSignal.timeout(8000) });
        const evs = er.ok ? ((await er.json()) as { event_type: string; action: string | null; result: string | null; metadata: { tokens?: string[] } | null }[]) : [];
        for (const e of evs) {
          if (e.event_type === 'decoy_access') defenses.decoy = true;
          if (e.event_type === 'session_diverted') defenses.sandbox = true;
          if (e.event_type === 'package_review' && e.result === 'pending') defenses.packageBlocked = true;
          if (e.event_type === 'tool_response' && e.result === 'blocked' && e.action !== 'search_docs') defenses.outboundBlocked = true;
          defenses.secretsMasked += e.metadata?.tokens?.length ?? 0;
        }
      } catch { /* la réponse reste utile sans ce détail */ }
    }
    return Response.json({
      kind: 'chat', attackId: attack.id, traceId: d.trace_id, answer: d.answer ?? '',
      diverted: !!d.diverted, neutralized: !!d.neutralized, toolCalls: d.tool_calls ?? [],
      incidentId: d.pipeline_delivery?.incident_id ?? null, defenses,
      message: 'Conversation réelle jouée derrière la passerelle. Défenses déclenchées lues dans les événements tracés.',
    }, { headers });
  } catch {
    return Response.json({ error: 'Service indisponible. Vérifier la passerelle (8002), le backend (8000) et le .venv.' }, { status: 503, headers });
  }
}
