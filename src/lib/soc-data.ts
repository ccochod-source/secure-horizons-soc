import type { Agent, Incident, Severity, IncidentStatus, TraceEvent } from './soc-types';

export type StoredAction = { id: string; type: string; target: string; status: string; mode: string; decidedBy: string | null; decidedAt: string | null; note: string | null };
export type StoredFinding = { id: string; claim: string; status: string; evidence: string[]; missingEvidence: string[] };
export type Benchmark = { scenario: string; without: string; with: string; events: number; measured: boolean };
export type SocSnapshot = { incidents: Incident[]; agents: Agent[]; benchmarks: Benchmark[]; updatedAt: string; warnings: string[] };
export type DbRow = Record<string, unknown>;
export type SocRows = { incidents: DbRow[]; events: DbRow[]; inventory: DbRow[]; access: DbRow[]; alerts: DbRow[]; findings: DbRow[]; actions: DbRow[]; runs: DbRow[]; scenarios: DbRow[] };

export function text(value: unknown, fallback = ''): string { return typeof value === 'string' ? value : fallback; }
function strings(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []; }
export function redact(value: string): string {
  return value.replace(/\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b/g, '[SECRET MASQUÉ]')
    .replace(/((?:password|api[_-]?key|secret|access[_-]?token|authorization)\s*[:=]\s*)[^\s,;]+/gi, '$1[MASQUÉ]')
    .slice(0, 5000);
}
function clean(value: unknown, fallback = '') { return redact(text(value, fallback)); }
function clock(value: unknown) { const date = new Date(text(value)); return Number.isNaN(date.valueOf()) ? '—' : date.toLocaleTimeString('fr-FR', {timeZone: 'Europe/Paris', hour:'2-digit', minute:'2-digit', second:'2-digit'}); }
function severity(value: unknown): Severity { return ({critical:'Critique', high:'Élevée', medium:'Modérée', low:'Faible'} as Record<string, Severity>)[text(value)] || 'Non renseignée'; }
function status(value: unknown): IncidentStatus { return ({open:'À examiner', investigating:'En enquête', awaiting_decision:'En attente de décision', contained:'Confiné', monitoring:'Surveillance', closed:'Clos'} as Record<string, IncidentStatus>)[text(value)] || 'À examiner'; }
const actionLabels: Record<string, string> = {block_export:'Bloquer les exports', suspend_mcp_tool:'Suspendre l’outil', set_agent_read_only:'Passer l’agent en lecture seule', revoke_token:'Révoquer le jeton', quarantine_document:'Mettre la source en quarantaine', revoke_key:'Révoquer la clé', quarantine_dependency:'Mettre la dépendance en quarantaine'};

export function mapSocRows(rows: SocRows): SocSnapshot {
  const inventory = new Map(rows.inventory.map(row => [text(row.id), row]));
  const alertIncident = new Map(rows.alerts.map(row => [text(row.id), text(row.incident_id) || text(rows.incidents.find(item => item.trace_id === row.trace_id)?.id)]));
  const incidentFor = (row: DbRow) => text(row.incident_id) || alertIncident.get(text(row.alert_id));
  const eventsFor = (trace: unknown) => rows.events.filter(row => row.trace_id === trace).sort((a,b) => text(a.occurred_at).localeCompare(text(b.occurred_at)) || text(a.id).localeCompare(text(b.id)));
  const incidents: Incident[] = rows.incidents.map(row => {
    const eventRows = eventsFor(row.trace_id);
    const events: TraceEvent[] = eventRows.map(event => ({id:text(event.id),parent_event_id: text(event.parent_event_id) || null,timestamp:clock(event.occurred_at),occurredAt:text(event.occurred_at),actor:clean(event.actor_id),type:clean(event.event_type),title:clean(event.action, text(event.event_type)),description:'Contenu brut non transmis au navigateur. Consultez les références et le résultat de cette interaction.',tool:clean(event.resource_type === 'mcp_tool' ? event.resource_id : event.action, 'Non renseigné'),resource:clean(event.resource_id, 'Non renseignée'),result:event.result === 'blocked'?'blocked': ['detected','flagged','denied'].includes(text(event.result))?'flagged': ['allowed','success'].includes(text(event.result))?'allowed':'unknown',rawResult:clean(event.result, 'Non renseigné')}));
    const eventIds = new Set(events.map(event => event.id));
    const findings: StoredFinding[] = rows.findings.filter(item => incidentFor(item) === row.id).map(item => ({id:text(item.id),claim:clean(item.claim),status:clean(item.verification_status),evidence:strings(item.evidence_event_ids).filter(id => eventIds.has(id)),missingEvidence:strings(item.evidence_event_ids).filter(id => !eventIds.has(id))}));
    const actions: StoredAction[] = rows.actions.filter(item => incidentFor(item) === row.id).map(item => ({id:text(item.id),type:clean(item.action_type),target:clean(item.target),status:clean(item.status),mode:clean(item.mode),decidedBy:clean(item.decided_by) || null,decidedAt:text(item.decided_at) || null,note:clean(item.decision_note) || null}));
    const pending = actions.find(item => ['proposed','pending_approval'].includes(item.status));
    const agent = rows.inventory.find(item => item.kind === 'agent' && item.name === row.agent);
    const evidence = [...new Set(findings.flatMap(item => item.evidence))];
    const missingParents = events.filter(event => event.parent_event_id && !eventIds.has(event.parent_event_id)).length;
    const start = Date.parse(text(eventRows[0]?.occurred_at));
    const end = Date.parse(text(eventRows.at(-1)?.occurred_at));
    return {id:text(row.reference, text(row.id)),databaseId:text(row.id),traceId:text(row.trace_id),detectedAt:text(row.detected_at),title:clean(row.title),agent:clean(row.agent),agentId:text(agent?.id, text(row.agent)),severity:severity(row.severity),status:status(row.status),time:clock(row.detected_at).slice(0,5),duration:Number.isFinite(end-start)?`${Math.max(0,Math.round((end-start)/1000))} secondes`:'Non mesurée',description:clean(row.summary, 'Aucun résumé disponible.'),evidence,events,proposal:pending?`${actionLabels[pending.type] || pending.type} : ${pending.target}`:'Aucune action proposée en attente.',impact:pending?'Action proposée dans la base ; son exécution nécessite le pipeline et une validation authentifiée.':'Les actions déjà enregistrées sont consultables ci-dessous.',storedActions:actions,findings,missingParents,protectionMode:clean(row.protection_mode)};
  });
  const agents: Agent[] = rows.inventory.filter(row => row.kind === 'agent').map(row => {
    const grants = rows.access.filter(item => item.subject_id === row.id);
    const linked = incidents.filter(item => item.agentId === row.id);
    const activity = rows.events.filter(item => item.actor_id === row.name).sort((a,b) => text(b.occurred_at).localeCompare(text(a.occurred_at)));
    return {id:text(row.id),name:clean(row.name),role:clean(row.description, text(row.role_name, 'Rôle non renseigné')),owner:row.is_defender?'Équipe défense':'Équipe développement',status:linked.some(item => !['Confiné','Clos'].includes(item.status))?'À risque':'Inventorié',initials:text(row.name).slice(0,2).toUpperCase(),tools:[...new Set(grants.map(item => clean(inventory.get(text(item.object_id))?.name, text(item.object_id))))],permissions:grants.flatMap(item => strings(item.granted_actions).map(action => `${clean(inventory.get(text(item.object_id))?.name, text(item.object_id))} : ${redact(action)}`)),lastActivity:clock(activity[0]?.occurred_at),events:activity.length};
  });
  const latest = new Map<string, DbRow>();
  for (const run of rows.runs) { const key = `${text(run.scenario_id)}:${text(run.protection_mode)}`; if (!latest.has(key)) latest.set(key,run); }
  const outcome = (run: DbRow | undefined) => !run ? 'Aucune exécution enregistrée' : !run.ended_at ? 'Exécution en cours' : `${Number(run.exports_blocked)||0} export(s) bloqué(s) · ${Number(run.exports_allowed)||0} autorisé(s)`;
  const benchmarks = rows.scenarios.map(row => { const bare=latest.get(`${text(row.id)}:unprotected`); const protectedRun=latest.get(`${text(row.id)}:protected`);return {scenario:clean(row.name),without:outcome(bare),with:outcome(protectedRun),events:rows.events.filter(event => event.run_id === protectedRun?.id && protectedRun).length,measured:!!(bare?.ended_at && protectedRun?.ended_at)}; });
  return {incidents,agents,benchmarks,updatedAt:new Date().toISOString(),warnings:[]};
}
