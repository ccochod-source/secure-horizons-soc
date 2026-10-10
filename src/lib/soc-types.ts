export type Severity = 'Critique' | 'Élevée' | 'Modérée' | 'Faible' | 'Non renseignée';
export type IncidentStatus = 'À examiner' | 'En enquête' | 'Confiné' | 'Surveillance' | 'En attente de décision' | 'Clos';
export type TraceEvent = {
  id: string; parent_event_id: string | null; timestamp: string;
  actor: string; type: string; title: string; description: string;
  tool: string; resource: string; result: 'allowed' | 'blocked' | 'flagged' | 'unknown'; occurredAt?: string; rawResult?: string;
};
export type Incident = {
  id: string; title: string; agent: string; agentId: string; severity: Severity;
  status: IncidentStatus; time: string; duration: string; description: string;
  evidence: string[]; events: TraceEvent[]; proposal: string; impact: string;
  databaseId?: string; traceId?: string; detectedAt?: string; missingParents?: number; protectionMode?: string;
  storedActions?: import('./soc-data').StoredAction[]; findings?: import('./soc-data').StoredFinding[];
};
export type Agent = {
  id: string; name: string; role: string; owner: string; status: 'À risque' | 'Actif' | 'Suspendu' | 'Inventorié';
  initials: string; tools: string[]; permissions: string[]; lastActivity: string; events: number;
};

