# Backend intégré TRACE

Deux applications complémentaires sont conservées :

- **Défense** : `main:app`, port 8000 ; incidents et décisions humaines. [Guide](README-defense.md).
- **Passerelle** : `app.main:app`, port 8002 ; traçage, coffre, leurres, contrôle des packages et environnement de démonstration. [Guide](README-gateway.md).
- **RAG simple** : `victim_agent.app:app`, port 8001 ; assistant en lecture seule affiché dans le front.

Depuis la racine : `python -m pip install -r backend/requirements.txt` dans le venv.
La passerelle exige une connexion PostgreSQL dans `DATABASE_URL`, ainsi que les tables et rôles de la migration Supabase. Le RAG et l’interface utilisent l’API HTTPS `SUPABASE_URL`.
Ne pas confondre ces deux adresses. Les secrets restent dans les fichiers `.env` ignorés.

La défense utilise désormais aussi PostgreSQL : incidents et pauses dans le schéma privé `trace` lorsque `DATABASE_URL` est défini. Sans cette variable, SQLite reste disponible pour les tests locaux.
