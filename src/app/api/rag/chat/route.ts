import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { isLocalRequest } from '@/lib/local-request';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const headers = {
  'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff',
};

async function privateToken() {
  if (process.env.VICTIM_GATEWAY_TOKEN) return process.env.VICTIM_GATEWAY_TOKEN;
  for (const filename of ['.env.victim', '.env']) {
    try {
      const contents = await readFile(path.join(process.cwd(), filename), 'utf8');
      const line = contents.split(/\r?\n/).find((entry) => /^\s*VICTIM_GATEWAY_TOKEN\s*=/.test(entry));
      if (!line) continue;
      const value = line.slice(line.indexOf('=') + 1).trim().replace(/^(?:"([\s\S]*)"|'([\s\S]*)')$/, '$1$2');
      if (value) return value;
    } catch {
      // Try the next local env file. Never include its contents in an error response.
    }
  }
  return '';
}

export async function POST(request: Request) {
  if (!isLocalRequest(request)) {
    return Response.json({ error: 'Le chat RAG est disponible uniquement depuis l’interface locale.' }, { status: 403, headers });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return Response.json({ error: 'La question envoyée est invalide.' }, { status: 400, headers });
  }
  if (!payload || typeof payload !== 'object' || !('question' in payload) || typeof payload.question !== 'string') {
    return Response.json({ error: 'Saisissez une question pour l’assistant.' }, { status: 400, headers });
  }
  const question = payload.question.trim();
  if (!question || question.length > 4000) {
    return Response.json({ error: 'La question doit contenir entre 1 et 4 000 caractères.' }, { status: 400, headers });
  }

  const token = await privateToken();
  if (!token) {
    return Response.json({ error: 'Jeton privé de l’agent absent. Vérifiez la configuration locale.' }, { status: 503, headers });
  }

  try {
    const upstream = await fetch(`${(process.env.RAG_API_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '')}/chat`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, agent_id: 'dev-01' }),
      cache: 'no-store',
      signal: AbortSignal.timeout(95_000),
    });
    const result: unknown = await upstream.json();
    if (!upstream.ok || !result || typeof result !== 'object' || !('answer' in result) || typeof result.answer !== 'string') {
      const message = result && typeof result === 'object' && 'detail' in result && typeof result.detail === 'string'
        ? result.detail
        : 'L’agent RAG n’a pas pu répondre.';
      return Response.json({ error: message }, { status: upstream.status >= 400 && upstream.status < 500 ? upstream.status : 502, headers });
    }
    return Response.json(result, { headers });
  } catch {
    return Response.json({ error: 'Impossible de joindre l’agent RAG. Vérifiez qu’il est lancé sur le port 8001.' }, { status: 503, headers });
  }
}
