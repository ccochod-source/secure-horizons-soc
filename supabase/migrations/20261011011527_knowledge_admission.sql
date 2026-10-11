-- Les lignes existantes constituent la base de départ approuvée. Toute nouvelle
-- connaissance (ou modification de contenu) attend ensuite l'analyse SOC.
create schema if not exists trace;

alter table public.documents
  add column if not exists review_status text not null default 'approved',
  add column if not exists review_reason text,
  add column if not exists reviewed_at timestamptz;
alter table public.repo_files
  add column if not exists review_status text not null default 'approved',
  add column if not exists review_reason text,
  add column if not exists reviewed_at timestamptz;

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'documents_review_status_check'
                 and conrelid = 'public.documents'::regclass) then
    alter table public.documents add constraint documents_review_status_check
      check (review_status in ('pending', 'approved', 'quarantined', 'rejected'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'repo_files_review_status_check'
                 and conrelid = 'public.repo_files'::regclass) then
    alter table public.repo_files add constraint repo_files_review_status_check
      check (review_status in ('pending', 'approved', 'quarantined', 'rejected'));
  end if;
end $$;

create table if not exists trace.knowledge_review_log (
  id bigserial primary key,
  source_table text not null check (source_table in ('documents', 'repo_files')),
  source_id uuid not null,
  status text not null check (status in ('approved', 'quarantined', 'rejected')),
  reason text not null,
  reviewer text not null,
  reviewed_at timestamptz not null default now()
);
alter table trace.knowledge_review_log enable row level security;
revoke all on trace.knowledge_review_log from public, anon, authenticated;

create or replace function trace.queue_knowledge_review()
returns trigger language plpgsql security invoker as $$
declare changed boolean := false;
begin
  if tg_op = 'INSERT' then
    changed := true;
  elsif tg_table_name = 'documents' then
    changed := new.title is distinct from old.title
      or new.doc_type is distinct from old.doc_type
      or new.source is distinct from old.source
      or new.content is distinct from old.content
      or new.is_decoy is distinct from old.is_decoy;
  else
    changed := new.repository_id is distinct from old.repository_id
      or new.path is distinct from old.path
      or new.file_type is distinct from old.file_type
      or new.sensitivity is distinct from old.sensitivity
      or new.content is distinct from old.content
      or new.is_decoy is distinct from old.is_decoy;
  end if;
  if changed then
    -- Les leurres sont plantés exclusivement par le service propriétaire.
    new.review_status := case when new.is_decoy then 'approved' else 'pending' end;
    new.review_reason := null;
    new.reviewed_at := case when new.is_decoy then now() else null end;
    if tg_table_name = 'documents' and tg_op = 'UPDATE' then
      new.embedding := null;
    end if;
  end if;
  return new;
end $$;

drop trigger if exists documents_queue_review on public.documents;
create trigger documents_queue_review
before insert or update on public.documents
for each row execute function trace.queue_knowledge_review();
drop trigger if exists repo_files_queue_review on public.repo_files;
create trigger repo_files_queue_review
before insert or update on public.repo_files
for each row execute function trace.queue_knowledge_review();

create index if not exists documents_review_pending_idx
  on public.documents (created_at, id) where review_status = 'pending';
create index if not exists repo_files_review_pending_idx
  on public.repo_files (created_at, id) where review_status = 'pending';
