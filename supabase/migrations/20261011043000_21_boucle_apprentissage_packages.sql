-- 21 — Boucle d'amélioration du contrôle des packages : listes versionnées.
--
-- Le système propose, l'analyste applique. Une règle n'a d'effet que dans
-- l'état « active », atteint uniquement par la décision d'un analyste. Les
-- listes ne grossissent que par ajout : aucun DELETE n'est accordé, et le
-- retour en arrière passe la ligne à « rolled_back » sans la supprimer.
-- Les propositions sont écrites par le backend (compte de DATABASE_URL, hors RLS).

-- Compteur unique de version des listes, partagé par toutes les tables de règles.
create table if not exists public.ruleset_meta (
  id boolean primary key default true check (id),
  current_version integer not null default 0,
  updated_at timestamptz not null default now()
);
insert into public.ruleset_meta (id) values (true) on conflict (id) do nothing;

create table if not exists public.package_rules (
  id bigserial primary key,
  kind text not null check (kind in ('known_malicious', 'replacement_map', 'popular')),
  value jsonb not null,
  status text not null default 'proposed' check (status in ('proposed', 'active', 'rolled_back')),
  version integer,  -- version des listes à l'activation ; null tant que la règle est proposée
  -- package_reviews.id est un uuid dans ce schéma (pas de colonne review_id bigint).
  -- Si la revue d'origine est purgée (remise à zéro de la démo), la règle reste.
  source_decision_id uuid references public.package_reviews(id) on delete set null,
  proposed_at timestamptz not null default now(),
  decided_by uuid references auth.users(id),
  decided_at timestamptz
);

-- Dédoublonnage : une seule règle identique proposée ou active à la fois.
create unique index if not exists package_rules_open_unique
  on public.package_rules (kind, value) where status in ('proposed', 'active');
create index if not exists package_rules_active on public.package_rules (kind) where status = 'active';

-- Seules transitions admises : proposed → active, active → rolled_back. Chacune
-- incrémente ruleset_meta et exige l'identité de l'analyste, quel que soit le
-- chemin d'écriture (backend ou API Supabase avec le jeton de l'analyste).
create or replace function public.rules_apply_transition()
returns trigger
language plpgsql
security definer
set search_path to ''
as $function$
declare v_version integer;
begin
  -- Purge de la décision d'origine (clé étrangère « on delete set null ») : la règle reste telle quelle.
  if old.source_decision_id is not null and new.source_decision_id is null
     and (new.id, new.kind, new.value, new.status, new.proposed_at)
         is not distinct from (old.id, old.kind, old.value, old.status, old.proposed_at)
     and new.version is not distinct from old.version
     and new.decided_by is not distinct from old.decided_by
     and new.decided_at is not distinct from old.decided_at then
    return new;
  end if;
  if new.id is distinct from old.id or new.kind is distinct from old.kind
     or new.value is distinct from old.value
     or new.source_decision_id is distinct from old.source_decision_id
     or new.proposed_at is distinct from old.proposed_at then
    raise exception 'une règle ne se modifie pas : seul son statut change';
  end if;
  if not ((old.status = 'proposed' and new.status = 'active')
          or (old.status = 'active' and new.status = 'rolled_back')) then
    raise exception 'transition de règle interdite : % → %', old.status, new.status;
  end if;
  -- Avec un jeton d'analyste, l'identité vient du jeton et non de la requête.
  if auth.uid() is not null then
    new.decided_by := auth.uid();
  end if;
  if new.decided_by is null then
    raise exception 'une règle ne change de statut que sur décision d''un analyste identifié';
  end if;
  update public.ruleset_meta set current_version = current_version + 1, updated_at = now()
    where id returning current_version into v_version;
  new.decided_at := now();
  if new.status = 'active' then
    new.version := v_version;
  else
    new.version := old.version;  -- on garde la version d'activation pour l'historique
  end if;
  return new;
end $function$;

revoke execute on function public.rules_apply_transition() from public, anon, authenticated;

drop trigger if exists package_rules_transition on public.package_rules;
create trigger package_rules_transition before update on public.package_rules
  for each row execute function public.rules_apply_transition();

alter table public.package_rules enable row level security;
alter table public.ruleset_meta enable row level security;

revoke all on public.package_rules from public, anon, authenticated;
revoke all on public.ruleset_meta from public, anon, authenticated;
revoke all on sequence public.package_rules_id_seq from public, anon, authenticated;

-- L'analyste lit tout et ne peut toucher qu'au statut et aux champs de décision.
grant select on public.package_rules, public.ruleset_meta to authenticated;
grant update (status, decided_by, decided_at) on public.package_rules to authenticated;

drop policy if exists analyst_read on public.package_rules;
create policy analyst_read on public.package_rules for select to authenticated
  using (exists (select 1 from public.analysts a where a.user_id = (select auth.uid())));
drop policy if exists analyst_decide_rule on public.package_rules;
create policy analyst_decide_rule on public.package_rules for update to authenticated
  using (exists (select 1 from public.analysts a
                 where a.user_id = (select auth.uid()) and a.can_approve_packages))
  with check (exists (select 1 from public.analysts a
                      where a.user_id = (select auth.uid()) and a.can_approve_packages));
drop policy if exists analyst_read on public.ruleset_meta;
create policy analyst_read on public.ruleset_meta for select to authenticated
  using (exists (select 1 from public.analysts a where a.user_id = (select auth.uid())));

-- Version des listes en vigueur pendant un run, pour comparer avant / après.
-- La table des runs de ce schéma s'appelle demo_runs ; benchmark_runs est
-- complétée aussi si elle existe.
alter table if exists public.demo_runs add column if not exists ruleset_version integer;
alter table if exists public.benchmark_runs add column if not exists ruleset_version integer;
