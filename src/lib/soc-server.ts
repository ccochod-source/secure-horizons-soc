import 'server-only';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import type { SocOverview } from './soc-overview';

type RawIncident = { id?: unknown; title?: unknown; severity?: unknown; status?: unknown; decision?: unknown };
type RawEvent = {
  id?: unknown;
  occurred_at?: unknown;
  event_type?: unknown;
  action?: unknown;
  result?: unknown;
  metadata?: unknown;
};

export async function privateValue(name: string, fallback = '') {
  const fromEnvironment = process.env[name];
  if (fromEnvironment) return fromEnvironment;
  for (const filename of ['.env.victim', '.env']) {
    try {
      const content = await readFile(path.join(process.cwd(), filename), 'utf8');
      const line = content.split(/\r?\n/).find((entry) => new RegExp(`^\\s*${name}\\s*=`).test(entry));
      if (!line) continue;
      const value = line.slice(line.indexOf('=') + 1).trim().replace(/^(?:"([\s\S]*)"|'([\s\S]*)')$/, '$1$2');
      if (value) return value;
    } catch {
      // Try the other local environment file without exposing its contents.
    }
  }
  return fallback;
}

export async function localBackendBase() {
  const configured = await privateValue('ALEX_API_URL', (process.env.DEFENSE_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, ''));
  try {
    const url = new URL(configured);
    const loopback = url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
    // En déploiement (ALLOW_PUBLIC_ACCESS=1) on accepte aussi un backend distant en HTTPS.
    const remote = process.env.ALLOW_PUBLIC_ACCESS === '1' && (url.protocol === 'https:' || url.protocol === 'http:');
    if ((loopback || remote) && !url.username && !url.password && !url.search && !url.hash) return url.origin;
  } catch {
    // Invalid configuration means the pipeline is unavailable.
  }
  return '';
}

async function getJson(url: string, headers: HeadersInit = {}) {
  const response = await fetch(url, { headers, cache: 'no-store', signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`Upstream returned ${response.status}`);
  return response.json() as Promise<unknown>;
}

export async function loadSocSnapshot(): Promise<SocOverview> {
  const rawUrl = process.env.SUPABASE_URL || process.env.DATABASE_URL;
  const key = await privateValue('SUPABASE_SERVICE_ROLE_KEY') || await privateValue('service_role_key');
  if (!rawUrl || !key) throw new Error('Renseignez SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY dans le .env du serveur.');
  const url = new URL(rawUrl);
  if (url.protocol !== 'https:' || !url.hostname.endsWith('.supabase.co') || url.username || url.password) {
    throw new Error('SUPABASE_URL doit être l’URL HTTPS du projet Supabase.');
  }

  const supabaseHeaders = { apikey: key, Authorization: `Bearer ${key}` };
  const [documents, rawEvents] = await Promise.all([
    getJson(`${url.origin}/rest/v1/documents?select=id&limit=1`, supabaseHeaders),
    getJson(`${url.origin}/rest/v1/events?select=id,occurred_at,event_type,action,result,metadata&order=occurred_at.desc&limit=8`, supabaseHeaders),
  ]);
  if (!Array.isArray(documents) || !Array.isArray(rawEvents)) throw new Error('Réponse Supabase inattendue.');

  const checkedAt = new Date().toISOString();
  const activity = (rawEvents as RawEvent[]).flatMap((event) => {
    if (typeof event.id !== 'string') return [];
    const metadata = event.metadata && typeof event.metadata === 'object' ? event.metadata as Record<string, unknown> : {};
    const title = typeof metadata.title === 'string' ? metadata.title : typeof event.action === 'string' ? event.action : typeof event.event_type === 'string' ? event.event_type : 'Événement';
    const timestamp = typeof event.occurred_at === 'string' ? event.occurred_at : '';
    return [{
      id: event.id,
      time: timestamp ? new Date(timestamp).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : '—',
      title,
      result: typeof event.result === 'string' ? event.result : '—',
    }];
  });

  const backendBase = await localBackendBase();
  const analystToken = await privateValue('ANALYSTE_TOKEN');
  const victimToken = await privateValue('VICTIM_GATEWAY_TOKEN');
  // Agents actifs : déduits des événements réels tracés (les agents protégés par la passerelle), sur 24 h.
  const agents: SocOverview['agents'] = [];
  const AGENT_PROFILES: Record<string, { name: string; role: string }> = {
    DevBot: { name: 'DevBot — assistant développeur', role: 'Répond aux développeurs derrière la passerelle : coffre, leurres et contrôle des packages' },
    'dev-01': { name: 'Agent d’intégration dev-01', role: 'Introduit et teste des packages via la passerelle' },
  };
  try {
    const since = new Date(Date.now() - 24 * 3600e3).toISOString();
    const rows = await getJson(`${url.origin}/rest/v1/events?select=actor_id,occurred_at&actor_type=eq.agent&occurred_at=gte.${encodeURIComponent(since)}&order=occurred_at.desc&limit=200`, supabaseHeaders);
    if (Array.isArray(rows)) {
      const seen = new Set<string>();
      for (const row of rows as { actor_id?: unknown }[]) {
        const id = typeof row.actor_id === 'string' ? row.actor_id : '';
        if (!id || seen.has(id)) continue;
        seen.add(id);
        const profile = AGENT_PROFILES[id] ?? { name: id, role: 'Agent protégé par la passerelle' };
        agents.push({ id, name: profile.name, role: profile.role });
      }
    }
  } catch { /* La base et le backend restent affichés indépendamment. */ }
  let incidents: SocOverview['incidents'] = [];
  let pipelineConnected = false;
  try {
    if (!backendBase) throw new Error('Backend URL must be loopback HTTP.');
    const headers: HeadersInit = analystToken ? { Authorization: `Bearer ${analystToken}` } : {};
    const [, rawIncidents] = await Promise.all([
      getJson(`${backendBase}/health`),
      getJson(`${backendBase}/incidents`, headers),
    ]);
    if (!Array.isArray(rawIncidents)) throw new Error('Réponse incidents invalide.');
    incidents = (rawIncidents as RawIncident[]).flatMap((incident) => {
      if (typeof incident.id !== 'string' || typeof incident.title !== 'string') return [];
      return [{
        id: incident.id,
        title: incident.title,
        severity: typeof incident.severity === 'string' ? incident.severity : 'À qualifier',
        status: typeof incident.status === 'string' ? incident.status : 'À examiner',
        decision: typeof incident.decision === 'string' ? incident.decision : undefined,
      }];
    });
    pipelineConnected = true;
  } catch {
    // Supabase remains available independently if Alex's API is not running.
  }

  let reviews: SocOverview['reviews'] = [];
  let gatewayConnected = false;
  try {
    const gatewayToken = await privateValue('GATEWAY_TOKEN') || victimToken;
    const data = await getJson(`${(process.env.GATEWAY_API_URL || 'http://127.0.0.1:8002').replace(/\/+$/, '')}/gateway/package-reviews`, {Authorization: `Bearer ${gatewayToken}`}) as {reviews: Record<string, unknown>[]};
    reviews = data.reviews.map(r => ({id: String(r.id), package: String(r.package_name), version: typeof r.version === 'string' ? r.version : '—', status: String(r.state), risk: String(r.risk_level || 'À qualifier')}));
    gatewayConnected = true;
  } catch { /* Display unavailability rather than an empty successful result. */ }
  let knowledgeReviews: SocOverview['knowledgeReviews'] = [];
  let knowledgeConnected = false;
  if (backendBase) {
    try {
      const raw = await getJson(`${backendBase}/knowledge/reviews`,
        analystToken ? { Authorization: `Bearer ${analystToken}` } : {});
      if (!Array.isArray(raw)) throw new Error('Réponse connaissances invalide.');
      knowledgeReviews = raw.flatMap((item: unknown) => {
        if (!item || typeof item !== 'object') return [];
        const row = item as Record<string, unknown>;
        if (typeof row.id !== 'string' || !['documents', 'repo_files'].includes(String(row.source_table))) return [];
        return [{ id: row.id, source_table: row.source_table as 'documents' | 'repo_files',
          title: typeof row.title === 'string' ? row.title : 'Sans titre',
          version: typeof row.version === 'string' ? row.version : null,
          preview: typeof row.preview === 'string' ? row.preview : '',
          review_status: typeof row.review_status === 'string' ? row.review_status : 'pending',
          review_reason: typeof row.review_reason === 'string' ? row.review_reason : null }];
      });
      knowledgeConnected = true;
    } catch { /* L'ancien backend peut encore tourner pendant son redémarrage. */ }
  }
  return {
    updatedAt: checkedAt,
    databaseConnected: true,
    pipelineConnected,
    agents,
    reviews,
    knowledgeConnected,
    knowledgeReviews,
    gatewayConnected,
    incidents,
    activity,
    blockedActions: null,
    completedTests: null,
  };
}
