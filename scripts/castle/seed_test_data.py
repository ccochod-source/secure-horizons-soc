#!/usr/bin/env python3
"""Plante (ou retire) les données de test réelles des scénarios du château dans Supabase.

    .venv/bin/python scripts/castle/seed_test_data.py            # plante ce qui manque
    .venv/bin/python scripts/castle/seed_test_data.py --remove   # retire tout ce qui a source = 'tests-chateau'
    .venv/bin/python scripts/castle/seed_test_data.py --redeposit  # redépose le guide piégé (repasse « pending »)

Les documents sont marqués source = 'tests-chateau' : rien d'autre dans la base n'est touché.
Redémarrer la passerelle ensuite : elle calcule l'embedding des nouveaux documents au démarrage.
"""
import argparse
import json
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'tests-chateau'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--remove', action='store_true')
    ap.add_argument('--redeposit', action='store_true', help='nouvelle révision du guide : le trigger le remet en attente d’admission')
    args = ap.parse_args()
    data = json.loads((Path(__file__).with_name('test_data.json')).read_text(encoding='utf-8'))
    url = dotenv_values(ROOT / '.env').get('DATABASE_URL', '')
    if not url.startswith(('postgres://', 'postgresql://')):
        raise SystemExit('DATABASE_URL PostgreSQL requis dans .env')
    with psycopg.connect(url, sslmode='require', connect_timeout=10) as conn:
        if args.redeposit:
            from datetime import datetime, timezone
            doc = data['documents'][0]
            row = conn.execute(
                'update public.documents set content = %s where source = %s and title = %s returning id, title, review_status',
                (f"{doc['content']}\n\nRévision du {datetime.now(timezone.utc).isoformat(timespec='seconds')}.", SOURCE, doc['title'])).fetchone()
            print(json.dumps({'id': str(row[0]), 'title': row[1], 'status': row[2]} if row else {'error': 'guide introuvable'}, ensure_ascii=False))
            return
        if args.remove:
            n = conn.execute('delete from public.documents where source = %s', (SOURCE,)).rowcount
            print(f'{n} document(s) de test retiré(s).')
            return
        for doc in data['documents']:
            created = conn.execute(
                'insert into public.documents (title, doc_type, source, content) select %s, %s, %s, %s '
                'where not exists (select 1 from public.documents where title = %s) returning id',
                (doc['title'], doc['doc_type'], SOURCE, doc['content'], doc['title'])).fetchone()
            print(f"« {doc['title']} » : {'planté' if created else 'déjà en base'}")
    print('Redémarrer la passerelle pour calculer les embeddings (scripts/castle/run_gateway.sh).')


if __name__ == '__main__':
    main()
