# Rapport du banc de scénarios réels — 11/10/2026 06:10

Services réels : passerelle 8002 (DevBot, OpenAI), backend de défense 8000 (enquêteur OpenAI), Supabase. Généré par `scripts/castle/run_scenarios.py`.

**15 vérification(s) sur 15 réussie(s)**.

| Scénario | Résultat | Durée |
|---|---|---|
| H — Approbation, enquête < 85 % → 2e vérification non positive → confirmation → retrait | OK | 12.2 s |
| I — Approbation contre une enquête ≥ 85 % → 2e vérification + confirmation d’office → maintenu | OK | 9.0 s |

## H — Approbation, enquête < 85 % → 2e vérification non positive → confirmation → retrait : OK (12.2 s)

| Vérification | Résultat | Détail |
|---|---|---|
| cas réel sous le seuil de 85 % | OK | revue 292123ed-eb36-4c47-be59-b4dd321f1993 sans enquête initiale (demandée avant la règle « packages ») : comptée comme 0 % |
| approbation humaine enregistrée | OK | état failed |
| les agents lancent une deuxième vérification | OK | CV-0010 : statut attente_confirmation, verdict douteux (IA : douteux) |
| faits indépendants collectés (registre + OSV) | OK | F1! Contrôle des packages — typosquat : Nom très proche du packa · F2! Contrôle des packages — package_not_found : Package introuva · F3! PyPI : le package « reqeusts » n'existe pas. · F4 OSV : aucune vulnérabilité connue. · F5! Passerelle : l'installation approuvée a échoué (aucune archi |
| verdict non positif → confirmation humaine demandée | OK | Vous avez autorisé pypi:reqeusts alors que la deuxième vérification n'est pas positive (verdict : douteux). Voulez-vous toujours l'ajouter ? |
| un autre analyste ne peut pas répondre | OK | Seul l'analyste qui a approuvé le package peut confirmer ou annuler son ajout |
| l’analyste d’origine refuse → retrait exécuté par la passerelle | OK | statut retire : {"review_id":"292123ed-eb36-4c47-be59-b4dd321f1993","state":"rejected","package":"pypi:reqeusts","removed_at":"2026-10-1 |
| revue passée à « refusé » dans Supabase | OK | état rejected, retrait par banc-chateau |
| retrait tracé (package_review / remove) | OK | review:pending → approve:success → install:error → remove:success |
| plus rien dans l’inventaire des dépendances | OK | 0 ligne(s) |

**Contre-vérification CV-0010** — verdict douteux (IA : douteux), statut retire : « reqeusts » ressemble à un nom de package erroné. L’installation approuvée a échoué ; aucune archive n’a été installée.

- F1 (critique) [controle_packages] Contrôle des packages — typosquat : Nom très proche du package répandu « requests ».
- F2 (critique) [controle_packages] Contrôle des packages — package_not_found : Package introuvable sur le registre : nom probablement halluciné.
- F3 (critique) [registre] PyPI : le package « reqeusts » n'existe pas.
- F4 [osv] OSV : aucune vulnérabilité connue.
- F5 (critique) [passerelle] Passerelle : l'installation approuvée a échoué (aucune archive installable).

## I — Approbation contre une enquête ≥ 85 % → 2e vérification + confirmation d’office → maintenu : OK (9.0 s)

| Vérification | Résultat | Détail |
|---|---|---|
| les agents étaient sûrs que le package est suspect | OK | INC-0062 « Instruction suspecte dans un guide PDF interne », certitude 100 %, revue d5dbf21e-e4fc-4053-93c7-fef4e94e3762 |
| deuxième vérification indépendante faite quand même | OK | verdict douteux |
| confirmation demandée d’office (l’humain est passé outre) | OK | la deuxième vérification n'est pas positive (verdict : douteux) ; les agents étaient sûrs à 100 % que ce package est suspect (« Instruction suspecte dans un guide PDF interne ») |
| l’analyste d’origine maintient son choix | OK | statut maintenu |
| rien n’est retiré | OK | état de la revue : failed |

**Contre-vérification CV-0011** — verdict douteux (IA : douteux), statut maintenu : Le package demandé est introuvable et l’installation approuvée a échoué. Aucun package n’a été installé, mais la demande ne peut pas être considérée comme sûre.

- F1 (critique) [controle_packages] Contrôle des packages — package_not_found : Package introuvable sur le registre : nom probablement halluciné.
- F2 (critique) [registre] PyPI : le package « pdfreport-turbo » n'existe pas.
- F3 [osv] OSV : aucune vulnérabilité connue.
- F4 (critique) [passerelle] Passerelle : l'installation approuvée a échoué (aucune archive installable).
