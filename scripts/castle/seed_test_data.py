#!/usr/bin/env python3
"""Plante (ou retire) les données de test réelles des scénarios du château dans Supabase.

    .venv/bin/python scripts/castle/seed_test_data.py            # plante ce qui manque
    .venv/bin/python scripts/castle/seed_test_data.py --remove   # retire tout ce qui a source = 'tests-chateau'

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
    args = ap.parse_args()
    data = json.loads((Path(__file__).with_name('test_data.json')).read_text(encoding='utf-8'))
    url = dotenv_values(ROOT / '.env').get('DATABASE_URL', '')
    if not url.startswith(('postgres://', 'postgresql://')):
        raise SystemExit('DATABASE_URL PostgreSQL requis dans .env')
    with psycopg.connect(url, sslmode='require', connect_timeout=10) as conn:
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
