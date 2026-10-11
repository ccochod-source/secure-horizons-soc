import { isLocalRequest } from '@/lib/local-request';
import { localBackendBase, privateValue } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
const GATEWAY = 'http://127.0.0.1:8002';

export interface PendingDoc { id: string; table: 'documents' | 'repo_files'; title: string; version: string | null; preview: string; status: string; reason: string | null }
export interface PendingPackage { id: string; package: string; version: string; status: string; risk: string | null; recommendation: string | null }
export interface PendingIncident { id: string; title: string; severity: string; status: string; confidence: number; proposal: string }
export interface PendingReverif { id: string; package: string; question: string | null; resume: string | null; verdict: string | null; motifs: string[]; confiance: number | null }
export interface PendingQueue { documents: PendingDoc[]; packages: PendingPackage[]; incidents: PendingIncident[]; reverifications: PendingReverif[]; health: { gateway: boolean; defense: boolean } }

/** Récupère une réponse JSON en liste, sans jamais lever : une source en panne ne doit pas vider toutes les autres. */
async function fetchList(url: string, init: RequestInit = {}): Promise<{ ok: boolean; rows: Record<string, unknown>[] }> {
  try {
    const r = await fetch(url, { ...init, cache: 'no-store', signal: AbortSignal.timeout(10_000) });
    if (!r.ok) return { ok: false, rows: [] };
    const body = (await r.json()) as unknown;
    const rows = Array.isArray(body) ? body : Array.isArray((body as { reviews?: unknown[] }).reviews) ? (body as { reviews: unknown[] }).reviews : [];
    return { ok: true, rows: rows.filter((x): x is Record<string, unknown> => !!x && typeof x === 'object') };
  } catch { return { ok: false, rows: [] }; }
}
async function alive(url: string, init: RequestInit = {}): Promise<boolean> {
  try { const r = await fetch(url, { ...init, cache: 'no-store', signal: AbortSignal.timeout(6000) }); return r.ok; } catch { return false; }
}

/** File unifiée des décisions humaines en attente, tous types de données confondus (le centre de décision de l'arsenal). */
export async function GET(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  const empty: PendingQueue = { documents: [], packages: [], incidents: [], reverifications: [], health: { gateway: false, defense: false } };
  try {
    const base = await localBackendBase();
    const analyst = await privateValue('ANALYSTE_TOKEN');
    const defAuth: Record<string, string> = analyst ? { Authorization: `Bearer ${analyst}` } : {};
    const gwToken = (await privateValue('GATEWAY_TOKEN')) || (await privateValue('VICTIM_GATEWAY_TOKEN'));

    const [gw, df, inc, cv, kn, pkg] = await Promise.all([
      alive(`${GATEWAY}/health`),
      base ? alive(`${base}/health`) : Promise.resolve(false),
      base ? fetchList(`${base}/incidents`, { headers: defAuth }) : Promise.resolve({ ok: false, rows: [] }),
      base ? fetchList(`${base}/contre-verifications`, { headers: defAuth }) : Promise.resolve({ ok: false, rows: [] }),
      base ? fetchList(`${base}/knowledge/reviews`, { headers: defAuth }) : Promise.resolve({ ok: false, rows: [] }),
      fetchList(`${GATEWAY}/gateway/package-reviews`, { headers: { Authorization: `Bearer ${gwToken}` } }),
    ]);

    const incidents: PendingIncident[] = inc.rows
      .filter((i) => String(i.decision ?? 'pending') === 'pending')
      .map((i) => ({ id: String(i.id), title: String(i.title ?? ''), severity: String(i.severity ?? ''), status: String(i.status ?? ''), confidence: Number(i.confidence ?? 0), proposal: String(i.proposal ?? '') }));

    const reverifications: PendingReverif[] = cv.rows
      .filter((c) => ['attente_confirmation', 'retrait_en_echec'].includes(String(c.statut)))
      .map((c) => ({ id: String(c.id), package: String(c.package ?? ''), question: typeof c.question === 'string' ? c.question : null, resume: typeof c.resume === 'string' ? c.resume : null, verdict: typeof c.verdict === 'string' ? c.verdict : null, motifs: Array.isArray(c.motifs_confirmation) ? (c.motifs_confirmation as string[]) : [], confiance: typeof c.confiance_initiale === 'number' ? c.confiance_initiale : null }));

    const documents: PendingDoc[] = kn.rows
      .filter((d) => ['documents', 'repo_files'].includes(String(d.source_table)) && ['pending', 'quarantined'].includes(String(d.review_status)))
      .map((d) => ({ id: String(d.id), table: d.source_table as 'documents' | 'repo_files', title: typeof d.title === 'string' ? d.title : 'Sans titre', version: typeof d.version === 'string' ? d.version : null, preview: typeof d.preview === 'string' ? d.preview : '', status: String(d.review_status), reason: typeof d.review_reason === 'string' ? d.review_reason : null }));

    const packages: PendingPackage[] = pkg.rows
      .filter((p) => !['approved', 'rejected', 'removed'].includes(String(p.state)))
      .map((p) => ({ id: String(p.id), package: String(p.package_name ?? ''), version: typeof p.version === 'string' ? p.version : '—', status: String(p.state), risk: typeof p.risk_level === 'string' ? p.risk_level : null, recommendation: typeof p.recommendation === 'string' ? p.recommendation : null }));

    const queue: PendingQueue = { documents, packages, incidents, reverifications, health: { gateway: gw, defense: df } };
    return Response.json(queue, { headers });
  } catch {
    return Response.json(empty, { headers });
  }
}
