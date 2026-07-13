-- SimpleFIN Bridge access-URL storage for the finance page.
-- Run once in the Supabase SQL editor (project jtcmlbwejpohwuwvnqnk).
-- The Access URL contains basic-auth credentials — treat the row as a secret.
-- (Alternative: skip this table and set SIMPLEFIN_ACCESS_URL as an env var.)

create table if not exists public.simplefin (
    id          uuid primary key default gen_random_uuid(),
    access_url  text not null,
    created_at  timestamptz not null default now()
);

-- Service-role only; no public/anon access to these credentials.
alter table public.simplefin enable row level security;
