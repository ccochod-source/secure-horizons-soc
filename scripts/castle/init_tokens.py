#!/usr/bin/env python3
"""Crée, s'ils manquent, les jetons locaux PASSERELLE_TOKEN et ANALYSTE_TOKEN dans .env.victim (ignoré par Git).
Les valeurs ne sont pas affichées."""
import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[2] / '.env.victim'
content = path.read_text() if path.exists() else ''
present = {line.split('=', 1)[0].strip() for line in content.splitlines() if '=' in line and line.split('=', 1)[1].strip()}
added = []
for name in ['PASSERELLE_TOKEN', 'ANALYSTE_TOKEN', 'CONFINEMENT_TOKEN', 'VICTIM_GATEWAY_TOKEN']:
    if name not in present:
        content = content.rstrip() + ('\n' if content else '') + f'{name}={secrets.token_urlsafe(32)}\n'
        added.append(name)
path.write_text(content)
path.chmod(0o600)
print('Jetons créés :' if added else 'Jetons déjà présents.', ', '.join(added))
