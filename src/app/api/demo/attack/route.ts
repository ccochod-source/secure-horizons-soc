import { isLocalRequest } from '@/lib/local-request';
import { privateValue } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const gateway = (process.env.GATEWAY_API_URL || 'http://127.0.0.1:8002').replace(/\/+$/, '');
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
const question = "Quel est l'état du déploiement de l'API ?";
const traceIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type DemoOutcome = {
  trace_id?: unknown;
  diverted?: unknown;
  neutralized?: unknown;
  tool_calls?: unknown;
  pipeline_delivery?: unknown;
};

export async function POST(request: Request) {
  if (!isLocalRequest(request)) {
    return Response.json({ error: 'La démonstration est disponible uniquement depuis l’interface locale.' }, { status: 403, headers });
  }
  const token = await privateValue('GATEWAY_TOKEN') || await privateValue('VICTIM_GATEWAY_TOKEN');
  if (!token) {
    return Response.json({ error: 'Le jeton de la passerelle est absent.' }, { status: 503, headers });
  }

  try {
    // The existing victim agent receives a poisoned MCP tool description. Its
    // tool calls go through the gateway; the browser never receives a secret.
    const response = await fetch(`${gateway}/chat`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, poisoned: true, user_id: 'demo-interface' }),
      cache: 'no-store',
      signal: AbortSignal.timeout(180_000),
    });
    if (!response.ok) {
      return Response.json({ error: `Le scénario n’a pas pu démarrer (passerelle HTTP ${response.status}).` },
        { status: 502, headers });
    }
    const raw: unknown = await response.json();
    if (!raw || typeof raw !== 'object') throw new Error('invalid response');
    const outcome = raw as DemoOutcome;
    if (typeof outcome.trace_id !== 'string' || !traceIdPattern.test(outcome.trace_id)) {
      throw new Error('invalid trace');
    }

    let eventTypes: string[] = [];
    try {
      const graph = await fetch(`${gateway}/incidents/${outcome.trace_id}/graph`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store', signal: AbortSignal.timeout(10_000),
      });
      if (graph.ok) {
        const payload: unknown = await graph.json();
        if (payload && typeof payload === 'object' && 'nodes' in payload && Array.isArray(payload.nodes)) {
          eventTypes = payload.nodes.flatMap((node: unknown) => {
            if (!node || typeof node !== 'object' || !('type' in node) || typeof node.type !== 'string') return [];
            return [node.type];
          });
        }
      }
    } catch {
      // The outcome remains useful even if the graph cannot be read.
    }

    const delivery = outcome.pipeline_delivery && typeof outcome.pipeline_delivery === 'object'
      ? outcome.pipeline_delivery as Record<string, unknown> : {};
    const incidentId = typeof delivery.incident_id === 'string' && /^INC-\d+$/.test(delivery.incident_id)
      ? delivery.incident_id : null;
    const toolCalls = Array.isArray(outcome.tool_calls)
      ? outcome.tool_calls.filter((name): name is string => typeof name === 'string' && /^[a-z][a-z0-9_]*$/.test(name)).slice(0, 20)
      : [];
    return Response.json({
      trace_id: outcome.trace_id,
      diverted: outcome.diverted === true,
      neutralized: outcome.neutralized === true,
      tool_calls: toolCalls,
      event_types: eventTypes,
      pipeline_delivery: { status: delivery.status === 'delivered' ? 'delivered' : 'uncertain', incident_id: incidentId },
    }, { headers });
  } catch {
    return Response.json({ error: 'Le scénario est indisponible. Vérifiez que la passerelle tourne sur le port 8002.' },
      { status: 503, headers });
  }
}
