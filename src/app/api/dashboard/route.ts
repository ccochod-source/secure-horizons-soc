import { isLocalRequest } from '@/lib/local-request';
import { localBackendBase, privateValue } from '@/lib/soc-server';
import { readGatewayState } from '@/lib/gateway-state';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };

/** Indicateurs du tableau de bord, tous calculés à partir de données réelles (Supabase, backend de défense, passerelle). */
export interface DashboardData {
  checkedAt: string;
  range: '24h' | '7d';
  health: { gateway: boolean; defense: boolean; database: boolean };
  kpis: {
    sessions: number; sessionsPrev: number;
    neutralized: number; neutralizedPrev: number; // sessions déroutées + packages bloqués
    decoysHit: number; packagesBlocked: number; packagesInstalled: number;
    secretsMasked: number; // valeurs remplacées par un jeton avant tout LLM
    leaks: number; // envois externes réussis dans une session compromise
    outboundBlocked: number;
    detectionMedianS: number | null; // user_request → première détection
    pendingDecisions: number; // humain dans la boucle
    pendingBreakdown: { incidents: number; packages: number; documents: number; reverifications: number };
    certaintyAvg: number | null; incidents: number; incidentsBySeverity: Record<string, number>; incidentsByStatus: Record<string, number>;
    activeMeasures: number;
    humanActions: number; attacksDetected: number; humanActionsPerAttack: number | null; // actions humaines / attaque détectée
  };
  /** Boucle d'apprentissage : règles de défense apprises (liste des packages/leurres), version qui s'auto-incrémente. */
  learning: { version: number; proposed: number; active: number; rolledBack: number; byList: { package: { active: number; proposed: number }; decoy: { active: number; proposed: number } }; series: number[]; attacksTotal: number; sessionsTotal: number; protections: number; points: { label: string; neutralized: number; protections: number }[] };
  series: { label: string; sessions: number; threats: number }[];
  split: { safe: number; threats: number; open: number };
  incidents: { id: string; title: string; severity: string; status: string; confidence: number; proposal: string; decision: string; time: string }[];
  measures: { suspensions: { agent_id: string; tool: string; incident_id: string }[]; packages: { package: string; incident_id: string }[]; documents: { document_id: string; title: string; incident_id: string }[] };
}

type Ev = { trace_id: string; occurred_at: string; event_type: string; action: string | null; result: string | null; metadata: Record<string, unknown> | null };
const OUTBOUND = new Set(['send_message', 'http.post', 'github.publish', 'email.send', 'slack.post', 'webhook.send']);

async function up(url: string, init: RequestInit = {}) {
  try { const r = await fetch(url, { ...init, cache: 'no-store', signal: AbortSignal.timeout(4000) }); return r.ok ? r : null; } catch { return null; }
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** Agrégats sur un lot d'événements (une période). */
function aggregate(events: Ev[]) {
  const byTrace = new Map<string, Ev[]>();
  for (const e of events) byTrace.set(e.trace_id, [...(byTrace.get(e.trace_id) ?? []), e]);
  let sessions = 0, diverted = 0, decoysHit = 0, packagesBlocked = 0, packagesInstalled = 0, leaks = 0, outboundBlocked = 0, secretsMasked = 0;
  const detect: number[] = [];
  for (const evs of byTrace.values()) {
    const req = evs.find((e) => e.event_type === 'user_request');
    if (req) sessions++;
    const isDiverted = evs.some((e) => e.event_type === 'session_diverted');
    if (isDiverted) diverted++;
    if (evs.some((e) => e.event_type === 'decoy_access')) decoysHit++;
    const blockedPkg = evs.some((e) => e.event_type === 'package_review' && e.result === 'pending');
    if (blockedPkg) packagesBlocked++;
    if (evs.some((e) => e.event_type === 'dependency_installed')) packagesInstalled++;
    for (const e of evs) {
      if (e.event_type === 'tool_response' && OUTBOUND.has(e.action ?? '')) {
        if (e.result === 'success' && isDiverted) leaks++;
        if (e.result === 'blocked') outboundBlocked++;
      }
      const tokens = e.metadata?.tokens;
      if (Array.isArray(tokens)) secretsMasked += tokens.length;
    }
    if (req) {
      const first = evs.filter((e) => e.event_type === 'decoy_access' || (e.event_type === 'package_review' && e.result === 'pending') || (e.event_type === 'tool_response' && e.result === 'blocked'))
        .map((e) => Date.parse(e.occurred_at)).sort((a, b) => a - b)[0];
      if (first) detect.push((first - Date.parse(req.occurred_at)) / 1000);
    }
  }
  return { sessions, neutralized: diverted + packagesBlocked, diverted, decoysHit, packagesBlocked, packagesInstalled, leaks, outboundBlocked, secretsMasked, detectionMedianS: median(detect) };
}

export async function GET(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  const range = new URL(request.url).searchParams.get('range') === '7d' ? '7d' : '24h';
  const now = Date.now();
  const span = range === '7d' ? 7 * 86400e3 : 86400e3;
  const since = new Date(now - 2 * span).toISOString();
  const checkedAt = new Date(now).toISOString();

  const supabase = (await privateValue('SUPABASE_URL')).replace(/\/+$/, '');
  const key = await privateValue('SUPABASE_SERVICE_ROLE_KEY');
  const sb = { apikey: key, Authorization: `Bearer ${key}` };
  const base = await localBackendBase();
  const analyst = await privateValue('ANALYSTE_TOKEN');
  const defAuth: Record<string, string> = analyst ? { Authorization: `Bearer ${analyst}` } : {};
  const confinement = await privateValue('CONFINEMENT_TOKEN');

  const [gw, df, evRes, incRes, cvRes, docRes, qdocRes, pkgRulesRes, decoyRulesRes, metaRes] = await Promise.all([
    up('http://127.0.0.1:8002/health'),
    up('http://127.0.0.1:8000/health'),
    supabase && key ? up(`${supabase}/rest/v1/events?select=trace_id,occurred_at,event_type,action,result,metadata&occurred_at=gte.${encodeURIComponent(since)}&order=occurred_at.asc&limit=5000`, { headers: sb }) : null,
    base ? up(`${base}/incidents`, { headers: defAuth }) : null,
    base ? up(`${base}/contre-verifications`, { headers: defAuth }) : null,
    supabase && key ? up(`${supabase}/rest/v1/documents?select=id,review_status&review_status=in.(pending,quarantined)`, { headers: sb }) : null,
    up('http://127.0.0.1:8002/confinement/documents', { headers: { Authorization: `Bearer ${confinement}` } }),
    supabase && key ? up(`${supabase}/rest/v1/package_rules?select=status`, { headers: sb }) : null,
    supabase && key ? up(`${supabase}/rest/v1/decoy_rules?select=status`, { headers: sb }) : null,
    supabase && key ? up(`${supabase}/rest/v1/ruleset_meta?select=current_version`, { headers: sb }) : null,
  ]);
  const events = (evRes ? ((await evRes.json()) as Ev[]) : []);
  const incidentsRaw = incRes ? ((await incRes.json()) as Record<string, unknown>[]) : [];
  const cvs = cvRes ? ((await cvRes.json()) as { statut: string }[]) : [];
  const docsPending = docRes ? ((await docRes.json()) as unknown[]).length : 0;
  const qdocs = qdocRes ? (((await qdocRes.json()) as { documents: DashboardData['measures']['documents'] }).documents ?? []) : [];
  const state = await readGatewayState();

  // Boucle d'apprentissage : règles de défense apprises (packages + leurres) et version du jeu de règles.
  const pkgRules = pkgRulesRes ? ((await pkgRulesRes.json()) as { status: string }[]) : [];
  const decoyRules = decoyRulesRes ? ((await decoyRulesRes.json()) as { status: string }[]) : [];
  const metaRows = metaRes ? ((await metaRes.json()) as { current_version: number }[]) : [];
  const countBy = (rows: { status: string }[], s: string) => rows.filter((r) => r.status === s).length;
  const activeRules = countBy(pkgRules, 'active') + countBy(decoyRules, 'active');

  const cutoff = now - span;
  const current = events.filter((e) => Date.parse(e.occurred_at) >= cutoff);
  const previous = events.filter((e) => Date.parse(e.occurred_at) < cutoff);
  const cur = aggregate(current);
  const prev = aggregate(previous);

  // série temporelle : sessions et menaces neutralisées par heure (24 h) ou par jour (7 j)
  const buckets = range === '7d' ? 7 : 24;
  const bucketMs = span / buckets;
  const series = Array.from({ length: buckets }, (_, i) => {
    const start = cutoff + i * bucketMs;
    const slice = current.filter((e) => { const t = Date.parse(e.occurred_at); return t >= start && t < start + bucketMs; });
    const a = aggregate(slice);
    const d = new Date(start);
    return { label: range === '7d' ? d.toLocaleDateString('fr-FR', { weekday: 'short' }) : `${d.getHours()}h`, sessions: a.sessions, threats: a.neutralized };
  });

  // Amélioration de la sécurité : courbe cumulée des attaques neutralisées sur la période (grandit à chaque requête).
  let accNeutralized = 0;
  const learningPoints = series.map((s) => { accNeutralized += s.threats; return { label: s.label, neutralized: accNeutralized, protections: activeRules }; });
  const learning: DashboardData['learning'] = {
    version: metaRows[0]?.current_version ?? 0,
    proposed: countBy(pkgRules, 'proposed') + countBy(decoyRules, 'proposed'),
    active: activeRules,
    rolledBack: countBy(pkgRules, 'rolled_back') + countBy(decoyRules, 'rolled_back'),
    byList: {
      package: { active: countBy(pkgRules, 'active'), proposed: countBy(pkgRules, 'proposed') },
      decoy: { active: countBy(decoyRules, 'active'), proposed: countBy(decoyRules, 'proposed') },
    },
    series: learningPoints.map((p) => p.neutralized),
    attacksTotal: cur.neutralized,
    sessionsTotal: cur.sessions,
    protections: activeRules,
    points: learningPoints,
  };

  const incidents = incidentsRaw.map((i) => ({
    id: String(i.id), title: String(i.title ?? ''), severity: String(i.severity ?? ''), status: String(i.status ?? ''),
    confidence: Number(i.confidence ?? 0), proposal: String(i.proposal ?? ''), decision: String(i.decision ?? 'pending'), time: String(i.time ?? ''),
  }));
  const count = (xs: string[]) => xs.reduce<Record<string, number>>((acc, k) => ({ ...acc, [k]: (acc[k] ?? 0) + 1 }), {});
  const pendingBreakdown = {
    incidents: incidents.filter((i) => i.decision === 'pending').length,
    packages: current.filter((e) => e.event_type === 'package_review' && e.result === 'pending').length - current.filter((e) => e.event_type === 'package_review' && (e.action === 'approve' || e.action === 'reject')).length,
    documents: docsPending,
    reverifications: cvs.filter((c) => c.statut === 'attente_confirmation' || c.statut === 'retrait_en_echec').length,
  };
  pendingBreakdown.packages = Math.max(0, pendingBreakdown.packages);
  const certainty = incidents.length ? incidents.reduce((s, i) => s + i.confidence, 0) / incidents.length : null;
  const safe = Math.max(0, cur.sessions - cur.neutralized);
  // Actions humaines (décisions requises par les attaques) rapportées aux attaques détectées.
  const humanActions = cur.packagesBlocked + pendingBreakdown.incidents + pendingBreakdown.documents + pendingBreakdown.reverifications;
  const attacksDetected = cur.neutralized;
  const humanActionsPerAttack = attacksDetected > 0 ? humanActions / attacksDetected : null;

  const data: DashboardData = {
    checkedAt, range,
    health: { gateway: !!gw, defense: !!df, database: !!evRes },
    kpis: {
      sessions: cur.sessions, sessionsPrev: prev.sessions, neutralized: cur.neutralized, neutralizedPrev: prev.neutralized,
      decoysHit: cur.decoysHit, packagesBlocked: cur.packagesBlocked, packagesInstalled: cur.packagesInstalled,
      secretsMasked: cur.secretsMasked, leaks: cur.leaks, outboundBlocked: cur.outboundBlocked, detectionMedianS: cur.detectionMedianS,
      pendingDecisions: Object.values(pendingBreakdown).reduce((a, b) => a + b, 0), pendingBreakdown,
      certaintyAvg: certainty, incidents: incidents.length, incidentsBySeverity: count(incidents.map((i) => i.severity)), incidentsByStatus: count(incidents.map((i) => i.status)),
      activeMeasures: state.suspensions.length + state.packages.length + qdocs.length,
      humanActions, attacksDetected, humanActionsPerAttack,
    },
    learning,
    series,
    split: { safe, threats: cur.neutralized, open: pendingBreakdown.packages },
    incidents: incidents.slice(0, 8),
    measures: { suspensions: state.suspensions, packages: state.packages, documents: qdocs },
  };
  return Response.json(data, { headers });
}
