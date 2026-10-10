-- 20 — Passerelle de traçage et coffre de pseudonymisation : rôles et droits.
--
-- Avant cette migration, public.vault_reveal (qui rend une valeur en clair) et
-- public.pseudonymize_value étaient exécutables par anon et authenticated,
-- donc appelables avec la clé publique via /rest/v1/rpc. On ferme cet accès et
-- on crée deux identités dédiées :
--   soc_gateway   : écrit les traces et crée des jetons, ne peut rien révéler ;
--   soc_confineur : seul rôle applicatif autorisé à retrouver une valeur réelle.
-- Le backend se connecte avec DATABASE_URL puis fait SET LOCAL ROLE dans
-- chaque transaction (compatible avec le pooler en mode transaction).

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'soc_gateway') then
    create role soc_gateway nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'soc_confineur') then
    create role soc_confineur nologin;
  end if;
end $$;

grant soc_gateway   to postgres with set true, inherit false;
grant soc_confineur to postgres with set true, inherit false;

-- Fonctions du coffre : plus aucun accès depuis les clés du navigateur.
revoke execute on function public.pseudonymize_value(text, text) from public, anon, authenticated;
revoke execute on function public.vault_reveal(text)             from public, anon, authenticated;

-- Le journal des révélations enregistre le rôle appelant (SET ROLE) plutôt
-- que session_user, qui vaut toujours « postgres » côté backend.
create or replace function public.vault_reveal(p_token text)
 returns text
 language plpgsql
 security definer
 set search_path to ''
as $function$
declare v_value text;
begin
  insert into public.token_vault_log(token, revealed_by)
    values (p_token, coalesce(nullif(current_setting('role', true), 'none'), session_user));
  select ds.decrypted_secret into v_value from public.token_vault tv
    join vault.decrypted_secrets ds on ds.id = tv.vault_secret_id where tv.token = p_token;
  return v_value;
end $function$;

-- Variante par lot : un seul aller-retour par événement tracé.
create or replace function public.pseudonymize_values(p_prefixes text[], p_values text[])
 returns text[]
 language plpgsql
 set search_path to ''
as $function$
declare v_out text[] := '{}'; i int;
begin
  if coalesce(array_length(p_prefixes, 1), 0) <> coalesce(array_length(p_values, 1), 0) then
    raise exception 'préfixes et valeurs de longueurs différentes';
  end if;
  for i in 1 .. coalesce(array_length(p_values, 1), 0) loop
    v_out := v_out || public.pseudonymize_value(p_prefixes[i], p_values[i]);
  end loop;
  return v_out;
end $function$;

revoke execute on function public.pseudonymize_values(text[], text[]) from public, anon, authenticated;

-- public.secrets réserve déjà les jetons …_001 à …_005 : on démarre la séquence
-- au-delà pour qu'un jeton généré ne puisse jamais porter le même nom.
select setval('public.token_seq', greatest((select last_value from public.token_seq), 100));

-- Passerelle : traces en ajout seul, création de jetons, annuaire des noms.
grant select, insert on public.events to soc_gateway;
grant execute on function public.pseudonymize_value(text, text)      to soc_gateway;
grant execute on function public.pseudonymize_values(text[], text[]) to soc_gateway;
grant execute on function public.provenance_graph(uuid)              to soc_gateway;
grant select (full_name) on public.employees to soc_gateway;

drop policy if exists gateway_insert on public.events;
create policy gateway_insert on public.events for insert to soc_gateway with check (true);
drop policy if exists gateway_read on public.events;
create policy gateway_read on public.events for select to soc_gateway using (true);
drop policy if exists gateway_directory on public.employees;
create policy gateway_directory on public.employees for select to soc_gateway using (true);

-- Confineur : la révélation, et rien d'autre dans ce périmètre.
grant execute on function public.vault_reveal(text) to soc_confineur;
