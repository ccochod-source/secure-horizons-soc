'use client';

import { useEffect, useState } from 'react';
import type { SocOverview } from '@/lib/soc-overview';

type RAGSource = { ref: string; title: string; type?: string | null; source?: string | null };
type RAGReply = { answer: string; sources: RAGSource[]; model: string; documents_found: number };

function Metric({ label, value, caption }: { label: string; value: string | number; caption: string }) {
  return <div className="metric"><p>{label}</p><strong>{value}</strong><span>{caption}</span></div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><strong>{title}</strong><p>{detail}</p></div>;
}

export function SocConsole() {
  const [snapshot, setSnapshot] = useState<SocOverview | null>(null);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [question, setQuestion] = useState('');
  const [ragReply, setRagReply] = useState<RAGReply | null>(null);
  const [ragError, setRagError] = useState('');
  const [asking, setAsking] = useState(false);

  async function askRag(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || asking) return;
    setAsking(true);
    setRagError('');
    setRagReply(null);
    try {
      const response = await fetch('/api/rag/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: trimmed }),
      });
      const data: unknown = await response.json();
      if (!response.ok) {
        const message = data && typeof data === 'object' && 'error' in data && typeof data.error === 'string'
          ? data.error
          : 'L’agent RAG n’a pas pu répondre.';
        throw new Error(message);
      }
      if (!isRAGReply(data)) throw new Error('La réponse de l’agent est invalide.');
      setRagReply(data);
    } catch (cause) {
      setRagError(cause instanceof Error ? cause.message : 'L’agent RAG est momentanément indisponible.');
    } finally {
      setAsking(false);
    }
  }

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    async function check() {
      controller = new AbortController();
      if (!disposed) setChecking(true);
      try {
        const response = await fetch('/api/soc', { cache: 'no-store', signal: controller.signal });
        const data: unknown = await response.json();
        if (!response.ok) {
          const message = data && typeof data === 'object' && 'error' in data && typeof data.error === 'string' ? data.error : 'Connexion à la base indisponible.';
          throw new Error(message);
        }
        if (!isOverview(data)) throw new Error('La réponse du serveur est invalide.');
        if (!disposed) { setSnapshot(data); setError(''); }
      } catch (cause) {
        if (!disposed && !(cause instanceof Error && cause.name === 'AbortError')) {
          setError(cause instanceof Error ? cause.message : 'Connexion à la base indisponible.');
        }
      } finally {
        if (!disposed) { setChecking(false); timer = setTimeout(check, 15000); }
      }
    }
    void check();
    return () => { disposed = true; clearTimeout(timer); controller?.abort(); };
  }, [refresh]);

  const connected = !!snapshot?.databaseConnected && !error;
  const ready = connected && !!snapshot?.pipelineConnected;
  const agents = ready ? snapshot.agents : [];
  const reviews = ready ? snapshot.reviews : [];
  const incidents = ready ? snapshot.incidents : [];
  const activity = ready ? snapshot.activity : [];
  const pending = reviews.filter(item => ['pending', 'proposed', 'pending_approval'].includes(item.status));
  const updated = snapshot ? new Date(snapshot.updatedAt).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : null;

  return <div className="app">
    <header className="topbar">
      <div className="brand"><span className="brand-mark" aria-hidden="true">T</span><strong>TRACE</strong><span className="version">Version de travail</span></div>
      <span className="team-label">Secure Horizons · Équipe SOC</span>
    </header>

    <main>
      <div className="page-heading"><div><h1>Vue d’ensemble</h1><p>Les informations essentielles du projet, au même endroit.</p></div>
        <button type="button" onClick={() => setRefresh(value => value + 1)} disabled={checking}>{checking ? 'Vérification…' : 'Actualiser'}</button>
      </div>

      <section className="metrics" aria-label="Indicateurs principaux">
        <Metric label="Agents branchés" value={agents.length} caption={ready ? 'Connectés à cette interface' : 'En attente du raccordement'} />
        <Metric label="Validations en attente" value={ready ? pending.length : '—'} caption={ready ? 'Demandes à examiner' : 'Aucune demande reçue'} />
        <Metric label="Incidents à examiner" value={ready ? incidents.filter(item => !['closed', 'contained'].includes(item.status)).length : '—'} caption={ready ? 'Incidents reçus du système' : 'Pas encore mesuré'} />
        <Metric label="Actions bloquées" value={ready ? snapshot.blockedActions ?? '—' : '—'} caption="Résultats d’exécution uniquement" />
      </section>

      <section className="panel rag-panel" aria-labelledby="rag-title">
        <div className="panel-heading"><div><h2 id="rag-title">Assistant développeur</h2><p className="rag-intro">Posez une question sur les connaissances présentes dans la base.</p></div><span>Agent RAG · sources affichées</span></div>
        <form className="rag-form" onSubmit={askRag}>
          <label className="sr-only" htmlFor="rag-question">Votre question</label>
          <textarea id="rag-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ex. Quelle est la procédure de revue d’une pull request ?" maxLength={4000} rows={3} disabled={asking} />
          <div className="rag-form-footer"><span>{question.length}/4 000 caractères</span><button type="submit" disabled={asking || !question.trim()}>{asking ? 'Recherche en cours…' : 'Interroger la base'}</button></div>
        </form>
        {ragError ? <div className="error-message rag-error" role="alert">{ragError}</div> : null}
        {asking ? <p className="rag-status" role="status">Recherche dans les documents puis préparation de la réponse…</p> : null}
        {ragReply ? <div className="rag-result" aria-live="polite"><h3>Réponse</h3><p className="rag-answer">{ragReply.answer}</p><div className="rag-sources"><strong>Sources consultées ({ragReply.documents_found})</strong>{ragReply.sources.length ? <ul>{ragReply.sources.map((source) => <li key={`${source.ref}-${source.title}`}><span>{source.ref}</span><div><strong>{source.title}</strong>{source.source ? <small>{source.source}</small> : null}</div></li>)}</ul> : <p>Aucun document pertinent trouvé dans la base.</p>}</div></div> : null}
      </section>

      {!ready ? <div className="notice"><strong>Les agents ne sont pas encore branchés.</strong><p>Les résultats resteront vides jusqu’à leur raccordement. Les exemples préparés dans la base ne sont pas affichés.</p></div> : null}
      {error ? <div className="error-message" role="alert"><strong>Connexion indisponible</strong><p>{error}</p><p>Les indicateurs ne sont pas actualisés.</p></div> : null}

      <section className="panel connections" aria-labelledby="connections-title">
        <div className="panel-heading"><h2 id="connections-title">État des connexions</h2><span role="status">{checking ? 'Vérification en cours' : updated ? `Dernière vérification réussie à ${updated}` : 'En attente de vérification'}</span></div>
        <div className="connection-list">
          <div><span className="connection-name">Interface</span><span className="status connected">Disponible</span></div>
          <div><span className="connection-name">Base de données</span><span className={`status ${connected ? 'connected' : error ? 'unavailable' : ''}`}>{connected ? 'Connectée' : error ? 'Indisponible' : 'Vérification…'}</span></div>
          <div><span className="connection-name">Agents et workflow</span><span className="status">{ready ? 'Raccordés' : 'Non branchés'}</span></div>
          <div><span className="connection-name">Validation humaine</span><span className="status">Non branchée</span></div>
        </div>
      </section>

      <section className="panel workflow" aria-labelledby="workflow-title">
        <div className="panel-heading"><h2 id="workflow-title">Parcours prévu</h2><span>Schéma du projet · pas une exécution en cours</span></div>
        <ol className="workflow-steps"><li><span>1</span><div><strong>Vérifier le package</strong><small>Contrôler la version proposée</small></div></li><li><span>2</span><div><strong>Valider ou refuser</strong><small>Décision de l’analyste</small></div></li><li><span>3</span><div><strong>Enquêter si suspect</strong><small>Retrouver l’origine et l’impact</small></div></li><li><span>4</span><div><strong>Conserver les preuves</strong><small>Résultats et rapport</small></div></li></ol>
      </section>

      <div className="panel-grid">
        <section className="panel" aria-labelledby="agents-title"><div className="panel-heading"><h2 id="agents-title">Agents</h2><span>{agents.length} branché{agents.length > 1 ? 's' : ''}</span></div>
          {agents.length ? <ul className="record-list">{agents.map(agent => <li key={agent.id}><strong>{agent.name}</strong><p>{agent.role}</p></li>)}</ul> : <EmptyState title="Aucun agent branché" detail="Les vrais agents apparaîtront ici après leur intégration." />}
        </section>
        <section className="panel" aria-labelledby="reviews-title"><div className="panel-heading"><h2 id="reviews-title">Packages à valider</h2><span>Décisions humaines</span></div>
          {pending.length ? <ul className="record-list">{pending.map(review => <li key={review.id}><strong>{review.package} · {review.version}</strong><p>En attente de décision</p></li>)}</ul> : <EmptyState title="Aucune demande reçue" detail="Les packages en attente seront listés ici. La validation n’est pas encore raccordée." />}
        </section>
        <section className="panel" aria-labelledby="incidents-title"><div className="panel-heading"><h2 id="incidents-title">Incidents</h2><span>Détections et enquêtes</span></div>
          {incidents.length ? <ul className="record-list">{incidents.map(incident => <li key={incident.id}><strong>{incident.title}</strong><p>{incident.severity} · {incident.status}</p></li>)}</ul> : <EmptyState title="Aucun incident reçu" detail="Les alertes et leurs preuves apparaîtront ici après le raccordement." />}
        </section>
        <section className="panel" aria-labelledby="activity-title"><div className="panel-heading"><h2 id="activity-title">Dernière activité</h2><span>Événements réels</span></div>
          {activity.length ? <ul className="record-list">{activity.map(event => <li key={event.id}><strong>{event.title}</strong><p>{event.time} · {event.result}</p></li>)}</ul> : <EmptyState title="Aucune activité reçue" detail="Les étapes réellement exécutées s’afficheront ici dans l’ordre." />}
        </section>
      </div>

      <section className="panel tests-summary" aria-labelledby="tests-title"><div><h2 id="tests-title">Résultats des tests</h2><p>Comparaison avec et sans protection, après les premières exécutions.</p></div><div><strong>{ready ? snapshot.completedTests ?? '—' : '—'}</strong><span>{ready ? 'Tests terminés' : 'Pas encore mesuré'}</span></div></section>
      <footer>Interface de travail · Lecture seule · Aucun agent ni résultat simulé</footer>
    </main>
  </div>;
}

function isRAGReply(value: unknown): value is RAGReply {
  if (!value || typeof value !== 'object') return false;
  const data = value as Partial<RAGReply>;
  return typeof data.answer === 'string' && typeof data.model === 'string' && Number.isInteger(data.documents_found)
    && Array.isArray(data.sources) && data.sources.every((source) => typeof source?.ref === 'string' && typeof source?.title === 'string');
}

function isOverview(value: unknown): value is SocOverview {
  if (!value || typeof value !== 'object') return false;
  const data = value as Partial<SocOverview>;
  return typeof data.updatedAt === 'string' && Number.isFinite(Date.parse(data.updatedAt)) && typeof data.databaseConnected === 'boolean' && typeof data.pipelineConnected === 'boolean'
    && Array.isArray(data.agents) && data.agents.every(item => typeof item?.id === 'string' && typeof item?.name === 'string' && typeof item?.role === 'string')
    && Array.isArray(data.reviews) && data.reviews.every(item => typeof item?.id === 'string' && typeof item?.package === 'string' && typeof item?.version === 'string' && typeof item?.status === 'string')
    && Array.isArray(data.incidents) && data.incidents.every(item => typeof item?.id === 'string' && typeof item?.title === 'string' && typeof item?.severity === 'string' && typeof item?.status === 'string')
    && Array.isArray(data.activity) && data.activity.every(item => typeof item?.id === 'string' && typeof item?.time === 'string' && typeof item?.title === 'string' && typeof item?.result === 'string')
    && (data.blockedActions === null || typeof data.blockedActions === 'number' && Number.isFinite(data.blockedActions) && data.blockedActions >= 0)
    && (data.completedTests === null || typeof data.completedTests === 'number' && Number.isFinite(data.completedTests) && data.completedTests >= 0);
}
