-- Admission des packages : sécurité au niveau de la base pour toute ligne insérée dans package_reviews,
-- y compris une insertion directe qui n'est pas passée par l'analyse de la passerelle.
--
-- Pourquoi : la couche de leurres et le contrôle des packages sont du code de la passerelle ; une insertion
-- directe dans package_reviews les contournait et n'enclenchait aucune sécurité. Ce déclencheur impose, côté
-- base :
--   1. le refus par défaut : un enregistrement qui n'a pas été analysé par la passerelle (ni trace_id, ni
--      contrôles) ne peut pas démarrer dans un état de confiance ; il repasse en revue analyste ;
--   2. l'application des règles apprises : si le package figure sur la liste de blocage active
--      (package_rules, kind = 'known_malicious'), il est bloqué et son risque passé à « critical ».
-- Une revue légitime venant de la passerelle (trace_id renseigné et checks non vides) n'est pas modifiée,
-- hormis le blocage par règle apprise, qui est justement l'effet recherché.

create or replace function trace.queue_package_review() returns trigger
language plpgsql
as $$
declare bloque boolean;
begin
  -- 1. Refus par défaut pour une insertion hors passerelle (analyse non effectuée).
  if new.trace_id is null or new.checks = '{}'::jsonb then
    if coalesce(new.state, 'proposed') in ('proposed', 'approved', 'executed') then
      new.state := 'pending_approval';
    end if;
    new.recommendation := coalesce(
      new.recommendation,
      'Inséré hors passerelle : analyse non effectuée, revue analyste requise avant toute exécution.');
  end if;

  -- 2. Règles apprises : liste de blocage active (boucle d'apprentissage).
  select exists (
    select 1 from public.package_rules
    where status = 'active'
      and kind = 'known_malicious'
      and lower(value->>'name') = lower(new.package_name)
      and (value->>'ecosystem' is null
           or lower(value->>'ecosystem') = lower(coalesce(new.registry, '')))
  ) into bloque;
  if bloque then
    new.state := 'pending_approval';
    new.risk_level := 'critical';
    new.recommendation := 'Bloqué par une règle apprise (liste de blocage des packages malveillants). Revue analyste requise.';
  end if;

  return new;
end;
$$;

drop trigger if exists package_reviews_queue_review on public.package_reviews;
create trigger package_reviews_queue_review
  before insert on public.package_reviews
  for each row execute function trace.queue_package_review();
