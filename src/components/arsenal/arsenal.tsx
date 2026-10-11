'use client';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Castle, LayoutDashboard, Terminal, ShieldCheck, Swords, Gavel, Play, Loader2, Check, X, Lock, FileWarning, PackageX, Bug, UserCheck, RefreshCw } from 'lucide-react';
import { ATTACKS, DANGER_CHIP, DANGER_LABEL, type Attack } from '@/castle/arsenal-catalog';
import type { PendingQueue } from '@/app/api/arsenal/pending/route';

type LaunchResult = {
  kind?: string; message?: string; status?: string; risk?: string | null; recommendation?: string | null;
  incidentId?: string | null; reviewId?: string | null; docId?: string; title?: string;
  diverted?: boolean; neutralized?: boolean; answer?: string; toolCalls?: string[];
  defenses?: { decoy: boolean; sandbox: boolean; packageBlocked: boolean; outboundBlocked: boolean; secretsMasked: number };
  error?: string;
};
type Slot = { loading: boolean; result?: LaunchResult; verdict?: string };
const GROUP_ICON = { Connaissances: FileWarning, Packages: PackageX, Agent: Bug } as const;

type Step = { who: string; text: string; tone?: 'danger' | 'success' | 'info' | 'muted' };

/** Raconte, étape par étape, ce qui se passe réellement pendant l'attaque, à partir du résultat réel. */
function narrate(a: Attack, res: LaunchResult, queue: PendingQueue | null): Step[] {
  const steps: Step[] = [{ who: 'Attaquant', text: a.desc, tone: 'muted' }];
  if (res.kind === 'document') {
    steps.push({ who: 'Passerelle', text: `Le document « ${res.title ?? a.title} » est déposé dans la base de connaissances.` });
    steps.push({ who: 'Admission des connaissances', text: 'Avant toute lecture par l’agent, j’analyse le contenu : règles de sécurité d’abord, puis l’IA, en traitant le document comme une simple donnée (jamais une consigne).' });
    const doc = queue?.documents.find((d) => d.id === res.docId);
    if (doc?.status === 'quarantined') steps.push({ who: 'Verdict', text: `Mis en quarantaine. Motif : ${doc.reason ?? 'contenu suspect'}. L’agent ne pourra pas le lire.`, tone: 'danger' });
    else if (doc?.status === 'pending' || (res.status === 'pending' && !doc)) steps.push({ who: 'Verdict', text: 'Analyse en cours… (rafraîchissez dans un instant).', tone: 'info' });
    else if (res.docId && !doc) steps.push({ who: 'Verdict', text: 'Admis : aucune menace détectée, le document devient consultable par l’agent.', tone: 'success' });
    steps.push({ who: 'Décision humaine', text: 'Un analyste peut confirmer la quarantaine (refuser) ou lever le doute (approuver).' });
  } else if (res.kind === 'package') {
    steps.push({ who: 'Agent développeur', text: `J’installe le package « ${a.name} »${a.version ? ` (version ${a.version})` : ''}.` });
    steps.push({ who: 'Passerelle', text: 'install_package n’est jamais relayé tel quel à l’écosystème : j’intercepte la demande.' });
    steps.push({ who: 'Contrôle des packages', text: `Je vérifie le nom et la version sur ${a.ecosystem === 'npm' ? 'npm' : 'PyPI'} et la base de vulnérabilités OSV.` });
    const pkg = queue?.packages.find((p) => p.id === res.reviewId);
    const verdict = `${res.status === 'blocked_pending_review' ? 'Bloqué' : res.status ?? 'traité'}.${pkg?.recommendation ? ` ${pkg.recommendation}` : ''}${pkg?.risk ? ` (risque : ${pkg.risk})` : ''}`;
    steps.push({ who: 'Verdict', text: verdict, tone: res.status === 'blocked_pending_review' ? 'danger' : 'info' });
    steps.push({ who: 'Passerelle', text: 'Le package n’a jamais été exécuté : seulement téléchargé en quarantaine pour analyse statique.', tone: 'muted' });
    steps.push({ who: 'Décision humaine', text: 'Un analyste décide de l’approuver ou de le refuser définitivement.' });
  } else {
    steps.push({ who: 'Vous', text: a.question ?? '' });
    steps.push({ who: 'Passerelle', text: 'Je trace la session, je masque les secrets du coffre et je surveille la couche de leurres.' });
    if (res.defenses?.decoy) steps.push({ who: 'Couche de leurres', text: 'Un leurre a été touché : la session est traitée comme compromise.', tone: 'danger' });
    if (res.diverted || res.defenses?.sandbox) steps.push({ who: 'Bac à sable', text: 'La session est confinée : elle ne touche plus rien de réel.', tone: 'danger' });
    if (res.defenses?.packageBlocked) steps.push({ who: 'Contrôle des packages', text: 'Un package demandé pendant la conversation a été bloqué.', tone: 'danger' });
    if (res.defenses?.outboundBlocked) steps.push({ who: 'Passerelle', text: 'Un envoi vers l’extérieur a été bloqué.', tone: 'danger' });
    if (res.defenses?.secretsMasked) steps.push({ who: 'Coffre', text: `${res.defenses.secretsMasked} secret(s) masqué(s) avant tout envoi au modèle.`, tone: 'info' });
    if (res.answer) steps.push({ who: 'Agent', text: res.answer });
    const clean = !res.defenses?.decoy && !res.diverted && !res.defenses?.packageBlocked && !res.defenses?.outboundBlocked && !res.defenses?.secretsMasked;
    if (clean && res.answer) steps.push({ who: 'Passerelle', text: 'Requête légitime : aucune défense n’a eu à se déclencher.', tone: 'success' });
    if (res.incidentId) steps.push({ who: 'Agents défenseurs', text: `Incident ${res.incidentId} ouvert : enquête puis mesure proposée à un analyste.`, tone: 'info' });
  }
  return steps;
}
const STEP_COLOR: Record<string, string> = { danger: 'var(--danger)', success: 'var(--success)', info: 'var(--brand-500)', muted: 'var(--text-2, #8a8a99)' };

export function Arsenal() {
  const [queue, setQueue] = useState<PendingQueue | null>(null);
  const [queueErr, setQueueErr] = useState('');
  const [slots, setSlots] = useState<Record<string, Slot>>({});
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // identité analyste : jeton gardé en mémoire uniquement (jamais journalisé)
  const [token, setToken] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loginErr, setLoginErr] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [flash, setFlash] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const r = await fetch('/api/arsenal/pending', { cache: 'no-store' });
        const d = (await r.json()) as PendingQueue & { error?: string };
        if (stop) return;
        if (!r.ok) { setQueueErr(d.error ?? `Erreur ${r.status}`); return; }
        setQueue(d); setQueueErr('');
      } catch (e) { if (!stop) setQueueErr(e instanceof Error ? e.message : String(e)); }
    };
    void load();
    const id = setInterval(load, 8000);
    return () => { stop = true; clearInterval(id); };
  }, [tick]);

  useEffect(() => { if (!flash) return; const id = setTimeout(() => setFlash(null), 4000); return () => clearTimeout(id); }, [flash]);

  const login = async () => {
    setLoginErr(''); setLoginBusy(true);
    try {
      const r = await fetch('/api/packages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ operation: 'login', email, password }) });
      const d = (await r.json()) as { access_token?: string; error?: string };
      if (!r.ok || !d.access_token) { setLoginErr(d.error ?? 'Connexion refusée.'); return; }
      setToken(d.access_token); setPassword('');
    } catch { setLoginErr('Service d’authentification indisponible.'); }
    finally { setLoginBusy(false); }
  };

  const launch = async (a: Attack) => {
    setSlots((s) => ({ ...s, [a.id]: { loading: true } }));
    try {
      const r = await fetch('/api/arsenal/launch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: a.id }) });
      const d = (await r.json()) as LaunchResult;
      setSlots((s) => ({ ...s, [a.id]: { loading: false, result: d } }));
    } catch (e) {
      setSlots((s) => ({ ...s, [a.id]: { loading: false, result: { error: e instanceof Error ? e.message : String(e) } } }));
    }
    setTimeout(refresh, 1500);
  };

  // décisions
  const decide = async (key: string, fn: () => Promise<Response>, label: string, onDone?: () => void) => {
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      const r = await fn();
      const d = (await r.json()) as { error?: string };
      if (!r.ok) setFlash({ ok: false, text: d.error ?? `Erreur ${r.status}` });
      else { setFlash({ ok: true, text: `${label} : décision enregistrée.` }); onDone?.(); refresh(); }
    } catch { setFlash({ ok: false, text: 'Service de décision injoignable.' }); }
    finally { setBusy((b) => ({ ...b, [key]: false })); }
  };
  const markSlot = (attackId: string, verdict: string) => setSlots((s) => ({ ...s, [attackId]: { ...s[attackId], verdict } }));
  const auth: Record<string, string> = token ? { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } : { 'Content-Type': 'application/json' };
  const decideDoc = (id: string, decision: 'approve' | 'reject') => decide(`doc-${id}`, () => fetch('/api/castle/knowledge', { method: 'POST', headers: auth, body: JSON.stringify({ op: 'decide', id, decision }) }), 'Document');
  const decidePkg = (id: string, decision: 'approve' | 'reject') => decide(`pkg-${id}`, () => fetch('/api/packages', { method: 'POST', headers: auth, body: JSON.stringify({ operation: 'decision', id, decision }) }), 'Package');
  const decideInc = (id: string, decision: 'approved' | 'rejected') => decide(`inc-${id}`, () => fetch('/api/incidents/decision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, decision }) }), 'Incident');
  const decideCv = (id: string, maintenir: boolean) => decide(`cv-${id}`, () => fetch('/api/castle/reverification', { method: 'POST', headers: auth, body: JSON.stringify({ id, maintenir }) }), 'Contre-vérification');

  const groups = useMemo(() => {
    const by: Record<string, Attack[]> = {};
    for (const a of ATTACKS) (by[a.group] ??= []).push(a);
    return Object.entries(by);
  }, []);
  const pendingTotal = queue ? queue.documents.length + queue.packages.length + queue.incidents.length + queue.reverifications.length : 0;

  return (
    <div className="ds">
      <div className="ds-app">
        <aside className="ds-sidebar">
          <div className="ds-logo"><div className="ds-logo-mark"><ShieldCheck size={16} strokeWidth={2} /></div><span className="ds-logo-word">TRACE.</span></div>
          <div className="overline" style={{ padding: '0 14px 6px' }}>Pilotage</div>
          <Link href="/" className="ds-nav"><LayoutDashboard size={20} strokeWidth={1.75} /><span>Tableau de bord</span></Link>
          <Link href="/castle" className="ds-nav"><Castle size={20} strokeWidth={1.75} /><span>Château</span></Link>
          <div className="overline" style={{ padding: '14px 14px 6px' }}>Outils</div>
          <Link href="/arsenal" className="ds-nav active"><Swords size={20} strokeWidth={1.75} /><span>Arsenal</span>{pendingTotal > 0 && <span className="ds-count">{pendingTotal}</span>}</Link>
          <Link href="/console" className="ds-nav"><Terminal size={20} strokeWidth={1.75} /><span>Console SOC</span></Link>
          <div style={{ marginTop: 'auto', padding: '0 14px 56px' }} className="caption faint">
            <span className="dot" style={{ background: queue?.health.gateway ? 'var(--success)' : 'var(--danger)', marginRight: 6 }} />passerelle
            <br /><span className="dot" style={{ background: queue?.health.defense ? 'var(--success)' : 'var(--danger)', marginRight: 6 }} />défense
          </div>
        </aside>

        <main className="ds-main">
          <header className="ds-topbar">
            <div className="title-block">
              <p className="body muted">Simulations d’attaque autorisées · environnement de test</p>
              <h1 className="display-xl">Arsenal & centre de décision</h1>
            </div>
            <button className="btn btn-sm btn-ghost" onClick={refresh} title="Rafraîchir"><RefreshCw size={15} /> Rafraîchir</button>
          </header>

          {flash && <div className={`ds-card c12 ${flash.ok ? 'tint-success' : 'tint-danger'}`} style={{ marginBottom: 16 }}><strong style={{ color: flash.ok ? 'var(--success)' : 'var(--danger)' }}>{flash.ok ? 'Fait' : 'Échec'}</strong><p className="body-sm">{flash.text}</p></div>}

          <div className="ds-grid">
            {/* ---------- Lanceur d'attaques ---------- */}
            <div className="ds-card c7">
              <div className="ds-card-head"><div className="grow"><h2 className="h2"><Swords size={18} style={{ verticalAlign: '-3px', marginRight: 6 }} />Lancer une attaque</h2><p className="body-sm">De vraies attaques, avec de vraies données, qui touchent réellement la base, la passerelle et les agents. Les packages ne sont jamais exécutés.</p></div></div>
              {groups.map(([group, items]) => {
                const Icon = GROUP_ICON[group as keyof typeof GROUP_ICON] ?? Bug;
                return (
                  <div key={group} style={{ marginBottom: 18 }}>
                    <div className="overline" style={{ marginBottom: 8 }}><Icon size={13} style={{ verticalAlign: '-2px', marginRight: 5 }} />{group}</div>
                    <div style={{ display: 'grid', gap: 10 }}>
                      {items.map((a) => {
                        const slot = slots[a.id];
                        const res = slot?.result;
                        return (
                          <div key={a.id} className="ds-card" style={{ padding: 14, boxShadow: 'none', border: '1px solid var(--line)' }}>
                            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                  <strong className="body">{a.title}</strong>
                                  <span className={`chip ${DANGER_CHIP[a.danger]}`}>{DANGER_LABEL[a.danger]}</span>
                                </div>
                                <p className="body-sm" style={{ marginTop: 4 }}>{a.desc}</p>
                                <p className="caption faint" style={{ marginTop: 4 }}>Attendu : {a.expect}</p>
                              </div>
                              <button className="btn btn-sm btn-primary" disabled={slot?.loading} onClick={() => launch(a)} style={{ flexShrink: 0 }}>
                                {slot?.loading ? <Loader2 size={15} className="spin" /> : <Play size={15} />}{slot?.loading ? 'En cours' : 'Lancer'}
                              </button>
                            </div>
                            {res && (
                              <div className="ds-card" style={{ marginTop: 10, padding: 10, boxShadow: 'none', background: 'var(--surface-2, #f6f6fb)' }}>
                                {res.error ? <p className="body-sm" style={{ color: 'var(--danger)' }}>{res.error}</p> : (
                                  <>
                                    <p className="body-sm">{res.message}</p>
                                    <div style={{ marginTop: 8, display: 'grid', gap: 7 }}>
                                      {narrate(a, res, queue).map((s, i) => (
                                        <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                                          <span style={{ flexShrink: 0, minWidth: 132, fontSize: 11, fontWeight: 600, color: STEP_COLOR[s.tone ?? ''] ?? 'var(--text)' }}>{s.who}</span>
                                          <span className="body-sm" style={{ whiteSpace: 'pre-wrap' }}>{s.who === 'Agent' && s.text.length > 320 ? `${s.text.slice(0, 320)}…` : s.text}</span>
                                        </div>
                                      ))}
                                    </div>
                                    {slot?.verdict ? (
                                      <p className="caption" style={{ marginTop: 8, color: 'var(--success)' }}><Check size={12} /> Décision prise : {slot.verdict}</p>
                                    ) : (res.reviewId || res.docId || res.incidentId) ? (
                                      <div style={{ marginTop: 8, borderTop: '1px solid var(--line)', paddingTop: 8 }}>
                                        <div className="overline" style={{ marginBottom: 6 }}>Décision requise maintenant{(res.reviewId || res.docId) && !token ? ' · connectez-vous en analyste' : ''}</div>
                                        {res.kind === 'package' && res.reviewId && (
                                          <Act busy={!!busy[`pkg-${res.reviewId}`]} disabled={!token}
                                            onApprove={() => decide(`pkg-${res.reviewId}`, () => fetch('/api/packages', { method: 'POST', headers: auth, body: JSON.stringify({ operation: 'decision', id: res.reviewId, decision: 'approve' }) }), 'Package', () => markSlot(a.id, 'package approuvé'))}
                                            onReject={() => decide(`pkg-${res.reviewId}`, () => fetch('/api/packages', { method: 'POST', headers: auth, body: JSON.stringify({ operation: 'decision', id: res.reviewId, decision: 'reject' }) }), 'Package', () => markSlot(a.id, 'package refusé'))} />
                                        )}
                                        {res.kind === 'document' && res.docId && (
                                          <Act busy={!!busy[`doc-${res.docId}`]} disabled={!token}
                                            onApprove={() => decide(`doc-${res.docId}`, () => fetch('/api/castle/knowledge', { method: 'POST', headers: auth, body: JSON.stringify({ op: 'decide', id: res.docId, decision: 'approve' }) }), 'Document', () => markSlot(a.id, 'document admis'))}
                                            onReject={() => decide(`doc-${res.docId}`, () => fetch('/api/castle/knowledge', { method: 'POST', headers: auth, body: JSON.stringify({ op: 'decide', id: res.docId, decision: 'reject' }) }), 'Document', () => markSlot(a.id, 'document rejeté'))} />
                                        )}
                                        {res.incidentId && (
                                          <Act busy={!!busy[`inc-${res.incidentId}`]} approveLabel="Appliquer la mesure" rejectLabel="Rejeter"
                                            onApprove={() => decide(`inc-${res.incidentId}`, () => fetch('/api/incidents/decision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: res.incidentId, decision: 'approved' }) }), 'Incident', () => markSlot(a.id, 'mesure appliquée'))}
                                            onReject={() => decide(`inc-${res.incidentId}`, () => fetch('/api/incidents/decision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: res.incidentId, decision: 'rejected' }) }), 'Incident', () => markSlot(a.id, 'mesure rejetée'))} />
                                        )}
                                      </div>
                                    ) : null}
                                  </>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* ---------- Centre de décision ---------- */}
            <div className="ds-card c5" style={{ alignSelf: 'start' }}>
              <div className="ds-card-head"><div className="grow"><h2 className="h2"><Gavel size={18} style={{ verticalAlign: '-3px', marginRight: 6 }} />Centre de décision</h2><p className="body-sm">Accepter ou refuser l’arrivée de toute donnée, tous types confondus. {pendingTotal} en attente.</p></div></div>
              {queueErr && <p className="body-sm" style={{ color: 'var(--danger)' }}>{queueErr}</p>}

              {/* identité analyste */}
              <div className="ds-card" style={{ padding: 12, boxShadow: 'none', border: '1px solid var(--line)', marginBottom: 14 }}>
                <div className="overline" style={{ marginBottom: 6 }}><UserCheck size={13} style={{ verticalAlign: '-2px', marginRight: 5 }} />Identité analyste</div>
                {token ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                    <span className="chip success"><Check size={12} /> connecté</span>
                    <button className="btn btn-sm btn-ghost" onClick={() => setToken('')}>Se déconnecter</button>
                  </div>
                ) : (
                  <>
                    <p className="caption faint" style={{ marginBottom: 8 }}>Requis pour les documents, les packages et les contre-vérifications. Les incidents sont tranchés avec le jeton du serveur.</p>
                    <div style={{ display: 'grid', gap: 6 }}>
                      <input className="ds-input" type="email" placeholder="email analyste" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" style={inputStyle} />
                      <input className="ds-input" type="password" placeholder="mot de passe" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" style={inputStyle} onKeyDown={(e) => { if (e.key === 'Enter') void login(); }} />
                      <button className="btn btn-sm btn-primary" disabled={loginBusy || !email || !password} onClick={login}>{loginBusy ? <Loader2 size={14} className="spin" /> : <Lock size={14} />} Se connecter</button>
                      {loginErr && <p className="caption" style={{ color: 'var(--danger)' }}>{loginErr}</p>}
                    </div>
                  </>
                )}
              </div>

              <div style={{ display: 'grid', gap: 14 }}>
                <Section title="Documents / connaissances" count={queue?.documents.length ?? 0} empty="Aucun document en attente.">
                  {queue?.documents.map((d) => (
                    <Item key={d.id} title={d.title} chip={<span className={`chip ${d.status === 'quarantined' ? 'danger' : 'warning'}`}>{d.status}</span>}
                      lines={[d.reason ? `Motif : ${d.reason}` : null, d.preview ? `« ${d.preview.slice(0, 120)}… »` : null]}>
                      <Act busy={!!busy[`doc-${d.id}`]} onApprove={() => decideDoc(d.id, 'approve')} onReject={() => decideDoc(d.id, 'reject')} disabled={!token} />
                    </Item>
                  ))}
                </Section>
                <Section title="Packages" count={queue?.packages.length ?? 0} empty="Aucun package en attente.">
                  {queue?.packages.map((p) => (
                    <Item key={p.id} title={`${p.package}${p.version && p.version !== '—' ? `@${p.version}` : ''}`} chip={p.risk ? <span className="chip warning">{p.risk}</span> : <span className="chip">{p.status}</span>}
                      lines={[p.recommendation ? `Recommandation : ${p.recommendation}` : null]}>
                      <Act busy={!!busy[`pkg-${p.id}`]} onApprove={() => decidePkg(p.id, 'approve')} onReject={() => decidePkg(p.id, 'reject')} disabled={!token} />
                    </Item>
                  ))}
                </Section>
                <Section title="Incidents" count={queue?.incidents.length ?? 0} empty="Aucun incident à trancher.">
                  {queue?.incidents.map((i) => (
                    <Item key={i.id} title={`${i.id} · ${i.title}`} chip={<span className="chip info">{Math.round(i.confidence * 100)} %</span>}
                      lines={[i.severity ? `Gravité : ${i.severity}` : null, i.proposal ? `Mesure proposée : ${i.proposal}` : null]}>
                      <Act busy={!!busy[`inc-${i.id}`]} onApprove={() => decideInc(i.id, 'approved')} onReject={() => decideInc(i.id, 'rejected')} approveLabel="Appliquer" rejectLabel="Rejeter" />
                    </Item>
                  ))}
                </Section>
                <Section title="Contre-vérifications" count={queue?.reverifications.length ?? 0} empty="Aucune confirmation demandée.">
                  {queue?.reverifications.map((c) => (
                    <Item key={c.id} title={`${c.id} · ${c.package}`} chip={c.confiance !== null ? <span className="chip danger">sûr à {Math.round(c.confiance * 100)} %</span> : undefined}
                      lines={[c.question, c.resume ? `Avis : ${c.resume}` : null, ...c.motifs]}>
                      <Act busy={!!busy[`cv-${c.id}`]} onApprove={() => decideCv(c.id, true)} onReject={() => decideCv(c.id, false)} approveLabel="Maintenir" rejectLabel="Retirer" disabled={!token} />
                    </Item>
                  ))}
                </Section>
              </div>
            </div>
          </div>
        </main>
      </div>
      <style>{`.spin{animation:aspin 1s linear infinite}@keyframes aspin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}

const inputStyle: React.CSSProperties = { width: '100%', padding: '8px 10px', borderRadius: 'var(--r-sm, 8px)', border: '1px solid var(--line)', background: 'var(--surface)', font: 'inherit' };

function Section({ title, count, empty, children }: { title: string; count: number; empty: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="overline" style={{ marginBottom: 6, display: 'flex', justifyContent: 'space-between' }}><span>{title}</span><span className="faint">{count}</span></div>
      {count === 0 ? <p className="caption faint">{empty}</p> : <div style={{ display: 'grid', gap: 8 }}>{children}</div>}
    </div>
  );
}

function Item({ title, chip, lines, children }: { title: string; chip?: React.ReactNode; lines: (string | null)[]; children: React.ReactNode }) {
  return (
    <div className="ds-card" style={{ padding: 12, boxShadow: 'none', border: '1px solid var(--line)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}><strong className="body-sm" style={{ flex: 1, minWidth: 0 }}>{title}</strong>{chip}</div>
      {lines.filter(Boolean).map((l, i) => <p key={i} className="caption faint" style={{ marginTop: 3 }}>{l}</p>)}
      <div style={{ marginTop: 8 }}>{children}</div>
    </div>
  );
}

function Act({ busy, onApprove, onReject, approveLabel = 'Approuver', rejectLabel = 'Refuser', disabled = false }: { busy: boolean; onApprove: () => void; onReject: () => void; approveLabel?: string; rejectLabel?: string; disabled?: boolean }) {
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      <button className="btn btn-sm" disabled={busy || disabled} onClick={onApprove} style={{ flex: 1 }} title={disabled ? 'Connectez-vous en analyste' : undefined}>{busy ? <Loader2 size={13} className="spin" /> : <Check size={13} />}{approveLabel}</button>
      <button className="btn btn-sm btn-danger" disabled={busy || disabled} onClick={onReject} style={{ flex: 1 }} title={disabled ? 'Connectez-vous en analyste' : undefined}>{busy ? <Loader2 size={13} className="spin" /> : <X size={13} />}{rejectLabel}</button>
    </div>
  );
}
