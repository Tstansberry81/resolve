create extension if not exists pgcrypto;

create table if not exists goals (
    id uuid primary key default gen_random_uuid(),
    owner_id text not null default 'owner',
    category text not null,
    objective text not null,
    status text not null default 'draft',
    autonomy_mode text not null default 'assist',
    success_criteria jsonb not null default '[]'::jsonb,
    constraints jsonb not null default '{}'::jsonb,
    allowed_connectors jsonb not null default '[]'::jsonb,
    max_cost_usd numeric(12, 4) not null default 5,
    max_runtime_minutes integer not null default 60,
    max_replans integer not null default 2,
    deadline timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (status in ('draft','planning','active','waiting_approval','paused','completed','failed','cancelled')),
    check (autonomy_mode in ('observe','assist','execute','autopilot'))
);

create table if not exists plans (
    id uuid primary key default gen_random_uuid(),
    goal_id uuid not null references goals(id) on delete cascade,
    version integer not null,
    status text not null default 'active',
    rationale text,
    plan_json jsonb not null,
    created_at timestamptz not null default now(),
    unique (goal_id, version)
);

create table if not exists tasks (
    id uuid primary key default gen_random_uuid(),
    goal_id uuid not null references goals(id) on delete cascade,
    plan_id uuid references plans(id) on delete set null,
    parent_task_id uuid references tasks(id) on delete set null,
    title text not null,
    kind text not null,
    status text not null default 'blocked',
    risk_class text not null default 'read',
    model_role text not null,
    connector text,
    tool text,
    input_json jsonb not null default '{}'::jsonb,
    success_criteria jsonb not null default '[]'::jsonb,
    attempt_count integer not null default 0,
    max_attempts integer not null default 3,
    priority integer not null default 100,
    scheduled_at timestamptz not null default now(),
    next_attempt_at timestamptz,
    lease_owner text,
    lease_expires_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (status in ('blocked','ready','claimed','running','verifying','waiting_approval','retry_scheduled','succeeded','failed','cancelled'))
);

create table if not exists task_dependencies (
    task_id uuid not null references tasks(id) on delete cascade,
    depends_on_task_id uuid not null references tasks(id) on delete cascade,
    primary key (task_id, depends_on_task_id),
    check (task_id <> depends_on_task_id)
);

create table if not exists runs (
    id uuid primary key default gen_random_uuid(),
    goal_id uuid not null references goals(id) on delete cascade,
    task_id uuid references tasks(id) on delete cascade,
    run_type text not null,
    status text not null,
    provider text,
    model text,
    reasoning_effort text,
    prompt_hash text,
    input_json jsonb not null default '{}'::jsonb,
    output_json jsonb,
    input_tokens bigint,
    output_tokens bigint,
    cost_usd numeric(12, 6),
    duration_ms bigint,
    trace_id text,
    error_json jsonb,
    started_at timestamptz not null default now(),
    completed_at timestamptz
);

create table if not exists approvals (
    id uuid primary key default gen_random_uuid(),
    goal_id uuid not null references goals(id) on delete cascade,
    task_id uuid references tasks(id) on delete cascade,
    status text not null default 'pending',
    action_summary text not null,
    risk_class text not null,
    request_json jsonb not null,
    preview_json jsonb,
    expires_at timestamptz,
    decided_at timestamptz,
    decision_note text,
    created_at timestamptz not null default now(),
    check (status in ('pending','approved','rejected','expired','cancelled'))
);

create table if not exists tool_calls (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references runs(id) on delete cascade,
    approval_id uuid references approvals(id) on delete set null,
    connector text not null,
    tool text not null,
    risk_class text not null,
    status text not null,
    idempotency_key text not null unique,
    request_json jsonb not null,
    response_json jsonb,
    reversible_until timestamptz,
    started_at timestamptz not null default now(),
    completed_at timestamptz
);

create table if not exists artifacts (
    id uuid primary key default gen_random_uuid(),
    goal_id uuid not null references goals(id) on delete cascade,
    task_id uuid references tasks(id) on delete set null,
    kind text not null,
    name text not null,
    uri text not null,
    content_hash text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists memories (
    id uuid primary key default gen_random_uuid(),
    owner_id text not null default 'owner',
    scope text not null,
    kind text not null,
    content text not null,
    source_uri text,
    confidence numeric(4, 3),
    valid_from timestamptz,
    valid_until timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists connector_accounts (
    id uuid primary key default gen_random_uuid(),
    owner_id text not null default 'owner',
    connector text not null,
    account_label text not null,
    status text not null default 'disconnected',
    granted_scopes jsonb not null default '[]'::jsonb,
    secret_ref text,
    metadata jsonb not null default '{}'::jsonb,
    last_healthcheck_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, connector, account_label)
);

create table if not exists schedules (
    id uuid primary key default gen_random_uuid(),
    owner_id text not null default 'owner',
    name text not null,
    cron_expression text not null,
    timezone text not null default 'America/New_York',
    goal_template jsonb not null,
    enabled boolean not null default true,
    last_fired_at timestamptz,
    next_fire_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists agent_events (
    id bigint generated always as identity primary key,
    goal_id uuid references goals(id) on delete cascade,
    task_id uuid references tasks(id) on delete cascade,
    event_type text not null,
    actor text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_goals_status on goals(status, updated_at desc);
create index if not exists idx_tasks_ready on tasks(status, scheduled_at, priority);
create index if not exists idx_tasks_lease on tasks(lease_expires_at) where status = 'claimed';
create index if not exists idx_runs_goal on runs(goal_id, started_at desc);
create index if not exists idx_approvals_pending on approvals(status, created_at) where status = 'pending';
create index if not exists idx_events_goal on agent_events(goal_id, created_at);

comment on column connector_accounts.secret_ref is
    'Reference to Render/Supabase/Vault secret storage. Never store OAuth tokens directly here.';
