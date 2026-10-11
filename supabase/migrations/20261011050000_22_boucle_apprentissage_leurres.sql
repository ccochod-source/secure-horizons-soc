-- 22 — Boucle d'amélioration des leurres : verdict de l'analyste et règles versionnées.
--
-- Même cycle que les packages (migration 21) : un verdict « confirmed » propose
-- un nouveau leurre, un analyste l'applique, le semeur ne lit que les règles
-- actives. Le compteur public.ruleset_meta et le trigger sont partagés.

alter table public.alerts
  add column if not exists analyst_verdict text,
  add column if not exists analyst_verdict_by uuid references auth.users(id),
  add column if not exists analyst_verdict_at timestamptz;

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'alerts_analyst_verdict_check'
                 and conrelid = 'public.alerts'::regclass) then
    alter table public.alerts add constraint alerts_analyst_verdict_check
      check (analyst_verdict in ('confirmed', 'false_positive'));
  end if;
end $$;

create table if not exists public.decoy_rules (
  id bigserial primary key,
  kind text not null check (kind in ('new_decoy_location')),
  value jsonb not null,
  status text not null default 'proposed' check (status in ('proposed', 'active', 'rolled_back')),
  version integer,
  -- Alerte dont le verdict a produit la proposition ; la règle survit à sa purge.
  source_decision_id uuid references public.alerts(id) on delete set null,
  proposed_at timestamptz not null default now(),
  decided_by uuid references auth.users(id),
  decided_at timestamptz
);

create unique index if not exists decoy_rules_open_unique
  on public.decoy_rules (kind, value) where status in ('proposed', 'active');

drop trigger if exists decoy_rules_transition on public.decoy_rules;
create trigger decoy_rules_transition before update on public.decoy_rules
  for each row execute function public.rules_apply_transition();

alter table public.decoy_rules enable row level security;
revoke all on public.decoy_rules from public, anon, authenticated;
revoke all on sequence public.decoy_rules_id_seq from public, anon, authenticated;
grant select on public.decoy_rules to authenticated;
grant update (status, decided_by, decided_at) on public.decoy_rules to authenticated;

drop policy if exists analyst_read on public.decoy_rules;
create policy analyst_read on public.decoy_rules for select to authenticated
  using (exists (select 1 from public.analysts a where a.user_id = (select auth.uid())));
drop policy if exists analyst_decide_rule on public.decoy_rules;
create policy analyst_decide_rule on public.decoy_rules for update to authenticated
  using (exists (select 1 from public.analysts a
                 where a.user_id = (select auth.uid()) and a.can_approve_packages))
  with check (exists (select 1 from public.analysts a
                      where a.user_id = (select auth.uid()) and a.can_approve_packages));
