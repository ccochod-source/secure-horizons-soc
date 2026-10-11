# Boucle d'amélioration : preuve avant / après

Mesuré le 2026-10-11T02:56:32+00:00 — registres PyPI, npm et OSV interrogés en direct ; analyste et installation simulés, rien n'est écrit en base.

| Mesure | Avant (listes v0) | Après (listes v5) |
|---|---|---|
| Packages malveillants arrêtés avant installation | 5 / 5 | 5 / 5 |
| … dont bloqués d'emblée, sans analyste | 0 / 5 | 5 / 5 |
| … dont en attente d'une décision humaine | 5 / 5 | 0 / 5 |
| Appels réseau (registres, archives) pour ces packages | 7 | 0 |
| Packages légitimes installés | 3 / 3 | 3 / 3 |
| Packages légitimes envoyés à tort en décision humaine | 0 / 3 | 0 / 3 |
| Packages légitimes bloqués par une règle apprise | 0 / 3 | 0 / 3 |

| Package | Type | Avant | Après |
|---|---|---|---|
| pypi:reqeusts | malveillant | blocked_pending_review (score 1.00 ; typosquat, package_not_found) | blocked (score 1.00 ; known_malicious) |
| pypi:pandass | malveillant | blocked_pending_review (score 1.00 ; typosquat, package_not_found) | blocked (score 1.00 ; known_malicious) |
| pypi:numpyy-fast | malveillant | blocked_pending_review (score 1.00 ; package_not_found) | blocked (score 1.00 ; known_malicious) |
| pypi:fastjsonparse-turbo | malveillant | blocked_pending_review (score 1.00 ; package_not_found) | blocked (score 1.00 ; known_malicious) |
| npm:lodahs | malveillant | blocked_pending_review (score 0.60 ; typosquat, known_vulnerability, single_release) | blocked (score 1.00 ; known_malicious) |
| pypi:requests | légitime | installed (score 0.00 ; aucun signal) | installed (score 0.00 ; aucun signal) |
| pypi:httpx | légitime | installed (score 0.00 ; aucun signal) | installed (score 0.00 ; aucun signal) |
| npm:lodash | légitime | installed (score 0.00 ; aucun signal) | installed (score 0.00 ; aucun signal) |

Règles appliquées par l'analyste entre les deux passes :

- v1 — known_malicious : {"ecosystem": "pypi", "name": "reqeusts"}
- v2 — known_malicious : {"ecosystem": "pypi", "name": "pandass"}
- v3 — known_malicious : {"ecosystem": "pypi", "name": "numpyy-fast"}
- v4 — known_malicious : {"ecosystem": "pypi", "name": "fastjsonparse-turbo"}
- v5 — known_malicious : {"ecosystem": "npm", "name": "lodahs"}
