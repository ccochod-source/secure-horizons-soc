/** Les six blocs du schéma d'architecture (design : architecture_six_blocs_court.svg). */
export type BlockId = 'env' | 'gateway' | 'decoys' | 'packages' | 'inventory' | 'defenders';

/** Sous-étapes des agents défenseurs, dans l'ordre du pipeline (`backend/pipeline.py`). */
export type DefenderStep = 'sentinelle' | 'enqueteur' | 'verificateur' | 'confineur' | 'rapporteur';

export interface TraceStep {
  id: string;
  block: BlockId;
  sub?: DefenderStep;
  /** `done` = fait, `active` = en cours (attente humaine / passerelle), `error` = échec, `skip` = non analysé. */
  state: 'done' | 'active' | 'error' | 'skip';
  label: string;
  detail?: string;
}

/** État agrégé par bloc, pour colorer le schéma. */
export function blockStates(steps: TraceStep[]): Partial<Record<BlockId, TraceStep['state']>> {
  const rank = { done: 0, skip: 1, active: 2, error: 3 } as const;
  const out: Partial<Record<BlockId, TraceStep['state']>> = {};
  for (const s of steps) {
    const cur = out[s.block];
    if (!cur || rank[s.state] > rank[cur]) out[s.block] = s.state;
  }
  return out;
}
