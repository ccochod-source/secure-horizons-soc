'use client';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Bell, Castle, LayoutDashboard, Search, Terminal, ShieldCheck, Lock, Timer, UserCheck, Gauge, PackageX, ArrowUpRight, SlidersHorizontal, ExternalLink, Swords, TrendingUp } from 'lucide-react';
import type { DashboardData } from '@/app/api/dashboard/route';
import { BarsChart, Donut, ScoreBar, Spark } from './charts';
import { AgentChat } from './chat';

const CastlePreview = dynamic(() => import('@/castle/CastlePreview').then((m) => m.CastlePreview), { ssr: false });

const SEVERITY: Record<string, string> = { Critique: 'danger', Élevée: 'danger', Modérée: 'warning' };
const STATUS: Record<string, string> = { 'À examiner': 'warning', 'En enquête': 'info', Confiné: 'success', Surveillance: 'info', "Approuvé, en attente d'exécution": 'warning' };

function Delta({ now, prev, invert = false }: { now: number; prev: number; invert?: boolean }) {
  if (!prev && !now) return <span className="chip">—</span>;
  const diff = now - prev;
  const good = invert ? diff <= 0 : diff >= 0;
  const label = diff === 0 ? '= stable' : prev === 0 ? `${diff > 0 ? '↑' : '↓'} ${Math.abs(diff)} (période préc. : 0)` : `${diff > 0 ? '↑' : '↓'} ${Math.abs(Math.round((diff / prev) * 100))} %`;
  return <span className={`chip ${diff === 0 ? '' : good ? 'success' : 'danger'}`} title={`période précédente : ${prev}`}>{label}</span>;
}

function Kpi({ label, value, unit, delta, spark, color, hint, className = 'c3' }: { label: string; value: string | number; unit?: string; delta?: React.ReactNode; spark?: number[]; color?: string; hint?: string; className?: string }) {
  return (
    <div className={`ds-card kpi-tile ${className}`}>
      <p className="body-sm">{label}</p>
      <div className="kpi-line"><span className="kpi">{value}{unit && <small> {unit}</small>}</span>{delta}</div>
      {hint && <p className="caption faint">{hint}</p>}
      {spark && <div className="spark"><Spark values={spark} color={color} /></div>}
    </div>
  );
}

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [range, setRange] = useState<'24h' | '7d'>('24h');
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const r = await fetch(`/api/dashboard?range=${range}`, { cache: 'no-store' });
        const d = (await r.json()) as DashboardData & { error?: string };
        if (stop) return;
        if (!r.ok) { setError(d.error ?? `Erreur ${r.status}`); return; }
        setData(d); setError('');
      } catch (e) { if (!stop) setError(e instanceof Error ? e.message : String(e)); }
    };
    void load();
    const id = setInterval(load, 15000);
    return () => { stop = true; clearInterval(id); };
  }, [range, tick]);

  const k = data?.kpis;
  const sessionsSpark = useMemo(() => data?.series.map((s) => s.sessions) ?? [], [data]);
  const threatsSpark = useMemo(() => data?.series.map((s) => s.threats) ?? [], [data]);
  const incidents = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data?.incidents ?? []).filter((i) => !q || `${i.id} ${i.title} ${i.severity} ${i.status} ${i.proposal}`.toLowerCase().includes(q));
  }, [data, query]);
  const protection = k ? Math.round(100 * (1 - k.leaks / Math.max(1, k.neutralized + k.leaks))) : null;
  const hour = new Date().getHours();
  const greeting = hour < 18 ? 'Bonjour,' : 'Bonsoir,';

  return (
    <div className="ds">
      <div className="ds-app">
        <aside className="ds-sidebar">
          <div className="ds-logo"><div className="ds-logo-mark"><ShieldCheck size={16} strokeWidth={2} /></div><span className="ds-logo-word">TRACE.</span></div>
          <div className="overline" style={{ padding: '0 14px 6px' }}>Pilotage</div>
          <Link href="/" className="ds-nav active"><LayoutDashboard size={20} strokeWidth={1.75} /><span>Tableau de bord</span></Link>
          <Link href="/castle" className="ds-nav"><Castle size={20} strokeWidth={1.75} /><span>Château</span>{k && k.pendingDecisions > 0 && <span className="ds-count">{k.pendingDecisions}</span>}</Link>
          <div className="overline" style={{ padding: '14px 14px 6px' }}>Outils</div>
          <Link href="/arsenal" className="ds-nav"><Swords size={20} strokeWidth={1.75} /><span>Arsenal</span>{k && k.pendingDecisions > 0 && <span className="ds-count">{k.pendingDecisions}</span>}</Link>
          <Link href="/console" className="ds-nav"><Terminal size={20} strokeWidth={1.75} /><span>Console SOC</span></Link>
          <div style={{ marginTop: 'auto', padding: '0 14px 56px' }} className="caption faint">
            <span className="dot" style={{ background: data?.health.gateway ? 'var(--success)' : 'var(--danger)', marginRight: 6 }} />passerelle
            <br /><span className="dot" style={{ background: data?.health.defense ? 'var(--success)' : 'var(--danger)', marginRight: 6 }} />défense
            <br /><span className="dot" style={{ background: data?.health.database ? 'var(--success)' : 'var(--danger)', marginRight: 6 }} />base
          </div>
        </aside>

        <main className="ds-main">
          <header className="ds-topbar">
            <div className="title-block">
              <p className="body muted">{greeting}</p>
              <h1 className="display-xl">Protection des agents IA</h1>
            </div>
            <div className="search"><Search size={18} strokeWidth={1.75} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher un incident" aria-label="Rechercher" /><kbd>⌘F</kbd></div>
            <button className="btn-icon" style={{ width: 40, height: 40, position: 'relative' }} aria-label="Décisions en attente" title="Décisions en attente"><Bell size={18} strokeWidth={1.75} />{k && k.pendingDecisions > 0 && <span className="ds-count" style={{ position: 'absolute', top: -2, right: -2 }}>{k.pendingDecisions}</span>}</button>
            <div className="user-avatar" title="Analyste">EL</div>
          </header>

          {error && <div className="ds-card tint-danger c12" style={{ marginBottom: 16 }}><strong style={{ color: 'var(--danger)' }}>Données indisponibles</strong><p className="body-sm">{error}</p></div>}

          <div className="ds-grid">
            {/* Château 3D : bannière hero cliquable */}
            <Link href="/castle" className="ds-card accent hover c12" style={{ position: 'relative', minHeight: 280, overflow: 'hidden', display: 'block', borderRadius: 'var(--r-xl)' }} aria-label="Ouvrir la page château">
              <div style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: '55%' }}><CastlePreview /></div>
              <div style={{ position: 'relative', maxWidth: 440, display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
                <span className="chip" style={{ background: 'rgba(255,255,255,.18)', color: '#fff', alignSelf: 'flex-start' }}>Visualisation en direct</span>
                <h2 className="display-lg">Le château</h2>
                <p className="body" style={{ color: 'rgba(255,255,255,.72)' }}>Chaque défense devient visible : les leurres, le bac à sable, le contrôle des packages et l’enquête des agents, jouée sur de vrais tests.</p>
                <span className="btn" style={{ background: '#111114', color: '#fff', boxShadow: 'none', alignSelf: 'flex-start', marginTop: 'auto' }}>Ouvrir le château <ArrowUpRight size={16} /></span>
              </div>
            </Link>

            {/* KPI */}
            <Kpi label="Attaques neutralisées" value={k?.neutralized ?? '—'} delta={k && <Delta now={k.neutralized} prev={k.neutralizedPrev} />} spark={threatsSpark} color="var(--viz-2)" hint={k ? `${k.decoysHit} via les leurres · ${k.packagesBlocked} package${k.packagesBlocked > 1 ? 's' : ''} bloqué${k.packagesBlocked > 1 ? 's' : ''}` : undefined} />
            <Kpi label="Fuites de données" value={k ? k.leaks : '—'} delta={k && <span className={`chip ${k.leaks === 0 ? 'success' : 'danger'}`}><Lock size={12} /> {k.leaks === 0 ? 'objectif 0 tenu' : 'à traiter'}</span>} hint={k ? `${k.outboundBlocked} envoi${k.outboundBlocked > 1 ? 's' : ''} externe${k.outboundBlocked > 1 ? 's' : ''} bloqué${k.outboundBlocked > 1 ? 's' : ''} · ${k.secretsMasked} secrets masqués avant tout LLM` : undefined} spark={sessionsSpark.map(() => 0)} color="var(--viz-7)" />
            <Kpi label="Délai médian de détection" value={k?.detectionMedianS === null || !k ? '—' : k.detectionMedianS < 60 ? k.detectionMedianS.toFixed(1) : (k.detectionMedianS / 60).toFixed(1)} unit={k?.detectionMedianS !== null && k ? (k.detectionMedianS < 60 ? 's' : 'min') : undefined} delta={k && <span className="chip info"><Timer size={12} /> demande → blocage</span>} hint="entre la demande à l’agent et la première défense déclenchée" spark={sessionsSpark} color="var(--viz-1)" />
            <Kpi label="Décisions humaines en attente" value={k?.pendingDecisions ?? '—'} delta={k && <span className={`chip ${k.pendingDecisions ? 'warning' : 'success'}`}><UserCheck size={12} /> {k.pendingDecisions ? 'à trancher' : 'à jour'}</span>} hint={k ? `${k.pendingBreakdown.incidents} enquête${k.pendingBreakdown.incidents > 1 ? 's' : ''} · ${k.pendingBreakdown.packages} package${k.pendingBreakdown.packages > 1 ? 's' : ''} · ${k.pendingBreakdown.documents} document${k.pendingBreakdown.documents > 1 ? 's' : ''} · ${k.pendingBreakdown.reverifications} confirmation${k.pendingBreakdown.reverifications > 1 ? 's' : ''}` : undefined} spark={threatsSpark} color="var(--viz-1)" />

            {/* actions humaines par attaque détectée */}
            <Kpi className="c4" label="Actions humaines / attaque détectée" value={k?.humanActionsPerAttack == null ? '—' : k.humanActionsPerAttack.toFixed(2)} delta={k && <span className="chip info"><UserCheck size={12} /> humain dans la boucle</span>} hint={k ? `${k.humanActions} action${k.humanActions > 1 ? 's' : ''} humaine${k.humanActions > 1 ? 's' : ''} pour ${k.attacksDetected} attaque${k.attacksDetected > 1 ? 's' : ''} détectée${k.attacksDetected > 1 ? 's' : ''} · plus c’est bas, plus c’est automatisé` : undefined} />

            {/* amélioration de la sécurité : boucle d'apprentissage (auto-incrémentation des règles) */}
            <div className="ds-card c8">
              <div className="ds-card-head">
                <div className="ds-icon-badge"><TrendingUp size={18} strokeWidth={1.75} /></div>
                <div className="grow"><h2 className="h2">Amélioration de la sécurité</h2><p className="body-sm">La couverture grandit à chaque requête : attaques neutralisées cumulées sur la période, et règles de défense apprises des vraies attaques.</p></div>
                <Link href="/castle" className="btn btn-icon" aria-label="Gérer les règles apprises" title="Château"><ExternalLink size={16} strokeWidth={1.75} /></Link>
              </div>
              <div style={{ display: 'flex', gap: 24, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <div>
                  <div className="kpi-line"><span className="kpi">{data?.learning.attacksTotal ?? '—'}</span></div>
                  <p className="caption faint">attaques neutralisées (cumul période)</p>
                </div>
                <div>
                  <div className="kpi-line"><span className="kpi" style={{ fontSize: 28 }}>v{data?.learning.version ?? '—'}</span></div>
                  <p className="caption faint">version du jeu de règles</p>
                </div>
                <div style={{ flex: 1, minWidth: 180 }}>
                  <Spark values={data && data.learning.series.length > 1 ? data.learning.series : [0, 0]} color="var(--viz-2)" />
                  <p className="caption faint" style={{ marginTop: 4 }}>{data ? `${data.learning.sessionsTotal} requête${data.learning.sessionsTotal > 1 ? 's' : ''} analysée${data.learning.sessionsTotal > 1 ? 's' : ''} sur la période` : ''}</p>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 12 }}>
                <span className="chip success"><ShieldCheck size={12} /> {data?.learning.active ?? 0} protection{(data?.learning.active ?? 0) > 1 ? 's' : ''} active{(data?.learning.active ?? 0) > 1 ? 's' : ''}</span>
                <span className="chip warning"><UserCheck size={12} /> {data?.learning.proposed ?? 0} à valider</span>
                <span className="chip"><PackageX size={12} /> packages : {data?.learning.byList.package.active ?? 0}</span>
                <span className="chip">leurres : {data?.learning.byList.decoy.active ?? 0}</span>
              </div>
              <p className="caption faint" style={{ marginTop: 8 }}>Chaque requête traitée alimente la courbe. Quand un analyste refuse un package malveillant ou confirme un leurre touché, une règle est apprise et la version s’incrémente : les attaques identiques suivantes sont bloquées automatiquement.</p>
            </div>

            {/* activité */}
            <div className="ds-card c8">
              <div className="ds-card-head">
                <div className="grow"><h2 className="h2">Activité des agents</h2><p className="body-sm">Sessions analysées et menaces neutralisées, {range === '24h' ? 'par heure sur 24 h' : 'par jour sur 7 jours'}.</p></div>
                <div className="tabs"><button className={range === '24h' ? 'active' : ''} onClick={() => setRange('24h')}>24 h</button><button className={range === '7d' ? 'active' : ''} onClick={() => setRange('7d')}>7 j</button></div>
              </div>
              <div className="legend" style={{ marginBottom: 8 }}><span><i style={{ background: 'var(--viz-1)' }} />Sessions</span><span><i style={{ background: 'var(--viz-2)' }} />Menaces neutralisées</span></div>
              {data ? <BarsChart data={data.series} /> : <div style={{ height: 220 }} className="ds-card nested" />}
              <div style={{ display: 'flex', gap: 24, marginTop: 12 }} className="body-sm">
                <span><strong className="h3" style={{ color: 'var(--text)' }}>{k?.sessions ?? '—'}</strong> sessions {k && <Delta now={k.sessions} prev={k.sessionsPrev} />}</span>
                <span><strong className="h3" style={{ color: 'var(--text)' }}>{k?.packagesInstalled ?? '—'}</strong> packages sains installés</span>
                <span><strong className="h3" style={{ color: 'var(--text)' }}>100 %</strong> des appels d’outils tracés</span>
              </div>
            </div>

            {/* répartition */}
            <div className="ds-card c4">
              <div className="ds-card-head"><div className="grow"><h2 className="h2">Issue des sessions</h2><p className="body-sm">Sur la période affichée.</p></div></div>
              <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
                <Donut parts={[{ label: 'saines', value: data?.split.safe ?? 0, color: 'var(--viz-1)' }, { label: 'neutralisées', value: data?.split.threats ?? 0, color: 'var(--viz-2)' }, { label: 'en attente', value: data?.split.open ?? 0, color: 'var(--viz-7)', hatched: true }]} />
                <div className="legend" style={{ flexDirection: 'column', gap: 10 }}>
                  <span><i style={{ background: 'var(--viz-1)' }} />Saines · <strong style={{ color: 'var(--text)' }}>{data?.split.safe ?? '—'}</strong></span>
                  <span><i style={{ background: 'var(--viz-2)' }} />Neutralisées · <strong style={{ color: 'var(--text)' }}>{data?.split.threats ?? '—'}</strong></span>
                  <span><i style={{ background: 'repeating-linear-gradient(45deg, transparent 0 2px, var(--viz-7) 2px 3px)' }} />Décision en attente · <strong style={{ color: 'var(--text)' }}>{data?.split.open ?? '—'}</strong></span>
                </div>
              </div>
              <div style={{ marginTop: 20 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }} className="body-sm"><span>Score de protection</span><strong style={{ color: 'var(--text)' }}>{protection === null ? '—' : `${protection} / 100`}</strong></div>
                <div style={{ marginTop: 12 }}><ScoreBar value={protection ?? 0} /></div>
                <p className="caption faint" style={{ marginTop: 8 }}>part des attaques neutralisées sans fuite de données</p>
              </div>
            </div>

            {/* chat */}
            <AgentChat onDone={refresh} />

            {/* incidents */}
            <div className="ds-card c6">
              <div className="ds-card-head">
                <div className="ds-icon-badge"><Gauge size={18} strokeWidth={1.75} /></div>
                <div className="grow"><h2 className="h2">Enquêtes des agents défenseurs</h2><p className="body-sm">{k ? `${k.incidents} enquête${k.incidents > 1 ? 's' : ''} · certitude moyenne ${k.certaintyAvg === null ? '—' : `${Math.round(k.certaintyAvg * 100)} %`}` : 'Chargement…'}</p></div>
                <div className="actions"><Link href="/console" className="btn btn-icon" aria-label="Ouvrir la console" title="Console SOC"><ExternalLink size={16} strokeWidth={1.75} /></Link></div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {incidents.length === 0 && <p className="body-sm">{query ? 'Aucune enquête ne correspond.' : 'Aucune enquête ouverte.'}</p>}
                {incidents.map((i) => (
                  <Link key={i.id} href={`/castle?incident=${i.id}`} className="row">
                    <div className="avatar" style={{ background: i.severity === 'Modérée' ? 'var(--warning-bg)' : 'var(--danger-bg)', color: i.severity === 'Modérée' ? 'var(--warning)' : 'var(--danger)' }}><PackageX size={18} strokeWidth={1.75} /></div>
                    <div className="grow"><div className="h3 ellipsis">{i.title}</div><div className="body-sm ellipsis">{i.id} · {i.proposal}</div></div>
                    <div className="right"><div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}><span className={`chip ${SEVERITY[i.severity] ?? ''}`}>{i.severity}</span><span className={`chip ${STATUS[i.status] ?? ''}`}>{i.status}</span></div><div className="caption faint" style={{ marginTop: 4 }}>certitude {Math.round(i.confidence * 100)} % · {i.time}</div></div>
                  </Link>
                ))}
              </div>
            </div>

            {/* mesures */}
            <div className="ds-card dark c12">
              <div className="ds-card-head">
                <div className="ds-icon-badge" style={{ background: 'rgba(255,255,255,.1)', color: '#fff' }}><SlidersHorizontal size={18} strokeWidth={1.75} /></div>
                <div className="grow"><h2 className="h2">Mesures de confinement en vigueur</h2><p className="body-sm" style={{ color: 'rgba(245,245,247,.6)' }}>Appliquées par la passerelle sur décision d’un analyste. {k ? `${k.activeMeasures} active${k.activeMeasures > 1 ? 's' : ''}.` : ''}</p></div>
                <Link href="/castle" className="btn" style={{ background: 'var(--accent-lime)', color: '#111114', boxShadow: 'none', height: 40 }}>Gérer dans le château</Link>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {data && data.measures.suspensions.length + data.measures.packages.length + data.measures.documents.length === 0 && <span className="chip" style={{ background: 'rgba(255,255,255,.1)', color: '#F5F5F7' }}>Aucune mesure active : tous les outils, packages et documents sont disponibles.</span>}
                {data?.measures.suspensions.map((s) => <span key={`${s.agent_id}-${s.tool}`} className="chip" style={{ background: 'rgba(255,255,255,.12)', color: '#F5F5F7', height: 30, padding: '0 12px' }}>outil <code style={{ margin: '0 4px' }}>{s.tool}</code> suspendu pour {s.agent_id} · {s.incident_id}</span>)}
                {data?.measures.packages.map((p) => <span key={p.package} className="chip" style={{ background: 'rgba(255,255,255,.12)', color: '#F5F5F7', height: 30, padding: '0 12px' }}>package <code style={{ margin: '0 4px' }}>{p.package}</code> en quarantaine · {p.incident_id}</span>)}
                {data?.measures.documents.map((d) => <span key={d.document_id} className="chip" style={{ background: 'rgba(255,255,255,.12)', color: '#F5F5F7', height: 30, padding: '0 12px' }}>document « {d.title} » écarté · {d.incident_id}</span>)}
              </div>
            </div>
          </div>
          <p className="caption faint" style={{ marginTop: 24 }}>{data ? `Données réelles · relevé ${new Date(data.checkedAt).toLocaleTimeString('fr-FR')} · actualisation toutes les 15 s` : ''}</p>
        </main>
      </div>
    </div>
  );
}
