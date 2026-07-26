-- Vault semantic index - turns the second brain from a filing cabinet into memory.
--
-- Run once in the Supabase SQL editor. The control plane reaches this through
-- PostgREST (same SUPABASE_URL/SUPABASE_KEY as everything else), so the search
-- has to be an RPC: PostgREST can't express a `<=>` vector ordering in a query
-- string, but it can call a function.
--
-- Model: text-embedding-3-small (1536 dims), the `embeddings` route in
-- config/model_routes.json - cheap enough ($0.02/1M tokens) that indexing the
-- whole vault costs well under a cent, which is why re-embedding only changed
-- chunks matters for latency rather than for money.

create extension if not exists vector;

create table if not exists public.vault_chunks (
    id           bigserial primary key,
    path         text        not null,
    chunk_index  int         not null,
    content      text        not null,
    -- sha256 of the chunk text: lets the indexer skip anything unchanged
    content_hash text        not null,
    embedding    vector(1536) not null,
    updated_at   timestamptz not null default now(),
    unique (path, chunk_index)
);

-- Cosine distance index. ivfflat needs ANALYZE and a populated table to be
-- effective; with a personal vault (thousands of chunks at most) a sequential
-- scan is already fast, so this is future-proofing rather than a hot path.
create index if not exists vault_chunks_embedding_idx
    on public.vault_chunks using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

create index if not exists vault_chunks_path_idx on public.vault_chunks (path);

-- Similarity search. Returns closest chunks with a 0-1 similarity score
-- (1 = identical), so the caller can drop weak matches rather than showing
-- Trav the least-bad row in an empty vault.
create or replace function public.match_vault_chunks(
    query_embedding vector(1536),
    match_count int default 8,
    min_similarity float default 0.0
)
returns table (path text, chunk_index int, content text, similarity float)
language sql stable
as $$
    select c.path,
           c.chunk_index,
           c.content,
           1 - (c.embedding <=> query_embedding) as similarity
    from public.vault_chunks c
    where 1 - (c.embedding <=> query_embedding) >= min_similarity
    order by c.embedding <=> query_embedding
    limit match_count;
$$;

-- Service-role only: the vault is Trav's private second brain.
alter table public.vault_chunks enable row level security;
