#!/usr/bin/env python3
"""Plante (ou re-dépose) un document de l'arsenal dans public.documents, avec le compte propriétaire.

    .venv/bin/python scripts/castle/plant_doc.py --id doc-injection
    .venv/bin/python scripts/castle/plant_doc.py --remove       # retire tout ce qui a source = 'arsenal'

Les documents portent source = 'arsenal'. Le trigger d'admission des connaissances les repasse « pending ».
Imprime une ligne JSON : {"id","title","status"}.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'arsenal'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--id')
    ap.add_argument('--remove', action='store_true')
    args = ap.parse_args()
    data = json.loads((Path(__file__).with_name('arsenal_docs.json')).read_text(encoding='utf-8'))['docs']
    url = dotenv_values(ROOT / '.env').get('DATABASE_URL', '')
    if not url.startswith(('postgres://', 'postgresql://')):
        raise SystemExit('DATABASE_URL PostgreSQL requis')
    with psycopg.connect(url, sslmode='require', connect_timeout=10) as conn:
        if args.remove:
            n = conn.execute('delete from public.documents where source = %s', (SOURCE,)).rowcount
            print(json.dumps({'removed': n})); return
        doc = data.get(args.id)
        if not doc:
            raise SystemExit(f'id inconnu : {args.id}')
        stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        content = f"{doc['content']}\n\n[arsenal {stamp}]"
        row = conn.execute('update public.documents set content = %s where source = %s and title = %s returning id, review_status',
                           (content, SOURCE, doc['title'])).fetchone()
        if row is None:
            row = conn.execute("insert into public.documents (title, doc_type, source, content) values (%s,'guide',%s,%s) returning id, review_status",
                               (doc['title'], SOURCE, content)).fetchone()
        print(json.dumps({'id': str(row[0]), 'title': doc['title'], 'status': row[1]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
