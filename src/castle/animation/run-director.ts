import type { CastleAnimator } from './animator';
import type { BlockId, DefenderStep, TraceStep } from './pipeline-trace';
import { TESTS, type ContreVerification, type DefenseIncident, type KnowledgeAdmission, type RunEvent, type RunOutcome, type RunTrace, type TestKind } from './run-types';

/**
 * Metteur en scène d'un test réel : chaque nouvel événement de `public.events` déclenche
 * l'animation correspondante, dans l'ordre et au moment où il arrive. Rien n'est joué sans événement.
 */
export class RunDirector {
  private seen = new Set<string>();
  private queue: Promise<void> = Promise.resolve();
  private reviewState: string | null = null;
  private incidentKey = '';
  private cvStatut = '';
  private kStatus = '';
  private cancelled = false;

  /** Arrête ce metteur en scène : plus aucune animation n'est programmée (enchaînement d'attaques). */
  dispose() { this.cancelled = true; }

  /** Admission du guide : pigeon au dépôt, alerte et trône en quarantaine, victoire si refusé. */
  updateKnowledge(k: KnowledgeAdmission | null) {
    if (this.cancelled || !k || k.status === this.kStatus) return;
    const prev = this.kStatus;
    this.kStatus = k.status;
    const a = this.animator;
    this.queue = this.queue.then(async () => {
      if (!prev) void a.mailArrive();
      if (k.status === 'quarantined') {
        await a.setAlarm('Modérée');
        await a.throneAttention(true);
      } else if (k.status === 'approved') {
        await a.throneAttention(false);
      } else if (k.status === 'rejected') {
        await a.throneAttention(false);
        await a.setAlarm('off');
        await a.victory();
        a.clearBattle();
      }
    }).catch(() => {});
  }

  /** Contre-vérification : alarme pendant l'attente de confirmation, retrait animé si l'analyste annule. */
  updateReverification(cvr: ContreVerification | null) {
    if (this.cancelled || !cvr || cvr.statut === this.cvStatut) return;
    this.cvStatut = cvr.statut;
    const a = this.animator;
    this.queue = this.queue.then(async () => {
      if (cvr.statut === 'attente_confirmation') {
        await a.setAlarm('Modérée');
        await a.throneAttention(true);
      } else if (cvr.statut === 'retire') {
        await a.throneAttention(false);
        await a.packageRemoved(cvr.package);
        await a.setAlarm('off');
      } else if (cvr.statut === 'maintenu' || cvr.statut === 'confirmee') {
        await a.throneAttention(false);
        await a.setAlarm('off');
      }
    }).catch(() => {});
  }

  constructor(private readonly animator: CastleAnimator, readonly kind: TestKind) {}

  /** À appeler à chaque relevé ; ne joue que ce qui est nouveau. */
  update(trace: RunTrace) {
    if (this.cancelled) return;
    for (const ev of trace.events) {
      if (this.seen.has(ev.id)) continue;
      this.seen.add(ev.id);
      this.queue = this.queue.then(() => this.play(ev)).catch(() => {});
    }
    const state = trace.review?.state ?? null;
    if (state && state !== this.reviewState) {
      const prev = this.reviewState;
      this.reviewState = state;
      this.queue = this.queue.then(() => this.playReview(prev, state)).catch(() => {});
    }
  }

  /** Enquête des agents défenseurs (backend 8000) : remparts à l'ouverture, sortie à l'exécution de la mesure. */
  updateIncident(inc: DefenseIncident | null) {
    if (this.cancelled || !inc) return;
    const key = `${inc.status}|${inc.decision}|${inc.execution.etat}`;
    if (key === this.incidentKey) return;
    const prev = this.incidentKey;
    this.incidentKey = key;
    const a = this.animator;
    this.queue = this.queue.then(async () => {
      if (!prev) {
        await a.setAlarm(inc.severity === 'Critique' ? 'Critique' : inc.severity === 'Élevée' ? 'Élevée' : 'Modérée');
        await a.defend(4, 2);
        if (inc.decision === 'pending') await a.throneAttention(true);
      }
      if (inc.decision !== 'pending' || inc.execution.etat === 'echec') await a.throneAttention(false);
      if (inc.status === 'Confiné') {
        await a.sortie(2);
        await a.setAlarm('off');
      } else if (inc.decision === 'rejected') {
        await a.setAlarm('off');
      }
    }).catch(() => {});
  }

  private async play(ev: RunEvent) {
    if (this.cancelled) return;
    const a = this.animator;
    if (this.kind === 'leurres') {
      switch (ev.type) {
        case 'user_request':
          void a.mailArrive();
          void a.attack(7);
          return;
        case 'decoy_access':
          await a.setAlarm('Critique');
          await a.defend(4, 2);
          return;
        case 'session_diverted':
          await a.startSandbox();
          return;
        case 'agent_response':
          if (a.sandboxActive) {
            await a.stopSandbox();
            await a.setAlarm('off');
            await a.victory();
            await a.tweens.wait(1.5);
            a.clearBattle();
          } else {
            await a.retreat();
          }
          return;
      }
      return;
    }
    switch (ev.type) {
      case 'package_install_requested':
        await a.packageArrives(String((ev.content?.arguments as Record<string, unknown> | undefined)?.name ?? 'package'));
        a.packageInspecting(true);
        return;
    }
  }

  private async playReview(prev: string | null, state: string) {
    if (this.cancelled) return;
    const a = this.animator;
    if (state === 'pending_approval') {
      a.packageInspecting(false);
      await a.packageBlocked();
    } else if (state === 'executed' && (prev === null || prev === 'proposed')) {
      // sain : installé automatiquement
      a.packageInspecting(false);
      await a.packageInstalled();
    } else if (state === 'approved' || (state === 'executed' && prev === 'pending_approval')) {
      await a.packageDecided('approved');
    } else if (state === 'rejected') {
      await a.packageDecided('rejected');
    }
  }
}

// ---------------------------------------------------------------------------------------------
// Explications en français simple
// ---------------------------------------------------------------------------------------------

export interface Narration {
  id: string;
  state: 'done' | 'active' | 'error' | 'skip';
  title: string;
  /** Ce que ça veut dire, sans jargon. */
  meaning: string;
  /** Ce que l'on voit dans le château. */
  castle?: string;
}

const first = (t: RunTrace, type: string) => t.events.find((e) => e.type === type);
const text = (e: RunEvent | undefined) => String(e?.content?.text ?? '');

function decoyLabel(e: RunEvent | undefined): string {
  const decoys = (e?.content?.decoys as string[] | undefined) ?? [];
  const where = (e?.content?.locations as string[] | undefined) ?? [];
  if (!decoys.length) return e?.resourceId ?? 'un leurre';
  return decoys.map((d, i) => `${d}${where[i] ? ` (${where[i].replace(/^docs:/, 'document « ').replace(/^files?:/, 'fichier « ')}${where[i].includes(':') ? ' »' : ''})` : ''}`).join(', ');
}

export function narrate(kind: TestKind, trace: RunTrace | null, outcome: RunOutcome | null, running: boolean, incident: DefenseIncident | null = null, cvr: ContreVerification | null = null, knowledge: KnowledgeAdmission | null = null): Narration[] {
  const out: Narration[] = [];
  if ((kind === 'packages' || kind === 'document') && knowledge) {
    out.push({ id: 'k-dep', state: 'done', title: `Nouveau document déposé : « ${knowledge.title} »`, meaning: 'Il contient une consigne cachée pour l’assistant : installer « pdfreport-turbo ». Tant qu’il n’est pas validé, aucun agent ne peut le lire.', castle: 'Un pigeon apporte le document.' });
    if (knowledge.status === 'pending') out.push({ id: 'k-wait', state: 'active', title: 'Admission des connaissances : analyse en cours…', meaning: 'Règles de détection, puis une IA qui traite le document comme une donnée (jamais comme une instruction).' });
    else if (knowledge.status === 'quarantined') out.push({ id: 'k-q', state: 'error', title: 'Document mis en quarantaine par l’admission', meaning: knowledge.reason ?? '', castle: 'Alerte et trône allumés : un analyste doit trancher (voir en haut).' });
    else if (knowledge.status === 'rejected') out.push({ id: 'k-r', state: 'done', title: knowledge.decidedByAnalyst ? 'Refusé par l’analyste : attaque stoppée en amont' : 'Document refusé', meaning: 'Le guide piégé ne sera jamais lu par DevBot : l’attaque s’arrête avant même d’atteindre l’agent.', castle: 'Victoire sans combat.' });
    else if (knowledge.status === 'approved') out.push({ id: 'k-a', state: knowledge.decidedByAnalyst ? 'error' : 'done', title: knowledge.decidedByAnalyst ? 'L’analyste a laissé passer le document : l’attaque continue' : 'Document approuvé par l’admission', meaning: 'DevBot peut désormais le lire. Les défenses suivantes prennent le relais : contrôle des packages, puis agents défenseurs.' });
    if (kind === 'document' || knowledge.status !== 'approved') return out;
  }
  const t = trace ?? { traceId: null, events: [], review: null };
  const req = first(t, 'user_request');
  if (running && !req) {
    out.push({ id: 'send', state: 'active', title: 'Envoi de la demande à la passerelle…', meaning: TESTS[kind].prompt });
  }
  if (req) {
    out.push({
      id: 'req', state: 'done',
      title: kind === 'leurres' ? 'L’agent DevBot reçoit une demande' : 'Une installation de package est demandée',
      meaning: `« ${text(req) || TESTS[kind].prompt} »`,
      castle: kind === 'leurres' ? 'Des guerriers rouges approchent : c’est la demande, potentiellement malveillante.' : undefined,
    });
  }
  if (kind === 'leurres') {
    const calls = t.events.filter((e) => e.type === 'tool_call');
    if (calls.length) {
      out.push({ id: 'tools', state: 'done', title: `Il utilise ${calls.length > 1 ? `${calls.length} outils` : 'un outil'} : ${[...new Set(calls.map((c) => c.action))].join(', ')}`, meaning: 'Chaque appel passe par la passerelle, qui l’enregistre et vérifie les résultats avant de les rendre à l’agent.' });
    }
    const decoy = first(t, 'decoy_access');
    if (decoy) {
      out.push({
        id: 'decoy', state: 'error', title: `Piège touché : ${decoyLabel(decoy)}`,
        meaning: 'Ce sont de fausses clés plantées exprès : aucun usage normal n’en a besoin. Les lire prouve que la session est compromise.',
        castle: 'Fumée d’alarme sur la tour de guet, chevaliers et archers aux remparts.',
      });
    }
    const div = first(t, 'session_diverted');
    const end = first(t, 'agent_response');
    const fake = t.events.filter((e) => e.type === 'tool_response' && e.result === 'blocked');
    if (div) {
      const size = fake.reduce((n, e) => n + Number(e.content?.size ?? 0), 0);
      out.push({
        id: 'sandbox', state: end ? 'done' : 'active',
        title: end ? 'Bac à sable terminé' : 'Bac à sable en cours : l’agent est détourné',
        meaning: `À partir de maintenant, l’agent ne touche plus rien de réel : il ne reçoit que des données factices${size ? ` (${size.toLocaleString('fr-FR')} caractères de leurre)` : ''}, qui l’occupent sans rien lui apprendre.`,
        castle: end ? 'La tornade a aspiré tous les assaillants : plus aucun ennemi.' : 'Une tornade de sable aspire les assaillants pendant toute la durée du traitement.',
      });
    }
    if (end) {
      out.push({
        id: 'end', state: 'done', title: div ? 'Attaque neutralisée, aucune donnée réelle n’est sortie' : 'Aucun piège touché',
        meaning: div ? `Réponse finale de l’agent : « ${text(end).slice(0, 180)}${text(end).length > 180 ? '…' : ''} »` : 'L’agent a répondu sans lire de leurre : rien à signaler.',
      });
    }
  } else {
    const asked = first(t, 'package_install_requested');
    const r = t.review;
    if (asked) {
      const name = String((asked.content?.arguments as Record<string, unknown> | undefined)?.name ?? '');
      out.push({ id: 'pkg', state: 'done', title: `Package demandé : ${name}`, meaning: 'La passerelle intercepte la demande : rien n’est installé avant le contrôle.', castle: 'Une caisse (le package) arrive devant le pont.' });
      if (!r || r.state === 'proposed') {
        out.push({ id: 'check', state: 'active', title: 'Contrôle en cours…', meaning: 'Existence sur le registre, ressemblance avec un package connu, analyse de l’archive, réputation.', castle: 'La caisse clignote en orange : inspection.' });
      }
    }
    if (r) {
      const reasons = r.signals.map((s) => s.explanation).join(' ');
      const decidedByHuman = t.events.some((e) => e.type === 'package_review' && (e.action === 'approve' || e.action === 'reject'));
      if (r.state === 'executed' && !decidedByHuman) {
        out.push({ id: 'ok', state: 'done', title: 'Package sain : installé automatiquement', meaning: reasons || 'Aucun signal suspect.', castle: 'La caisse devient verte et entre au château.' });
      } else {
        out.push({ id: 'verdict', state: 'error', title: `Package suspect : ${r.packageName} (risque ${r.risk === 'critical' ? 'critique' : r.risk})`, meaning: reasons, castle: 'La caisse devient rouge et reste bloquée devant le pont relevé, sous un faisceau rouge.' });
        if (r.state === 'pending_approval') {
          out.push({ id: 'wait', state: 'active', title: 'Une seule décision vous attend (voir en haut)', meaning: 'Le système ne décide jamais seul pour un package suspect. Votre décision, avec votre compte analyste, tranche aussi l’enquête des agents.' });
        } else if (r.state === 'rejected') {
          out.push({ id: 'rej', state: 'done', title: 'Refusé par l’analyste', meaning: 'Le package ne sera jamais installé.', castle: 'La caisse coule dans les douves, le pont se rouvre.' });
        } else if (['approved', 'executed', 'failed'].includes(r.state)) {
          out.push({ id: 'app', state: r.state === 'failed' ? 'error' : 'done', title: r.state === 'failed' ? 'Approuvé mais installation impossible' : 'Approuvé par l’analyste', meaning: r.state === 'failed' ? 'Le package n’existe pas sur le registre : il n’y a rien à installer.' : 'Le package est installé.', castle: 'La caisse devient verte et entre au château.' });
        }
      }
    }
  }
  if (outcome && !outcome.ok) out.push({ id: 'err', state: 'error', title: 'Le test a échoué', meaning: outcome.error ?? 'Erreur inconnue.' });
  const agentDone = t.events.some((e) => e.type === 'agent_response');
  if (running && agentDone && !outcome) {
    out.push({ id: 'def-wait', state: 'active', title: 'Agents défenseurs : analyse de la session…', meaning: 'La passerelle transmet la session au backend de défense (règle, puis enquêteur IA, puis vérificateur).' });
  }
  if (outcome?.ok && !outcome.defenseIncidentId) {
    out.push({
      id: 'def-none', state: 'skip', title: 'Agents défenseurs : pas d’enquête ouverte',
      meaning: kind === 'leurres'
        ? 'Leur règle porte sur les sorties de données et les installations bloquées. Ici le bac à sable a coupé l’attaque avant toute sortie : aucune enquête n’a été ouverte (l’alerte du détecteur de pièges reste dans Supabase).'
        : 'Aucune installation n’a été bloquée dans cette session : rien à enquêter.',
    });
  }
  if (outcome?.ok && outcome.defenseIncidentId && !incident) {
    out.push({ id: 'def-load', state: 'active', title: `Agents défenseurs : incident ${outcome.defenseIncidentId} ouvert`, meaning: 'Chargement de l’enquête…' });
  }
  if (incident) {
    const ok = incident.conclusions.filter((c) => c.verifiee).length;
    out.push({ id: 'def-sent', state: 'done', title: `Sentinelle : alerte levée → incident ${incident.id}`, meaning: kind === 'packages' ? 'Règle : installation d’un package bloquée par la passerelle.' : 'Règle : accès à un leurre (la session a été déroutée vers le bac à sable).' });
    out.push({ id: 'def-enq', state: 'done', title: `Enquêteur IA : « ${incident.title} »`, meaning: incident.description });
    out.push({
      id: 'def-ver', state: incident.confidence >= 0.7 ? 'done' : 'error',
      title: `Vérificateur : ${ok}/${incident.conclusions.length} conclusion(s) prouvée(s) → les agents sont sûrs à ${Math.round(incident.confidence * 100)} % que : « ${incident.title} »`,
      meaning: incident.conclusions.map((c) => `${c.verifiee ? '✓' : '✗'} ${c.affirmation}`).join(' '),
    });
    const prop = `${incident.proposal}. ${incident.impact}`;
    if (incident.decision === 'pending') out.push({ id: 'def-prop', state: 'active', title: kind === 'packages' ? 'Mesure proposée par les agents : incluse dans votre décision sur le package (voir en haut)' : 'Mesure proposée par les agents : à vous de décider (voir en haut)', meaning: prop, castle: 'Chevaliers aux remparts, trône allumé.' });
    else if (incident.status === 'Confiné') out.push({ id: 'def-app', state: 'done', title: 'Mesure appliquée par la passerelle', meaning: `${prop} Exécution confirmée : ${incident.execution.detail}`, castle: 'Les chevaliers font une sortie, l’alarme s’éteint.' });
    else if (incident.decision === 'approved') out.push({ id: 'def-exec', state: incident.execution.etat === 'echec' ? 'error' : 'active', title: incident.execution.etat === 'echec' ? 'Mesure approuvée mais non exécutée' : 'Mesure approuvée, exécution en cours…', meaning: incident.execution.detail || prop });
    else out.push({ id: 'def-rej', state: 'done', title: 'Mesure refusée : incident sous surveillance', meaning: 'Aucune restriction appliquée à l’agent.' });
  }
  if (t.review?.humanDecision === 'approve') {
    const pct = (x: number | null) => (x === null ? 'aucune enquête' : `${Math.round(x * 100)} %`);
    if (!cvr) out.push({ id: 'cv-wait', state: 'active', title: 'Package autorisé par un humain : deuxième vérification des agents…', meaning: 'Règle : chaque autorisation humaine d’un package bloqué est revérifiée (registre, vulnérabilités), puis confirmée si besoin par l’analyste qui a autorisé.' });
    else {
      out.push({
        id: 'cv-done', state: cvr.verdict === 'sur' ? 'done' : 'error',
        title: `Deuxième vérification des agents : verdict « ${cvr.verdict === 'sur' ? 'sûr' : cvr.verdict} »`,
        meaning: `Enquête initiale : ${cvr.conclusion_initiale ? `« ${cvr.conclusion_initiale} », certitude ${pct(cvr.confiance_initiale)}` : 'aucune'}. ${cvr.resume ?? ''}${cvr.correction ? ` ${cvr.correction}` : ''}`,
      });
      if (cvr.statut === 'attente_confirmation' || cvr.statut === 'retrait_en_echec') out.push({ id: 'cv-ask', state: 'active', title: 'Confirmation demandée à l’analyste qui a approuvé (voir en haut)', meaning: cvr.question ?? '', castle: 'Alarme et trône allumés.' });
      if (cvr.statut === 'maintenu') out.push({ id: 'cv-keep', state: 'done', title: 'L’analyste maintient son choix : le package reste installé', meaning: '' });
      if (cvr.statut === 'retire') out.push({ id: 'cv-rm', state: 'done', title: 'Package retiré de la base', meaning: 'Désinstallé chez l’agent, supprimé de l’inventaire, revue passée à « refusé ».', castle: 'La caisse ressort des réserves et est jetée dans les douves.' });
      if (cvr.statut === 'confirmee') out.push({ id: 'cv-ok', state: 'done', title: 'Les agents confirment : le package est sûr', meaning: '' });
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// Étapes du schéma « six blocs »
// ---------------------------------------------------------------------------------------------

export function traceRun(kind: TestKind, trace: RunTrace | null, outcome: RunOutcome | null, incident: DefenseIncident | null = null, knowledge: KnowledgeAdmission | null = null): TraceStep[] {
  const t = trace ?? { traceId: null, events: [], review: null };
  const steps: TraceStep[] = [];
  if ((kind === 'packages' || kind === 'document') && knowledge) {
    const st = knowledge.status === 'pending' ? 'active' : knowledge.status === 'quarantined' ? 'active' : knowledge.status === 'rejected' ? 'done' : knowledge.decidedByAnalyst ? 'error' : 'done';
    steps.push({ id: 'k', block: 'inventory', state: st, label: `Admission des connaissances : ${knowledge.status === 'pending' ? 'analyse…' : knowledge.status === 'quarantined' ? 'quarantaine, décision humaine requise' : knowledge.status === 'rejected' ? 'document refusé, attaque stoppée' : 'document approuvé'}`, detail: knowledge.reason ?? undefined });
  }
  if (!t.events.length) return steps;
  const push = (id: string, block: BlockId, state: TraceStep['state'], label: string, detail?: string, sub?: DefenderStep) => steps.push({ id, block, state, label, detail, sub });
  const req = first(t, 'user_request');
  push('env', 'env', 'done', `DevBot : ${kind === 'leurres' ? 'demande reçue' : 'installation demandée'}`, text(req) || undefined);
  const calls = t.events.filter((e) => e.type === 'tool_call' || e.type === 'package_install_requested');
  const tokens = new Set<string>();
  for (const e of t.events) for (const k of (e.content?.tokens as string[] | undefined) ?? []) tokens.add(k);
  push('gateway', 'gateway', 'done', `${t.events.length} événement(s) tracé(s), ${calls.length} appel(s) intercepté(s)`, tokens.size ? `Valeurs masquées par le coffre : ${[...tokens].join(', ')}` : 'Aucun secret à masquer');
  if (kind === 'leurres') {
    const decoy = first(t, 'decoy_access');
    const end = first(t, 'agent_response');
    if (decoy) push('decoy', 'decoys', 'error', `Leurre touché : ${decoyLabel(decoy)}`);
    if (first(t, 'session_diverted')) push('sandbox', 'decoys', end ? 'done' : 'active', end ? 'Bac à sable : agent neutralisé' : 'Bac à sable en cours…');
    else if (end) push('nodecoy', 'decoys', 'done', 'Aucun leurre touché');
  } else {
    const r = t.review;
    const name = String((first(t, 'package_install_requested')?.content?.arguments as Record<string, unknown> | undefined)?.name ?? '');
    if (!r || r.state === 'proposed') push('pkgcheck', 'packages', 'active', `Contrôle de ${name}…`);
    else if (r.state === 'pending_approval') push('pkgwait', 'packages', 'active', `${r.packageName} bloqué : décision humaine requise`, r.recommendation);
    else if (r.state === 'rejected') push('pkgrej', 'packages', 'done', `${r.packageName} refusé par l’analyste`);
    else if (r.state === 'failed') push('pkgfail', 'packages', 'error', `${r.packageName} approuvé mais introuvable : rien installé`);
    else push('pkgok', 'packages', 'done', `${r.packageName} installé`, r.recommendation || undefined);
  }
  push('inventory', 'inventory', 'done', `${t.events.length} événement(s) enregistré(s) dans Supabase`);
  if (incident) {
    const ok = incident.conclusions.filter((c) => c.verifiee).length;
    push('sentinelle', 'defenders', 'done', `Sentinelle : incident ${incident.id} ouvert`, undefined, 'sentinelle');
    push('enqueteur', 'defenders', 'done', `Enquêteur IA : ${incident.conclusions.length} conclusion(s)`, incident.title, 'enqueteur');
    push('verificateur', 'defenders', incident.confidence >= 0.7 ? 'done' : 'error', `Vérificateur : ${ok}/${incident.conclusions.length} prouvée(s), confiance ${Math.round(incident.confidence * 100)} %`, undefined, 'verificateur');
    const echec = incident.execution.etat === 'echec';
    const conf = incident.status === 'Confiné' || incident.decision === 'rejected' ? 'done' : echec ? 'error' : 'active';
    push('confineur', 'defenders', conf, `Confineur : ${incident.status === 'Confiné' ? 'mesure exécutée' : incident.decision === 'rejected' ? 'mesure refusée' : echec ? 'la passerelle n’a pas pu exécuter la mesure' : incident.decision === 'approved' ? 'exécution en cours' : 'attend votre décision'}`, echec ? incident.execution.detail : incident.proposal, 'confineur');
    push('rapporteur', 'defenders', incident.status === 'Confiné' || incident.decision === 'rejected' ? 'done' : echec ? 'error' : 'active', `Rapporteur : ${echec ? 'clos sur un échec d’exécution' : incident.status}`, undefined, 'rapporteur');
  } else if (outcome?.ok) {
    push('sentinelle', 'defenders', 'skip', 'Agents défenseurs : non analysé (aucune règle déclenchée)', kind === 'leurres' ? 'Leur règle ne couvre pas encore l’accès à un leurre.' : undefined, 'sentinelle');
  } else if (t.events.some((e) => e.type === 'agent_response')) {
    push('sentinelle', 'defenders', 'active', 'Agents défenseurs : analyse en cours…', undefined, 'sentinelle');
  }
  return steps;
}
