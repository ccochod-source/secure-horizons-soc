import { isLocalRequest } from '@/lib/local-request';
import { privateValue } from '@/lib/soc-server';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
const headers = { 'Cache-Control': 'no-store' };
const base = 'http://127.0.0.1:8002';
export async function POST(request: Request) {
  if (!isLocalRequest(request)) return Response.json({error:'Disponible uniquement en local.'},{status:403,headers});
  let input: Record<string, unknown>;
  try { input = await request.json(); if (!input || typeof input !== 'object') throw Error(); }
  catch { return Response.json({error:'Demande invalide.'},{status:400,headers}); }
  try {
    if (input.operation === 'login') {
      if (typeof input.email !== 'string' || typeof input.password !== 'string' || input.email.length > 254 || input.password.length > 500)
        return Response.json({error:'Identifiants invalides.'},{status:400,headers});
      const url = await privateValue('SUPABASE_URL');
      const key = await privateValue('SUPABASE_ANON_KEY') || await privateValue('anon_key') || await privateValue('SUPABASE_SERVICE_ROLE_KEY');
      const r = await fetch(`${url}/auth/v1/token?grant_type=password`,{method:'POST',headers:{apikey:key,'Content-Type':'application/json'},body:JSON.stringify({email:input.email,password:input.password}),signal:AbortSignal.timeout(10000)});
      if (!r.ok) return Response.json({error:'Connexion analyste refusée.'},{status:401,headers});
      const data = await r.json();
      return Response.json({access_token:data.access_token},{headers});
    }
    const token = await privateValue('GATEWAY_TOKEN') || await privateValue('VICTIM_GATEWAY_TOKEN');
    const auth = {Authorization:`Bearer ${token}`,'Content-Type':'application/json'};
    if (input.operation === 'review') {
      if (typeof input.name !== 'string' || !/^[a-zA-Z0-9@/_.-]{1,214}$/.test(input.name) || !['npm','pypi'].includes(String(input.ecosystem)))
        return Response.json({error:'Nom ou registre invalide.'},{status:400,headers});
      const session = await fetch(`${base}/gateway/sessions`,{method:'POST',headers:auth,body:JSON.stringify({agent_id:'dev-01',query:`Vérifier le package ${input.name}`}),signal:AbortSignal.timeout(10000)});
      if (!session.ok) throw Error();
      const {trace_id} = await session.json();
      const r = await fetch(`${base}/gateway/sessions/${trace_id}/tools/install_package`,{method:'POST',headers:auth,body:JSON.stringify({arguments:{name:input.name,ecosystem:input.ecosystem}}),signal:AbortSignal.timeout(90000)});
      const result = await r.json();
      const delivery = await fetch(`${base}/gateway/sessions/${trace_id}/complete`,{method:'POST',headers:auth,signal:AbortSignal.timeout(100000)});
      return Response.json({result:result.result,pipeline_delivery:await delivery.json()},{status:r.ok?200:502,headers});
    }
    if (input.operation === 'decision') {
      if (typeof input.id !== 'string' || !/^[0-9a-f-]{36}$/i.test(input.id) || !['approve','reject'].includes(String(input.decision)))
        return Response.json({error:'Décision invalide.'},{status:400,headers});
      const access = request.headers.get('Authorization') || '';
      if (!access.startsWith('Bearer ')) return Response.json({error:'Connectez-vous avec un compte analyste.'},{status:401,headers});
      const r = await fetch(`${base}/packages/${input.id}/decision`,{method:'POST',headers:{Authorization:access,'Content-Type':'application/json'},body:JSON.stringify({decision:input.decision}),signal:AbortSignal.timeout(90000)});
      if (!r.ok) return Response.json({error:r.status===403?'Ce compte n’a pas le droit de valider les packages.':'Décision refusée ou connexion expirée.'},{status:r.status,headers});
      return Response.json(await r.json(),{headers});
    }
    return Response.json({error:'Opération inconnue.'},{status:400,headers});
  } catch { return Response.json({error:'Service packages indisponible. Vérifier la passerelle sur le port 8002.'},{status:503,headers}); }
}
