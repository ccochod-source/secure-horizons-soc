import { loadSocSnapshot } from '@/lib/soc-server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = {'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};

export async function GET(request: Request) {
  // Temporary gateway for the team's local hackathon console. Fail closed when deployed.
  // This is not enterprise authentication; replace with Supabase Auth + analyst authorization.
  const url=new URL(request.url);
  const loopback=['localhost','127.0.0.1','[::1]'];
  const origin=request.headers.get('origin');
  const site=request.headers.get('sec-fetch-site');
  const host=request.headers.get('host');
  let requestedOrigin='';
  try { const incoming=new URL(`http://${host}`); if(loopback.includes(incoming.hostname) && !incoming.username && !incoming.password) requestedOrigin=incoming.origin; } catch { /* Invalid Host: reject below. */ }
  // Next.js adds x-forwarded-for even to direct connections; accept only a single loopback address.
  const forwardedFor=request.headers.get('x-forwarded-for');
  const localPeer=!forwardedFor || ['127.0.0.1','::1','::ffff:127.0.0.1'].includes(forwardedFor);
  // Déploiement : ALLOW_PUBLIC_ACCESS=1 ouvre l'accès (lecture seule, données agrégées) ; sinon réservé au local.
  const publicAccess=process.env.ALLOW_PUBLIC_ACCESS==='1';
  if(!publicAccess && (process.env.NODE_ENV==='production' || !loopback.includes(url.hostname) || !requestedOrigin || !localPeer || request.headers.has('forwarded') || (origin && origin !== requestedOrigin) || (site && !['same-origin','none'].includes(site)))) {
    return Response.json({error:'Cette connexion est réservée au serveur local de développement. Un accès déployé nécessite une authentification analyste.'},{status:403,headers});
  }
  try { return Response.json(await loadSocSnapshot(),{headers}); }
  catch(error) {
    const message=error instanceof Error && (error.message.startsWith('Lecture Supabase') || error.message.startsWith('Renseignez ') || error.message.startsWith('SUPABASE_URL')) ? error.message : 'Connexion à Supabase indisponible. Vérifiez les accès du serveur.';
    return Response.json({error:message},{status:503,headers});
  }
}
