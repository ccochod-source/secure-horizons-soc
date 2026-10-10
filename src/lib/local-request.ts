export function isLocalRequest(request: Request) {
  const url = new URL(request.url);
  const localHosts = ['localhost', '127.0.0.1', '[::1]'];
  const host = request.headers.get('host');
  const origin = request.headers.get('origin');
  const site = request.headers.get('sec-fetch-site');
  const forwardedFor = request.headers.get('x-forwarded-for');
  let localOrigin = '';
  try {
    const parsedHost = new URL(`http://${host}`);
    if (localHosts.includes(parsedHost.hostname) && !parsedHost.username && !parsedHost.password) localOrigin = parsedHost.origin;
  } catch {
    return false;
  }
  const localPeer = !forwardedFor || ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(forwardedFor);
  return process.env.NODE_ENV !== 'production'
    && localHosts.includes(url.hostname)
    && !!localOrigin
    && localPeer
    && !request.headers.has('forwarded')
    && (!origin || origin === localOrigin)
    && (!site || ['same-origin', 'none'].includes(site));
}
