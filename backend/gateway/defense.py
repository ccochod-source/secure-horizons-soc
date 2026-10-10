"""Relais de conversations masquées et suspension persistante des outils.

SQLite conserve les accusés de livraison locaux : un résultat incertain n'est
jamais retransmis automatiquement. Les événements restent dans Supabase.
"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit


def adapt_event(row):
    content = row.get('content') or '{}'
    try:
        payload = json.loads(content)
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    tool = row.get('action') or ''
    resource = row.get('resource_id') or ''
    if tool == 'read_file':
        arguments = payload.get('arguments') if isinstance(payload.get('arguments'), dict) else {}
        outcome = payload.get('result') if isinstance(payload.get('result'), dict) else {}
        resource = arguments.get('path') or outcome.get('path') or resource
    if tool in {'send_message', 'http.post', 'github.publish', 'email.send', 'slack.post', 'webhook.send'}:
        resource = 'external/' + tool
    result = row.get('result')
    status = 'blocked' if result in {'blocked', 'denied'} else 'flagged' if result in {'pending','error'} or result is None else 'allowed'
    stamp = row.get('occurred_at') or datetime.now(timezone.utc)
    return dict(id=str(row['id']), parent_event_id=str(row['parent_event_id']) if row.get('parent_event_id') else None,
                timestamp=stamp.isoformat() if hasattr(stamp,'isoformat') else str(stamp),
                actor=row['actor_id'], type=row['event_type'], title=row['event_type'],
                description=content, tool=tool, resource=resource, result=status)


class DefenseBridge:
    def __init__(self, db, http, url, token, path):
        address = urlsplit(url)
        if address.scheme != 'http' or address.hostname not in {'127.0.0.1', 'localhost', '::1'} or address.username or address.password or address.query or address.fragment:
            raise ValueError('Le relais de défense doit utiliser une adresse HTTP locale.')
        self.db, self.http, self.url, self.token = db, http, url.rstrip('/'), token
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connect() as c:
            c.execute('create table if not exists deliveries (trace_id text primary key, state text, response text)')
            c.execute('create table if not exists suspensions (agent_id text, tool text, incident_id text, approved_by text, primary key(agent_id,tool))')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def suspended(self, agent, tool):
        with self.connect() as c:
            return c.execute('select 1 from suspensions where agent_id=? and tool=?',(agent,tool)).fetchone() is not None

    def suspend(self, agent, tool, incident, approved_by):
        with self.connect() as c:
            c.execute('insert or replace into suspensions values (?,?,?,?)',(agent,tool,incident,approved_by))
        if not self.suspended(agent,tool):
            raise RuntimeError('Suspension non confirmée')

    async def complete(self, session):
        trace = str(session.trace_id)
        # Claim before networking; concurrency and restart cannot duplicate an incident.
        with self.connect() as c:
            claimed = c.execute('insert or ignore into deliveries values (?, ?, ?)',(trace,'uncertain','{}')).rowcount
            if not claimed:
                state, response = c.execute('select state,response from deliveries where trace_id=?',(trace,)).fetchone()
                return {'status':state, **json.loads(response)}
        try:
            async with self.db.as_owner() as conn:
                rows = await (await conn.execute('select * from public.events where trace_id=%s order by occurred_at,id',(session.trace_id,))).fetchall()
            response = await self.http.post(self.url+'/events',headers={'Authorization':'Bearer '+self.token},
                                           json={'agent_id':session.agent_id,'events':[adapt_event(r) for r in rows]},timeout=90)
            if response.status_code != 200:
                return {'status':'uncertain'}
            incident = response.json().get('incident')
            result = {'incident_id':incident.get('id') if incident else None}
            with self.connect() as c:
                c.execute('update deliveries set state=?,response=? where trace_id=?',('delivered',json.dumps(result),trace))
            return {'status':'delivered', **result}
        except Exception:
            return {'status':'uncertain'}
