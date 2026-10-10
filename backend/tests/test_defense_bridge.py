from datetime import datetime, timezone
from uuid import uuid4
import httpx
import asyncio
from gateway.defense import DefenseBridge, adapt_event


def test_mapping_retains_sensitive_path_and_attempt():
    row=dict(id=uuid4(),parent_event_id=None,occurred_at=datetime.now(timezone.utc),actor_id='dev-test',event_type='tool_call',action='read_file',resource_id='read_file',result=None,content='{"arguments":{"path":".env.demo"}}')
    event=adapt_event(row)
    assert event['resource']=='.env.demo' and event['result']=='flagged'
    row.update(action='send_message',result='blocked',content='{}')
    event=adapt_event(row)
    assert event['resource'].startswith('external/') and event['result']=='blocked'


def test_suspension_survives_new_instance_and_is_scoped(tmp_path):
    path=tmp_path/'state.sqlite'
    bridge=DefenseBridge(None,None,'http://localhost:8000','test',path)
    bridge.suspend('dev-test','send_message','INC-test','analyste-test')
    restored=DefenseBridge(None,None,'http://localhost:8000','test',path)
    assert restored.suspended('dev-test','send_message')
    assert not restored.suspended('other-agent','send_message')
    assert not restored.suspended('dev-test','read_file')


def test_uncertain_delivery_is_not_replayed(tmp_path):
    asyncio.run(_uncertain(tmp_path))


async def _uncertain(tmp_path):
    class Conn:
        async def execute(self,*args): return self
        async def fetchall(self): return []
    from contextlib import asynccontextmanager
    class DB:
        @asynccontextmanager
        async def as_owner(self): yield Conn()
    calls=[]
    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout('uncertain')
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        bridge=DefenseBridge(DB(),client,'http://localhost:8000','test',tmp_path/'state.sqlite')
        from gateway.session import Session
        session=Session('dev-test')
        assert (await bridge.complete(session))['status']=='uncertain'
        assert (await bridge.complete(session))['status']=='uncertain'
        assert len(calls)==1


def test_confinement_rejects_unsupported_actions_and_confirms_persistence(tmp_path):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.main import create_app
    path=tmp_path/'guard.sqlite'
    bridge=DefenseBridge(None,None,'http://localhost:8000','test',path)
    app=create_app(gateway=SimpleNamespace(tools=lambda:[{'name':'send_message'}]))
    app.state.defense=bridge
    app.state.confinement_token='private-test-token'
    body={'incident_id':'INC-test','action':'suspendre_outil','cible':'send_message','agent_id':'test-agent','approuve_par':'test-analyst'}
    with TestClient(app) as client:
        assert client.post('/confinement',json=body).status_code==401
        headers={'Authorization':'Bearer private-test-token'}
        assert client.post('/confinement',json={**body,'action':'revoquer_secret'},headers=headers).status_code==422
        assert client.post('/confinement',json={**body,'cible':'unknown'},headers=headers).status_code==422
        assert not bridge.suspended('test-agent','send_message')
        assert client.post('/confinement',json=body,headers=headers).status_code==200
    restored=DefenseBridge(None,None,'http://localhost:8000','test',path)
    assert restored.suspended('test-agent','send_message')
