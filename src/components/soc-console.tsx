'use client';

import { useEffect, useState } from 'react';
import type { SocOverview } from '@/lib/soc-overview';

type RAGSource = { ref: string; title: string; type?: string | null; source?: string | null };
type RAGReply = { answer: string; sources: RAGSource[]; model: string; documents_found: number; pipeline_delivery?: { status: string; incident_id?: string | null } };
type DemoResult = { trace_id: string; diverted: boolean; neutralized: boolean; tool_calls: string[]; event_types: string[]; pipeline_delivery: { status: string; incident_id: string | null } };
type KnowledgeDemoResult = { id: string; title: string; status: string; reason: string | null };

const demoEventLabels: Record<string, string> = {
  user_request: 'Question reçue', tool_call: 'Appel d’outil', tool_response: 'Résultat de l’outil',
  decoy_access: 'Accès au leurre détecté', session_diverted: 'Session déroutée vers le bac à sable',
  agent_response: 'Réponse de l’agent', mcp_server_registered: 'Outil MCP enregistré',
};

function Metric({ label, value, caption }: { label: string; value: string | number; caption: string }) {
  return <div className="metric"><p>{label}</p><strong>{value}</strong><span>{caption}</span></div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><strong>{title}</strong><p>{detail}</p></div>;
}

export function SocConsole() {
  const [activeTab, setActiveTab] = useState<'overview' | 'demo'>('overview');
  const [snapshot, setSnapshot] = useState<SocOverview | null>(null);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [question, setQuestion] = useState('');
  const [ragReply, setRagReply] = useState<RAGReply | null>(null);
  const [ragError, setRagError] = useState('');
  const [asking, setAsking] = useState(false);
  const [decisionError, setDecisionError] = useState('');
  const [decidingId, setDecidingId] = useState('');
  const [packageName, setPackageName] = useState('');
  const [registry, setRegistry] = useState('npm');
  const [packageMessage, setPackageMessage] = useState('');
  const [packageBusy, setPackageBusy] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [analystAccess, setAnalystAccess] = useState('');
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoResult, setDemoResult] = useState<DemoResult | null>(null);
  const [demoError, setDemoError] = useState('');
  const [knowledgeDemoRunning, setKnowledgeDemoRunning] = useState(false);
  const [knowledgeDemoResult, setKnowledgeDemoResult] = useState<KnowledgeDemoResult | null>(null);
  const [knowledgeDemoError, setKnowledgeDemoError] = useState('');
  const [knowledgeDecisionBusy, setKnowledgeDecisionBusy] = useState('');
  const [knowledgeDecisionError, setKnowledgeDecisionError] = useState('');

  async function runDemo() {
    if (demoRunning) return;
    setDemoRunning(true);
    setDemoResult(null);
    setDemoError('');
    try {
      const response = await fetch('/api/demo/attack', { method: 'POST' });
      const data: unknown = await response.json();
      if (!response.ok) {
        const message = data && typeof data === 'object' && 'error' in data && typeof data.error === 'string'
          ? data.error : 'Le scénario n’a pas pu être lancé.';
        throw new Error(message);
      }
      if (!isDemoResult(data)) throw new Error('Le résultat du scénario est invalide.');
      setDemoResult(data);
      setRefresh(value => value + 1);
    } catch (cause) {
      setDemoError(cause instanceof Error ? cause.message : 'Le scénario est indisponible.');
    } finally {
      setDemoRunning(false);
    }
  }

  async function runKnowledgeDemo() {
    if (knowledgeDemoRunning) return;
    setKnowledgeDemoRunning(true);
    setKnowledgeDemoError('');
    setKnowledgeDemoResult(null);
    try {
      const response = await fetch('/api/demo/knowledge', { method: 'POST' });
      const data: unknown = await response.json();
      if (!response.ok) {
        const message = data && typeof data === 'object' && 'error' in data && typeof data.error === 'string'
          ? data.error : 'Le scénario n’a pas pu être lancé.';
        throw new Error(message);
      }
      if (!data || typeof data !== 'object' || !('id' in data) || typeof data.id !== 'string'
        || !('status' in data) || typeof data.status !== 'string') throw new Error('Résultat invalide.');
      setKnowledgeDemoResult(data as KnowledgeDemoResult);
      setRefresh(value => value + 1);
    } catch (cause) {
      setKnowledgeDemoError(cause instanceof Error ? cause.message : 'Le scénario est indisponible.');
    } finally {
      setKnowledgeDemoRunning(false);
    }
  }
  async function packageAction(operation: string, extra: Record<string, string> = {}) {
    if (packageBusy) return;
    setPackageBusy(true); setPackageMessage('');
    try {
      const r = await fetch('/api/packages', {method:'POST',headers:{'Content-Type':'application/json', ...(analystAccess ? {Authorization:`Bearer ${analystAccess}`} : {})},body:JSON.stringify({operation,...extra})});
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || 'Opération refusée.');
      if (operation === 'login') { setAnalystAccess(data.access_token); setPassword(''); setPackageMessage('Compte analyste connecté.'); }
      else { setPackageMessage(operation === 'review' ? `Analyse terminée : ${data.result?.simulated ? 'installation simulée, aucun code exécuté' : data.result?.status || 'voir la revue'}. ${data.pipeline_delivery?.status === 'delivered' ? 'Traces transmises à la défense.' : 'Transmission à la défense non confirmée.'}` : 'Décision enregistrée.'); setRefresh(v=>v+1); }
    } catch (e) { setPackageMessage(e instanceof Error ? e.message : 'Service indisponible.'); }
    finally { setPackageBusy(false); }
  }


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

  async function decideIncident(id: string, decision: 'approved' | 'rejected') {
    if (decidingId) return;
    setDecidingId(id);
    setDecisionError('');
    try {
      const response = await fetch('/api/incidents/decision', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, decision }),
      });
      const data: unknown = await response.json();
      if (!response.ok) {
        const message = data && typeof data === 'object' && 'error' in data && typeof data.error === 'string'
          ? data.error : 'La décision n’a pas été enregistrée.';
        throw new Error(message);
      }
      setRefresh(value => value + 1);
    } catch (cause) {
      setDecisionError(cause instanceof Error ? cause.message : 'La décision n’a pas été enregistrée.');
    } finally {
      setDecidingId('');
    }
  }

  async function decideKnowledge(table: 'documents' | 'repo_files', id: string, decision: 'approve' | 'reject', version: string | null) {
    if (knowledgeDecisionBusy) return;
    setKnowledgeDecisionBusy(id);
    setKnowledgeDecisionError('');
    try {
      const response = await fetch('/api/knowledge/decision', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        // La version (xmin) affichée accompagne la décision : si le contenu a changé depuis,
        // le backend refuse (409) et la liste doit être rafraîchie avant de re-décider.
        body: JSON.stringify({ table, id, decision, version: version ?? undefined }),
      });
      const data: unknown = await response.json();
      if (!response.ok) {
        const message = data && typeof data === 'object' && 'error' in data && typeof data.error === 'string'
          ? data.error : 'Décision non enregistrée.';
        throw new Error(message);
      }
      setRefresh(value => value + 1);
    } catch (cause) {
      setKnowledgeDecisionError(cause instanceof Error ? cause.message : 'Décision non enregistrée.');
    } finally {
      setKnowledgeDecisionBusy('');
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
  const agents = connected ? snapshot!.agents : [];
  const reviews = connected ? snapshot!.reviews : [];
  const incidents = ready ? snapshot.incidents : [];
  const activity = connected ? snapshot!.activity : [];
  const pending = reviews.filter(item => ['pending', 'proposed', 'pending_approval'].includes(item.status));
  const knowledgeReviews = connected ? snapshot!.knowledgeReviews : [];
  const updated = snapshot ? new Date(snapshot.updatedAt).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : null;

  return <div className="app">
    <header className="topbar">
      <div className="brand"><span className="brand-mark" aria-hidden="true">T</span><strong>TRACE</strong><span className="version">Version de travail</span></div>
      <span className="team-label">Secure Horizons · Équipe SOC</span>
    </header>

    <main>
      <div className="page-heading"><div><h1>{activeTab === 'overview' ? 'Vue d’ensemble' : 'Démonstration d’attaque'}</h1><p>{activeTab === 'overview' ? 'Les informations essentielles du projet, au même endroit.' : 'Une tentative contrôlée sur l’assistant doté d’outils.'}</p></div>
        {activeTab === 'overview' ? <button type="button" onClick={() => setRefresh(value => value + 1)} disabled={checking}>{checking ? 'Vérification…' : 'Actualiser'}</button> : null}
      </div>
      <div className="page-tabs" role="tablist" aria-label="Pages TRACE">
        <button type="button" role="tab" id="tab-overview" aria-controls="panel-overview" aria-selected={activeTab === 'overview'} onClick={() => setActiveTab('overview')}>Vue d’ensemble</button>
        <button type="button" role="tab" id="tab-demo" aria-controls="panel-demo" aria-selected={activeTab === 'demo'} onClick={() => setActiveTab('demo')}>Scénario d’attaque</button>
      </div>

      <div id="panel-overview" role="tabpanel" aria-labelledby="tab-overview" hidden={activeTab !== 'overview'}>

      <section className="metrics" aria-label="Indicateurs principaux">
        <Metric label="Agents branchés" value={agents.length} caption={connected ? 'Connectés à cette interface' : 'En attente du raccordement'} />
        <Metric label="Validations en attente" value={ready ? pending.length + knowledgeReviews.length : '—'} caption={ready ? 'Packages et connaissances à examiner' : 'Aucune demande reçue'} />
        <Metric label="Incidents à examiner" value={ready ? incidents.filter(item => !['closed', 'contained', 'Confiné', 'Surveillance'].includes(item.status)).length : '—'} caption={ready ? 'Incidents reçus du système' : 'Pas encore mesuré'} />
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
        {ragReply ? <div className="rag-result" aria-live="polite"><h3>Réponse</h3><p className="rag-answer">{ragReply.answer}</p><div className="rag-sources"><strong>Sources consultées ({ragReply.documents_found})</strong>{ragReply.sources.length ? <ul>{ragReply.sources.map((source) => <li key={`${source.ref}-${source.title}`}><span>{source.ref}</span><div><strong>{source.title}</strong>{source.source ? <small>{source.source}</small> : null}</div></li>)}</ul> : <p>Aucun document pertinent trouvé dans la base.</p>}</div><p className="rag-intro" role="status">{ragReply.pipeline_delivery?.status === 'delivered' ? ragReply.pipeline_delivery.incident_id ? `Trace transmise à la pipeline · incident ${ragReply.pipeline_delivery.incident_id}` : 'Trace transmise à la pipeline de défense · aucune alerte créée.' : 'Réponse enregistrée ; transmission à la pipeline non confirmée.'}</p></div> : null}
      </section>

      {!ready ? <div className="notice"><strong>Les agents ne sont pas encore branchés.</strong><p>Les résultats resteront vides jusqu’à leur raccordement. Les exemples préparés dans la base ne sont pas affichés.</p></div> : null}
      {error ? <div className="error-message" role="alert"><strong>Connexion indisponible</strong><p>{error}</p><p>Les indicateurs ne sont pas actualisés.</p></div> : null}

      <section className="panel connections" aria-labelledby="connections-title">
        <div className="panel-heading"><h2 id="connections-title">État des connexions</h2><span role="status">{checking ? 'Vérification en cours' : updated ? `Dernière vérification réussie à ${updated}` : 'En attente de vérification'}</span></div>
        <div className="connection-list">
          <div><span className="connection-name">Interface</span><span className="status connected">Disponible</span></div>
          <div><span className="connection-name">Base de données</span><span className={`status ${connected ? 'connected' : error ? 'unavailable' : ''}`}>{connected ? 'Connectée' : error ? 'Indisponible' : 'Vérification…'}</span></div>
          <div><span className="connection-name">Agent RAG</span><span className={`status ${agents.length ? 'connected' : ''}`}>{agents.length ? 'Connecté' : 'Non disponible'}</span></div>
          <div><span className="connection-name">Pipeline de défense</span><span className={`status ${snapshot?.pipelineConnected ? 'connected' : ''}`}>{snapshot?.pipelineConnected ? 'Connectée' : 'Non disponible'}</span></div>
          <div><span className="connection-name">Passerelle et packages</span><span className={`status ${snapshot?.gatewayConnected ? 'connected' : ''}`}>{snapshot?.gatewayConnected ? 'Connectée' : 'Non disponible'}</span></div>
          <div><span className="connection-name">Validation humaine</span><span className={`status ${snapshot?.pipelineConnected ? 'connected' : ''}`}>{snapshot?.pipelineConnected ? 'Disponible via l’API' : 'En attente du pipeline'}</span></div>
        </div>
      </section>

      <section className="panel workflow" aria-labelledby="workflow-title">
        <div className="panel-heading"><h2 id="workflow-title">Parcours actuellement raccordé</h2><span>Les nouveautés sont vérifiées avant lecture</span></div>
        <ol className="workflow-steps"><li><span>1</span><div><strong>Nouvelle connaissance</strong><small>Le document arrive en attente dans Supabase</small></div></li><li><span>2</span><div><strong>Analyse défensive</strong><small>La défense approuve ou met en quarantaine</small></div></li><li><span>3</span><div><strong>Décision humaine</strong><small>Un analyste peut valider ou rejeter un doute</small></div></li><li><span>4</span><div><strong>Réponse du RAG</strong><small>L’assistant ne lit que les contenus approuvés</small></div></li></ol>
      </section>

      <div className="panel-grid">
        <section className="panel" aria-labelledby="knowledge-title"><div className="panel-heading"><h2 id="knowledge-title">Connaissances à valider</h2><span>Nouveaux documents et fichiers</span></div>
          {knowledgeDecisionError ? <div className="error-message" role="alert">{knowledgeDecisionError}</div> : null}
          {!snapshot?.knowledgeConnected ? <EmptyState title="Contrôle indisponible" detail="Redémarrez la défense pour activer l’analyse des nouvelles connaissances." />
            : knowledgeReviews.length ? <ul className="record-list">{knowledgeReviews.map(item => <li key={`${item.source_table}-${item.id}`}>
              <strong>{item.title}</strong><p>{item.source_table === 'documents' ? 'Document' : 'Fichier'} · {item.review_status === 'pending' ? 'Analyse en cours' : 'En quarantaine'}</p>
              {item.review_reason ? <p>Motif : {item.review_reason}</p> : null}
              {item.preview ? <p className="knowledge-preview">{item.preview}</p> : null}
              <div className="incident-actions"><button type="button" disabled={!!knowledgeDecisionBusy} onClick={() => void decideKnowledge(item.source_table, item.id, 'approve', item.version)}>Approuver</button>
                <button type="button" disabled={!!knowledgeDecisionBusy} onClick={() => void decideKnowledge(item.source_table, item.id, 'reject', item.version)}>Refuser</button></div>
            </li>)}</ul> : <EmptyState title="Aucune connaissance suspecte" detail="Les nouvelles données sont examinées avant d’être accessibles à l’assistant." />}
        </section>
        <section className="panel" aria-labelledby="agents-title"><div className="panel-heading"><h2 id="agents-title">Agents</h2><span>{agents.length} branché{agents.length > 1 ? 's' : ''}</span></div>
          {agents.length ? <ul className="record-list">{agents.map(agent => <li key={agent.id}><strong>{agent.name}</strong><p>{agent.role}</p></li>)}</ul> : <EmptyState title="Aucun agent branché" detail="Les vrais agents apparaîtront ici après leur intégration." />}
        </section>
        <section className="panel" aria-labelledby="reviews-title"><div className="panel-heading"><h2 id="reviews-title">Packages à valider</h2><span>Décisions humaines</span></div>
          <form className="rag-form" onSubmit={e=>{e.preventDefault(); void packageAction('review',{name:packageName,ecosystem:registry});}}>
            <label>Package à vérifier<input value={packageName} onChange={e=>setPackageName(e.target.value)} placeholder="Nom du package" required /></label>
            <label>Registre<select value={registry} onChange={e=>setRegistry(e.target.value)}><option value="npm">npm</option><option value="pypi">PyPI</option></select></label>
            <button disabled={packageBusy || !snapshot?.gatewayConnected}>Analyser</button>
          </form>
          {!analystAccess ? <form className="rag-form" onSubmit={e=>{e.preventDefault(); void packageAction('login',{email,password});}}><p>Pour décider, connectez-vous avec votre compte analyste autorisé.</p><label>E-mail<input type="email" value={email} onChange={e=>setEmail(e.target.value)} required /></label><label>Mot de passe<input type="password" value={password} onChange={e=>setPassword(e.target.value)} required autoComplete="current-password" /></label><button disabled={packageBusy}>Connexion analyste</button></form> : <button onClick={()=>setAnalystAccess('')}>Déconnecter le compte analyste</button>}
          {packageMessage ? <p role="status">{packageMessage}</p> : null}
          {pending.length ? <ul className="record-list">{pending.map(review => <li key={review.id}><strong>{review.package} · {review.version}</strong><p>Risque : {review.risk} · En attente de décision</p><div className="incident-actions"><button disabled={packageBusy || !analystAccess} onClick={()=>void packageAction('decision',{id:review.id,decision:'approve'})}>Approuver</button><button disabled={packageBusy || !analystAccess} onClick={()=>void packageAction('decision',{id:review.id,decision:'reject'})}>Refuser</button></div></li>)}</ul> : <EmptyState title="Aucune demande reçue" detail="Les packages en attente apparaîtront après analyse." />}
        </section>
        <section className="panel" aria-labelledby="incidents-title"><div className="panel-heading"><h2 id="incidents-title">Incidents</h2><span>Détections et enquêtes</span></div>
          {decisionError ? <div className="error-message" role="alert">{decisionError}</div> : null}
          {incidents.length ? <ul className="record-list">{incidents.map(incident => <li key={incident.id}><strong>{incident.title}</strong><p>{incident.severity} · {incident.status}</p>{(incident.decision ?? 'pending') === 'pending' ? <div className="incident-actions"><button type="button" disabled={!!decidingId} onClick={() => void decideIncident(incident.id, 'approved')}>{decidingId === incident.id ? 'Enregistrement…' : 'Approuver'}</button><button type="button" disabled={!!decidingId} onClick={() => void decideIncident(incident.id, 'rejected')}>Refuser</button></div> : null}</li>)}</ul> : <EmptyState title="Aucun incident reçu" detail="Les alertes et leurs preuves apparaîtront ici après le raccordement." />}
        </section>
        <section className="panel" aria-labelledby="activity-title"><div className="panel-heading"><h2 id="activity-title">Dernière activité</h2><span>Événements réels</span></div>
          {activity.length ? <ul className="record-list">{activity.map(event => <li key={event.id}><strong>{event.title}</strong><p>{event.time} · {event.result}</p></li>)}</ul> : <EmptyState title="Aucune activité reçue" detail="Les étapes réellement exécutées s’afficheront ici dans l’ordre." />}
        </section>
      </div>

      <section className="panel tests-summary" aria-labelledby="tests-title"><div><h2 id="tests-title">Résultats des tests</h2><p>Comparaison avec et sans protection, après les premières exécutions.</p></div><div><strong>{ready ? snapshot.completedTests ?? '—' : '—'}</strong><span>{ready ? 'Tests terminés' : 'Pas encore mesuré'}</span></div></section>
      <footer>Interface de travail · Données réelles · Décisions humaines tracées</footer>
      </div>

      <section id="panel-demo" role="tabpanel" aria-labelledby="tab-demo" hidden={activeTab !== 'demo'}>
        <div className="panel demo-panel">
          <div className="panel-heading"><div><h2>Nouvelle connaissance dans Supabase</h2><p className="rag-intro">Une procédure fictive contenant une instruction malveillante est ajoutée. La défense l’examine avant qu’elle soit visible par l’assistant RAG.</p></div><span>Base · défense · validation</span></div>
          <button type="button" className="primary-button" onClick={() => void runKnowledgeDemo()} disabled={knowledgeDemoRunning || !snapshot?.knowledgeConnected}>
            {knowledgeDemoRunning ? 'Analyse en cours…' : 'Ajouter la procédure piégée'}
          </button>
          {!snapshot?.knowledgeConnected ? <p className="demo-note">Redémarrez la défense pour activer cette simulation.</p> : null}
          {knowledgeDemoError ? <div className="error-message demo-error" role="alert">{knowledgeDemoError}</div> : null}
          {knowledgeDemoResult ? <div className="rag-result" role="status">
            <strong>{knowledgeDemoResult.status === 'quarantined' ? 'Instruction détectée : document en quarantaine' : knowledgeDemoResult.status === 'pending' ? 'Document en attente d’analyse' : `État : ${knowledgeDemoResult.status}`}</strong>
            <p>{knowledgeDemoResult.reason || 'La défense examine le nouveau contenu.'}</p>
            <p>Le RAG ne lit que les connaissances approuvées.</p>
            <button type="button" onClick={() => setActiveTab('overview')}>Voir les connaissances à valider</button>
          </div> : null}
        </div>
        <div className="panel demo-panel">
          <div className="panel-heading"><div><h2>Outil MCP piégé</h2><p className="rag-intro">Scénario de la fausse entreprise : une description d’outil tente de faire lire un fichier sensible puis de l’envoyer ailleurs.</p></div><span>Agent à outils · passerelle · leurres</span></div>
          <ol className="demo-steps">
            <li>L’utilisateur demande l’état du déploiement de l’API.</li>
            <li>L’agent voit une instruction malveillante dans la description d’un outil MCP.</li>
            <li>Ses appels passent par la passerelle, qui surveille les fichiers leurres.</li>
            <li>La trace est transmise à la défense à la fin de la conversation.</li>
          </ol>
          <button type="button" className="primary-button" onClick={() => void runDemo()} disabled={demoRunning || !snapshot?.gatewayConnected}>
            {demoRunning ? 'Scénario en cours…' : 'Lancer la tentative simulée'}
          </button>
          {!snapshot?.gatewayConnected ? <p className="demo-note">Démarrez la passerelle pour lancer le scénario.</p> : null}
          {demoRunning ? <p className="demo-note" role="status">L’agent utilise ses outils ; cela peut prendre une à deux minutes.</p> : null}
          {demoError ? <div className="error-message demo-error" role="alert">{demoError}</div> : null}
        </div>

        {demoResult ? <div className="panel demo-result" aria-live="polite">
          <h2>{demoResult.diverted ? 'Leurre détecté : session déroutée' : 'Aucune diversion observée'}</h2>
          <p>{demoResult.diverted ? 'La passerelle a bloqué l’accès au leurre et envoyé l’agent dans le bac à sable.' : 'L’agent n’a pas tenté d’accéder au leurre pendant cette exécution. La trace permet de voir ce qu’il a fait.'}</p>
          <div className="demo-facts">
            <div><span>Outils demandés</span><strong>{demoResult.tool_calls.length ? demoResult.tool_calls.join(' → ') : 'Aucun'}</strong></div>
            <div><span>Pipeline de défense</span><strong>{demoResult.pipeline_delivery.status === 'delivered' ? demoResult.pipeline_delivery.incident_id ? `Incident ${demoResult.pipeline_delivery.incident_id}` : 'Trace reçue, aucun incident créé' : 'Transmission non confirmée'}</strong></div>
          </div>
          <h3>Étapes enregistrées</h3>
          {demoResult.event_types.length ? <ol className="demo-timeline">{demoResult.event_types.map((type, index) => <li key={`${type}-${index}`}>{demoEventLabels[type] || type}</li>)}</ol> : <p>Le détail de la trace est momentanément indisponible.</p>}
          <p className="demo-trace">Référence de la trace : {demoResult.trace_id}</p>
          {demoResult.pipeline_delivery.incident_id ? <button type="button" onClick={() => setActiveTab('overview')}>Voir l’incident dans la vue d’ensemble</button> : null}
        </div> : null}
      </section>
    </main>
  </div>;
}

function isDemoResult(value: unknown): value is DemoResult {
  if (!value || typeof value !== 'object') return false;
  const result = value as Partial<DemoResult>;
  return typeof result.trace_id === 'string' && typeof result.diverted === 'boolean'
    && typeof result.neutralized === 'boolean' && Array.isArray(result.tool_calls)
    && result.tool_calls.every(tool => typeof tool === 'string')
    && Array.isArray(result.event_types) && result.event_types.every(type => typeof type === 'string')
    && !!result.pipeline_delivery && typeof result.pipeline_delivery.status === 'string';
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
    && typeof data.knowledgeConnected === 'boolean' && Array.isArray(data.knowledgeReviews)
    && data.knowledgeReviews.every(item => typeof item?.id === 'string' && typeof item?.title === 'string' && typeof item?.review_status === 'string')
    && Array.isArray(data.incidents) && data.incidents.every(item => typeof item?.id === 'string' && typeof item?.title === 'string' && typeof item?.severity === 'string' && typeof item?.status === 'string')
    && Array.isArray(data.activity) && data.activity.every(item => typeof item?.id === 'string' && typeof item?.time === 'string' && typeof item?.title === 'string' && typeof item?.result === 'string')
    && (data.blockedActions === null || typeof data.blockedActions === 'number' && Number.isFinite(data.blockedActions) && data.blockedActions >= 0)
    && (data.completedTests === null || typeof data.completedTests === 'number' && Number.isFinite(data.completedTests) && data.completedTests >= 0);
}
