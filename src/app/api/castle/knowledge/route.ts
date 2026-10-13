import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { isLocalRequest } from '@/lib/local-request';
import { localBackendBase, privateValue } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
const GATEWAY = (process.env.GATEWAY_API_URL || 'http://127.0.0.1:8002').replace(/\/+$/, '');
const UUID_RE = /^[0-9a-f-]{36}$/i;

async function defense(p: string, init: RequestInit = {}) {
  const base = await localBackendBase();
  const token = await privateValue('ANALYSTE_TOKEN');
  return fetch(`${base}${p}`, { ...init, cache: 'no-store', signal: AbortSignal.timeout(30_000),
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
}

/** Statut d'admission d'une connaissance (pending → approved / quarantined / rejected), lu par le backend de défense. */
export async function GET(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  const id = new URL(request.url).searchParams.get('id') ?? '';
  if (!UUID_RE.test(id)) return Response.json({ error: 'Identifiant invalide.' }, { status: 400, headers });
  try {
    const r = await defense(`/knowledge/documents/${id}`);
    return Response.json(await r.json(), { status: r.status, headers });
  } catch {
    return Response.json({ error: 'Backend de défense injoignable.' }, { status: 503, headers });
  }
}

/**
 * `deposit` : redépose le guide piégé de test (données de test, source « tests-chateau ») ; le trigger de la base
 *   le repasse « pending » et l'admission des connaissances de l'équipe l'analyse.
 * `decide`  : décision de l'analyste connecté (session Supabase) sur un document mis en quarantaine par l'admission ;
 *   s'il l'approuve, la passerelle calcule son embedding pour que l'agent puisse le trouver.
 */
export async function POST(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  let body: { op?: unknown; id?: unknown; decision?: unknown };
  try { body = await request.json(); } catch { return Response.json({ error: 'Corps invalide.' }, { status: 400, headers }); }
  const supabase = (await privateValue('SUPABASE_URL')).replace(/\/+$/, '');
  const service = await privateValue('SUPABASE_SERVICE_ROLE_KEY');
  try {
    if (body.op === 'deposit') {
      // Le script de données de test écrit avec le compte propriétaire (la clé REST n'a pas le droit de modifier documents).
      // Chemins construits à l'exécution : le bundler ne doit pas tenter d'embarquer l'environnement Python.
      const root = process.cwd();
      const python = process.env.CASTLE_PYTHON || [root, '.venv', 'bin', 'python'].join('/');
      const script = [root, 'scripts', 'castle', 'seed_test_data.py'].join('/');
      const { stdout } = await promisify(execFile)(/* turbopackIgnore: true */ python, [script, '--redeposit'], { cwd: root, timeout: 30_000 });
      const out = JSON.parse(stdout.trim().split('\n').pop() ?? '{}') as { id?: string; title?: string; status?: string; error?: string };
      if (!out.id) return Response.json({ error: 'Guide de test introuvable : lancer scripts/castle/seed_test_data.py.' }, { status: 404, headers });
      return Response.json(out, { headers });
    }
    if (body.op === 'decide') {
      if (typeof body.id !== 'string' || !UUID_RE.test(body.id) || (body.decision !== 'approve' && body.decision !== 'reject')) {
        return Response.json({ error: 'Décision invalide.' }, { status: 400, headers });
      }
      const access = request.headers.get('Authorization') ?? '';
      if (!access.startsWith('Bearer ')) return Response.json({ error: 'Connectez-vous avec un compte analyste.' }, { status: 401, headers });
      const anon = (await privateValue('SUPABASE_ANON_KEY')) || service;
      const who = await fetch(`${supabase}/auth/v1/user`, { headers: { apikey: anon, Authorization: access }, cache: 'no-store', signal: AbortSignal.timeout(10_000) });
      if (!who.ok) return Response.json({ error: 'Session analyste invalide ou expirée.' }, { status: 401, headers });
      const analyst = ((await who.json()) as { id?: string }).id;
      if (!analyst) return Response.json({ error: 'Session analyste invalide.' }, { status: 401, headers });
      const d = await defense(`/knowledge/documents/${body.id}/decision`, { method: 'POST', body: JSON.stringify({ decision: body.decision, analyst }) });
      const result = (await d.json()) as { status?: string; detail?: string };
      if (!d.ok) return Response.json({ error: result.detail ?? `Backend de défense : ${d.status}` }, { status: d.status, headers });
      let embedded: number | null = null;
      if (body.decision === 'approve') {
        const token = (await privateValue('GATEWAY_TOKEN')) || (await privateValue('VICTIM_GATEWAY_TOKEN'));
        const e = await fetch(`${GATEWAY}/gateway/embeddings`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, cache: 'no-store', signal: AbortSignal.timeout(60_000) });
        embedded = e.ok ? ((await e.json()) as { embedded: number }).embedded : null;
      }
      return Response.json({ ...result, embedded }, { headers });
    }
    return Response.json({ error: 'Opération inconnue.' }, { status: 400, headers });
  } catch {
    return Response.json({ error: 'Service injoignable.' }, { status: 503, headers });
  }
}
