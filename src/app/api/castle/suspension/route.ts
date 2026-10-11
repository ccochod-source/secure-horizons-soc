import path from 'node:path';
import { isLocalRequest } from '@/lib/local-request';
import { privateValue } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store' };
// État local de la passerelle (backend/gateway/defense.py) : mesures appliquées sur décision d'un analyste.
const STATE = path.join(process.cwd(), '.runtime', 'gateway-state.sqlite');

const GATEWAY = 'http://127.0.0.1:8002';

/** Documents en quarantaine : gérés par la passerelle (ils vivent dans Supabase). */
async function gateway(path: string, method = 'GET') {
  const token = await privateValue('CONFINEMENT_TOKEN');
  return fetch(`${GATEWAY}${path}`, { method, headers: { Authorization: `Bearer ${token}` }, cache: 'no-store', signal: AbortSignal.timeout(8000) });
}

async function open() {
  const { DatabaseSync } = await import('node:sqlite');
  return new DatabaseSync(STATE);
}

/** Mesures en vigueur : outils suspendus pour un agent, packages mis en quarantaine. */
export async function GET(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  try {
    const db = await open();
    const suspensions = db.prepare('select agent_id, tool, incident_id, approved_by from suspensions').all();
    let packages: unknown[] = [];
    try { packages = db.prepare('select package, incident_id, approved_by from quarantined_packages').all(); } catch { /* table créée au prochain démarrage */ }
    db.close();
    let documents: unknown[] = [];
    try { documents = ((await (await gateway('/confinement/documents')).json()) as { documents: unknown[] }).documents ?? []; } catch { /* passerelle arrêtée */ }
    return Response.json({ suspensions, packages, documents }, { headers });
  } catch {
    return Response.json({ suspensions: [], packages: [], documents: [] }, { headers });
  }
}

/** Lève une mesure (décision explicite de l'analyste depuis le château) : `agent` + `tool`, ou `package`. */
export async function DELETE(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Réservé à l’interface locale.' }, { status: 403, headers });
  const q = new URL(request.url).searchParams;
  const agent = q.get('agent') ?? '';
  const tool = q.get('tool') ?? '';
  const pkg = q.get('package') ?? '';
  const doc = q.get('document') ?? '';
  if (doc) {
    if (!/^[0-9a-f-]{36}$/i.test(doc)) return Response.json({ error: 'Document invalide.' }, { status: 400, headers });
    try {
      const r = await gateway(`/confinement/documents/${doc}`, 'DELETE');
      return Response.json(await r.json(), { status: r.status, headers });
    } catch {
      return Response.json({ error: 'Passerelle injoignable.' }, { status: 503, headers });
    }
  }
  try {
    const db = await open();
    let n = 0;
    if (pkg) {
      if (!/^(pypi|npm):[\w@/.-]{1,214}$/.test(pkg)) return Response.json({ error: 'Package invalide.' }, { status: 400, headers });
      n = Number(db.prepare('delete from quarantined_packages where package = ?').run(pkg).changes);
    } else {
      if (!/^[\w.-]{1,100}$/.test(agent) || !/^[\w.-]{1,100}$/.test(tool)) return Response.json({ error: 'Paramètres invalides.' }, { status: 400, headers });
      n = Number(db.prepare('delete from suspensions where agent_id = ? and tool = ?').run(agent, tool).changes);
    }
    db.close();
    return Response.json({ removed: n }, { headers });
  } catch {
    return Response.json({ error: 'État de la passerelle illisible.' }, { status: 503, headers });
  }
}
