import { isLocalRequest } from '@/lib/local-request';
import { privateValue } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
const GATEWAY = (process.env.GATEWAY_API_URL || 'http://127.0.0.1:8002').replace(/\/+$/, '');

export interface ChatReply {
  answer: string; traceId: string; diverted: boolean; neutralized: boolean; toolCalls: string[];
  incidentId: string | null;
  /** Défenses réellement déclenchées pendant la conversation (événements tracés). */
  defenses: { decoy: boolean; sandbox: boolean; packageBlocked: boolean; outboundBlocked: boolean; secretsMasked: number };
  durationMs: number;
}

/**
 * Conversation réelle avec l'agent DevBot, derrière la passerelle (traçage, coffre, leurres, contrôle des packages),
 * puis relais de la session au backend de défense. `poisoned` connecte en plus le serveur MCP tiers piégé.
 */
export async function POST(request: Request) {
  if (!isLocalRequest(request)) return Response.json({ error: 'Le chat est disponible uniquement depuis l’interface locale.' }, { status: 403, headers });
  let body: { question?: unknown; poisoned?: unknown };
  try { body = await request.json(); } catch { return Response.json({ error: 'Message invalide.' }, { status: 400, headers }); }
  const question = typeof body.question === 'string' ? body.question.trim() : '';
  if (!question || question.length > 4000) return Response.json({ error: 'Le message doit contenir entre 1 et 4 000 caractères.' }, { status: 400, headers });
  const token = (await privateValue('GATEWAY_TOKEN')) || (await privateValue('VICTIM_GATEWAY_TOKEN'));
  if (!token) return Response.json({ error: 'Jeton de la passerelle absent.' }, { status: 503, headers });
  const t0 = Date.now();
  try {
    const r = await fetch(`${GATEWAY}/chat`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, poisoned: body.poisoned === true }), cache: 'no-store', signal: AbortSignal.timeout(300_000),
    });
    const d = (await r.json()) as { trace_id?: string; answer?: string; diverted?: boolean; neutralized?: boolean; tool_calls?: string[]; detail?: string; pipeline_delivery?: { incident_id?: string | null } };
    if (!r.ok || !d.trace_id) return Response.json({ error: d.detail ?? `La passerelle a répondu ${r.status}.` }, { status: r.status >= 500 ? 502 : r.status, headers });
    // défenses déclenchées : relues dans les événements tracés de la session
    const defenses = { decoy: false, sandbox: false, packageBlocked: false, outboundBlocked: false, secretsMasked: 0 };
    const supabase = (await privateValue('SUPABASE_URL')).replace(/\/+$/, '');
    const key = await privateValue('SUPABASE_SERVICE_ROLE_KEY');
    if (supabase && key) {
      try {
        const er = await fetch(`${supabase}/rest/v1/events?select=event_type,action,result,metadata&trace_id=eq.${d.trace_id}`, { headers: { apikey: key, Authorization: `Bearer ${key}` }, cache: 'no-store', signal: AbortSignal.timeout(8000) });
        const evs = er.ok ? ((await er.json()) as { event_type: string; action: string | null; result: string | null; metadata: { tokens?: string[] } | null }[]) : [];
        for (const e of evs) {
          if (e.event_type === 'decoy_access') defenses.decoy = true;
          if (e.event_type === 'session_diverted') defenses.sandbox = true;
          if (e.event_type === 'package_review' && e.result === 'pending') defenses.packageBlocked = true;
          if (e.event_type === 'tool_response' && e.result === 'blocked' && e.action !== 'search_docs') defenses.outboundBlocked = true;
          defenses.secretsMasked += e.metadata?.tokens?.length ?? 0;
        }
      } catch { /* la réponse reste utile sans ce détail */ }
    }
    const reply: ChatReply = {
      answer: d.answer ?? '', traceId: d.trace_id, diverted: !!d.diverted, neutralized: !!d.neutralized, toolCalls: d.tool_calls ?? [],
      incidentId: d.pipeline_delivery?.incident_id ?? null, defenses, durationMs: Date.now() - t0,
    };
    return Response.json(reply, { headers });
  } catch {
    return Response.json({ error: 'Passerelle injoignable (port 8002). Lancer scripts/castle/run_gateway.sh.' }, { status: 503, headers });
  }
}
