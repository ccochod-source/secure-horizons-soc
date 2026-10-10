import 'server-only';
import { unconnectedOverview } from './soc-overview';

export async function loadSocSnapshot() {
  const rawUrl = process.env.SUPABASE_URL || process.env.DATABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.service_role_key;
  if (!rawUrl || !key) throw new Error('Renseignez SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY dans le .env du serveur.');
  const url = new URL(rawUrl);
  if (url.protocol !== 'https:' || !url.hostname.endsWith('.supabase.co') || url.username || url.password) {
    throw new Error('SUPABASE_URL doit être l’URL HTTPS du projet Supabase.');
  }

  // Only test the existing database connection. Do not expose prepared demo rows
  // or infer active agents from inventory. No database changes or secret reads.
  const response = await fetch(`${url.origin}/rest/v1/inventory?select=id&limit=1`, {
    headers: { apikey: key, Authorization: `Bearer ${key}` },
    cache: 'no-store', signal: AbortSignal.timeout(12000),
  });
  if (!response.ok) throw new Error(`Lecture Supabase impossible (inventory, HTTP ${response.status}).`);
  const data: unknown = await response.json();
  if (!Array.isArray(data)) throw new Error('Réponse Supabase inattendue.');

  // The team's actual agent endpoints and provenance must be integrated before
  // publishing runtime results. This is not a user-toggleable simulation mode.
  return unconnectedOverview(new Date().toISOString());
}
