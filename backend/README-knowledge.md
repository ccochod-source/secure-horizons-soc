# Admission des connaissances Supabase

La migration `supabase/migrations/20261011011527_knowledge_admission.sql` conserve les
documents et fichiers déjà présents comme base initiale approuvée. Chaque nouvel
enregistrement ou modification de contenu dans `public.documents` et
`public.repo_files` passe ensuite à `review_status = 'pending'` dans la même
transaction. Une modification d'un document efface également son ancien
embedding. Les leurres plantés par le service propriétaire sont exemptés.

La défense sur le port 8000 examine les lignes en attente toutes les deux
secondes. Les règles repèrent immédiatement les secrets et instructions
suspectes ; les autres contenus sont classés avec le modèle OpenAI de la
défense. Un résultat incertain ou une panne laisse le contenu en attente.
Un contenu suspect va en quarantaine. La décision et son motif sont conservés
dans `trace.knowledge_review_log`. Un analyste peut approuver ou refuser depuis
la section « Connaissances à valider » de l'interface.

L'assistant RAG et les outils de l'agent de démonstration lisent uniquement
les lignes `approved`. Ce filtre est appliqué aux recherches textuelles et
vectorielles, aux fichiers et au calcul des embeddings. Le contrôle des
packages reste un circuit distinct ; les événements d'action continuent à
alimenter la pipeline comportementale d'Alex.

Pour montrer le parcours, ouvrir « Scénario d'attaque » et cliquer sur
« Ajouter la procédure piégée ». Le bouton insère une procédure fictive sans
véritable secret. La défense la met en quarantaine ; elle apparaît ensuite
dans « Connaissances à valider » pour une décision humaine.

Ce contrôle porte sur les connaissances (`documents`, `repo_files`), pas sur
toutes les tables Supabase. Il ne garantit pas la détection de toute attaque :
les règles et l'analyse IA peuvent produire des faux positifs ou manquer une
manipulation subtile. La quarantaine et la décision humaine restent donc
visibles, et les échecs d'analyse n'approuvent jamais automatiquement une ligne.
