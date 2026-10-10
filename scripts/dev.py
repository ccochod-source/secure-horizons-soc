"""Lancer les services locaux du même checkout, sans installation ni données de démo."""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from victim_agent.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gateway', action='store_true', help='Ajouter la passerelle PostgreSQL sur 8002.')
    args = parser.parse_args()
    config = {**{k: v for k, v in dotenv_values(ROOT / '.env.victim').items() if v},
              **{k: v for k, v in dotenv_values(ROOT / '.env').items() if v},
              **{k: v for k, v in os.environ.items() if v}}
    settings = Settings.from_env()
    if not config.get('PASSERELLE_TOKEN') or not config.get('ANALYSTE_TOKEN'):
        raise SystemExit('Les jetons PASSERELLE_TOKEN et ANALYSTE_TOKEN sont requis dans .env.victim.')
    services = [
        ('Défense', 8000, [sys.executable, '-m', 'victim_agent.launch_alex']),
        ('RAG', 8001, [sys.executable, '-m', 'uvicorn', 'victim_agent.app:app', '--host', '127.0.0.1', '--port', '8001']),
        ('Interface', 3100, ['npm', 'run', 'dev']),
    ]
    if args.gateway:
        if not config.get('DATABASE_URL', '').startswith(('postgres://', 'postgresql://')):
            raise SystemExit('DATABASE_URL PostgreSQL requis pour --gateway.')
        services.insert(2, ('Passerelle', 8002, [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8002']))
    for name, port, _ in services:
        with socket.socket() as probe:
            probe.settimeout(0.3)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise SystemExit(f'{name} : port {port} déjà occupé. Aucun processus existant n’a été arrêté.')
    # Validate the shared database before starting any children. A failed
    # connection must not leave half of the stack running or expose the DSN.
    if config.get('DATABASE_URL'):
        import psycopg
        try:
            with psycopg.connect(config['DATABASE_URL'], connect_timeout=5, sslmode='require') as conn:
                conn.execute('select 1')
        except psycopg.Error:
            raise SystemExit('Connexion PostgreSQL impossible : vérifier DATABASE_URL dans Supabase → Connect. Aucun service lancé.')
    config.setdefault('GATEWAY_TOKEN', settings.gateway_token)
    config.setdefault('DECOYS_SEED_ON_START', 'false')
    if args.gateway:
        config.setdefault('CONFINEMENT_URL', 'http://127.0.0.1:8002/confinement')
    children = []
    def stop(_signal=None, _frame=None):
        for _, child in children:
            if child.poll() is None:
                child.terminate()
    signal.signal(signal.SIGTERM, stop)
    try:
        for name, port, command in services:
            env = {**os.environ, **config}
            if name == 'Défense':
                env['OPENAI_API_KEY'] = config.get('OPENAI_API_KEY_ENQUETEUR') or settings.openai_key
            cwd = ROOT / 'backend' if name == 'Passerelle' else ROOT
            children.append((name, subprocess.Popen(command, cwd=cwd, env=env)))
            print(f'{name} démarré sur 127.0.0.1:{port}', flush=True)
        if not args.gateway:
            print('Passerelle packages/leurres non lancée : utiliser dev:full après vérification PostgreSQL.', flush=True)
        while all(child.poll() is None for _, child in children):
            time.sleep(0.5)
        failed = [(name, child.returncode) for name, child in children if child.poll() is not None]
        raise SystemExit(f'Service arrêté : {failed}. Consulter son message ci-dessus.')
    except KeyboardInterrupt:
        pass
    finally:
        stop()
        for _, child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    main()
