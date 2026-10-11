import { isLocalRequest } from '@/lib/local-request';
import { privateValue } from '@/lib/soc-server';
import { TESTS, type RunEvent, type RunReview, type RunTrace, type TestKind } from '@/castle/animation/run-types';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function parse(v: unknown): Record<string, unknown> {
  if (v && typeof v === 'object') return v as Record<string, unknown>;
  if (typeof v === 'string') { try { const o = JSON.parse(v); return o && typeof o === 'object' ? o : { text: v }; } catch { return { text: v }; } }
  return {};
}

/**
 * État du contrôle de package, reconstitué uniquement à partir des événements tracés
 * (`package_review` du système puis de l'analyste, `dependency_installed`) : aucune autre table n'est lue.
 */
function reviewFromEvents(rows: Record<string, unknown>[], events: RunEvent[]): RunReview | null {
  const asked = events.find((e) => e.type === 'package_install_requested');
  const sys = events.findIndex((e, i) => e.type === 'package_review' && rows[i]?.actor_type === 'system');
  if (!asked) return null;
  const args = (asked.content.arguments ?? {}) as Record<string, unknown>;
  const base = { packageName: String(args.name ?? ''), registry: String(args.ecosystem ?? '') };
  if (sys < 0) return { id: '', ...base, state: 'proposed', risk: '', recommendation: '', signals: [], replacement: null, humanDecision: null, removed: false };
  const verdict = events[sys];
  const meta = parse(rows[sys].metadata);
  const signals = (Array.isArray(verdict.content.signals) ? verdict.content.signals : []) as Record<string, unknown>[];
  const typo = signals.find((x) => x.code === 'typosquat');
  const replacement = typo ? (String(typo.explanation).match(/«\s*([^»]+?)\s*»/)?.[1] ?? null) : null;
  let state = verdict.result === 'pending' ? 'pending_approval' : verdict.result === 'success' ? 'executed' : verdict.result === 'blocked' ? 'rejected' : 'proposed';
  const decision = events.find((e, i) => i > sys && e.type === 'package_review' && rows[i]?.actor_type === 'user');
  if (decision) state = decision.action === 'approve' ? 'approved' : 'rejected';
  const installed = events.find((e, i) => i > sys && e.type === 'dependency_installed');
  if (installed && state !== 'rejected') state = installed.result === 'success' ? 'executed' : 'failed';
  const failed = events.find((e, i) => i > sys && e.type === 'package_review' && e.action === 'install' && e.result === 'error');
  if (failed && state === 'approved') state = 'failed';
  const removed = events.some((e) => e.type === 'package_review' && e.action === 'remove');
  if (removed) state = 'rejected';
  return {
    id: String(meta.review_id ?? ''), ...base, state, risk: String(verdict.content.risk_level ?? ''),
    recommendation: replacement ? `Remplacer par « ${replacement} ».` : '',
    signals: signals.map((x) => ({ code: String(x.code), explanation: String(x.explanation ?? ''), blocking: x.code === 'package_not_found' })),
    replacement,
    humanDecision: decision ? (decision.action === 'approve' ? 'approve' : 'reject') : null,
    removed,
  };
}

/**
 * Événements d'un test, lus dans Supabase (`public.events`) au fil de l'eau.
 * Paramètres : `kind` + `since` (heure de lancement) pour retrouver la session par sa demande d'origine,
 * puis `traceId` une fois connue. `exclude` : sessions déjà affichées (tests précédents), séparées par des virgules.
 */
export async function GET(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  const q = new URL(request.url).searchParams;
  const kind = q.get('kind') as TestKind;
  const since = q.get('since') ?? '';
  let traceId = q.get('traceId') ?? '';
  const exclude = new Set((q.get('exclude') ?? '').split(',').filter((x) => UUID_RE.test(x)));
  if (!(kind in TESTS) || Number.isNaN(Date.parse(since)) || (traceId && !UUID_RE.test(traceId))) {
    return Response.json({ error: 'Paramètres invalides.' }, { status: 400, headers });
  }
  const base = (await privateValue('SUPABASE_URL')).replace(/\/+$/, '');
  const key = await privateValue('SUPABASE_SERVICE_ROLE_KEY');
  if (!base.startsWith('https://') || !key) return Response.json({ error: 'SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY manquants.' }, { status: 503, headers });
  const h = { apikey: key, Authorization: `Bearer ${key}` };
  try {
    if (!traceId) {
      const sr = await fetch(`${base}/rest/v1/events?select=trace_id,content&event_type=eq.user_request&occurred_at=gte.${encodeURIComponent(new Date(since).toISOString())}&order=occurred_at.desc&limit=20`, { headers: h, cache: 'no-store', signal: AbortSignal.timeout(8000) });
      const found = sr.ok ? ((await sr.json()) as { trace_id: string; content: unknown }[]) : [];
      const match = found.find((r) => !exclude.has(r.trace_id) && parse(r.content).text === TESTS[kind].prompt);
      if (!match) return Response.json({ traceId: null, events: [], review: null } satisfies RunTrace, { headers });
      traceId = match.trace_id;
    }
    const er = await fetch(`${base}/rest/v1/events?select=id,trace_id,occurred_at,event_type,actor_type,action,result,resource_id,content,metadata&trace_id=eq.${traceId}&order=occurred_at.asc,id.asc`, { headers: h, cache: 'no-store', signal: AbortSignal.timeout(8000) });
    if (!er.ok) return Response.json({ error: `Supabase events : ${er.status}` }, { status: 502, headers });
    const rows = (await er.json()) as Record<string, unknown>[];
    const events: RunEvent[] = rows.map((r) => ({
      id: String(r.id), at: String(r.occurred_at), type: String(r.event_type ?? ''), action: String(r.action ?? ''),
      result: String(r.result ?? ''), resourceId: String(r.resource_id ?? ''), content: parse(r.content),
    }));
    const review = reviewFromEvents(rows, events);
    return Response.json({ traceId, events, review } satisfies RunTrace, { headers });
  } catch {
    return Response.json({ error: 'Supabase injoignable.' }, { status: 503, headers });
  }
}
