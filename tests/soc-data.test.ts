import assert from 'node:assert/strict';
import test from 'node:test';
import {mapSocRows,redact,type SocRows} from '../src/lib/soc-data.ts';

const empty=():SocRows=>({incidents:[],events:[],inventory:[],access:[],alerts:[],findings:[],actions:[],runs:[],scenarios:[]});

test('chaîne partielle : ne fabrique ni preuve ni action exécutée',()=>{
  const rows=empty();
  rows.incidents=[{id:'i1',reference:'INC-1',trace_id:'t1',agent:'victim',severity:'low',status:'awaiting_decision'}];
  rows.events=[{id:'e1',trace_id:'t1',parent_event_id:'absent',result:'failed',occurred_at:'2026-10-10T12:00:00Z',event_type:'file_read'}];
  rows.alerts=[{id:'a1',trace_id:'t1',incident_id:'i1'}];
  rows.findings=[{id:'f1',alert_id:'a1',claim:'À vérifier',verification_status:'validated',evidence_event_ids:['e1','unknown']}];
  rows.actions=[{id:'action1',alert_id:'a1',action_type:'suspend_mcp_tool',target:'export',status:'approved',mode:'manual'}];
  const incident=mapSocRows(rows).incidents[0];
  assert.equal(incident.severity,'Faible');
  assert.equal(incident.status,'En attente de décision');
  assert.equal(incident.events[0].result,'unknown');
  assert.equal(incident.missingParents,1);
  assert.deepEqual(incident.evidence,['e1']);
  assert.deepEqual(incident.findings?.[0].missingEvidence,['unknown']);
  assert.equal(incident.storedActions?.[0].status,'approved');
  assert.equal(incident.proposal,'Aucune action proposée en attente.');
});

test('inventaire sans activité : ne présente pas un agent comme opérationnel',()=>{
  const rows=empty();rows.inventory=[{id:'agent1',kind:'agent',name:'investigator',is_defender:true}];
  const snapshot=mapSocRows(rows);
  assert.equal(snapshot.agents[0].status,'Inventorié');
  assert.equal(snapshot.agents[0].events,0);
  assert.deepEqual(snapshot.incidents,[]);
  assert.deepEqual(snapshot.agents[0].tools,[]);
});

test('benchmark absent ou inachevé : aucun résultat de protection inventé',()=>{
  const rows=empty();rows.scenarios=[{id:'s1',name:'Extraction'}];
  rows.runs=[{id:'r1',scenario_id:'s1',protection_mode:'protected',ended_at:null,exports_blocked:1}];
  const benchmark=mapSocRows(rows).benchmarks[0];
  assert.equal(benchmark.without,'Aucune exécution enregistrée');
  assert.equal(benchmark.with,'Exécution en cours');
  assert.equal(benchmark.measured,false);
});

test('texte de preuve : masque les clés courantes',()=>{
  const value='ghp_'+'a'.repeat(36);
  assert.equal(redact('clé '+value),'clé [SECRET MASQUÉ]');
  assert.equal(redact('password=hunter2'),'password=[MASQUÉ]');
});


test('actions du pipeline : pending_approval reste une proposition',()=>{
  const rows=empty();rows.incidents=[{id:'i',reference:'INC',trace_id:'trace',agent:'dev'}];
  rows.actions=[{id:'a',incident_id:'i',action_type:'revoke_key',target:'SECRET_1',status:'pending_approval',mode:'analyst_approval'}];
  const incident=mapSocRows(rows).incidents[0];
  assert.equal(incident.proposal,'Révoquer la clé : SECRET_1');
  assert.equal(incident.storedActions?.[0].status,'pending_approval');
});
