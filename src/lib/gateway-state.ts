import 'server-only';
import path from 'node:path';

/** État local de la passerelle (backend/gateway/defense.py) : mesures appliquées sur décision d'un analyste. */
export interface GatewayState {
  suspensions: { agent_id: string; tool: string; incident_id: string; approved_by: string }[];
  packages: { package: string; incident_id: string; approved_by: string }[];
}

const STATE = path.join(process.cwd(), '.runtime', 'gateway-state.sqlite');

export async function openGatewayState() {
  const { DatabaseSync } = await import('node:sqlite');
  return new DatabaseSync(STATE);
}

export async function readGatewayState(): Promise<GatewayState> {
  try {
    const db = await openGatewayState();
    const suspensions = db.prepare('select agent_id, tool, incident_id, approved_by from suspensions').all() as GatewayState['suspensions'];
    let packages: GatewayState['packages'] = [];
    try { packages = db.prepare('select package, incident_id, approved_by from quarantined_packages').all() as GatewayState['packages']; } catch { /* table créée au prochain démarrage */ }
    db.close();
    return { suspensions, packages };
  } catch {
    return { suspensions: [], packages: [] };
  }
}
