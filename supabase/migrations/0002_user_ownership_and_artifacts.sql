-- VisionForge Phase 4: User Ownership, Furniture Layouts, Artifacts, and Storage Security
-- Reversible and idempotent migration for production Supabase deployment.

-- 1. Add user_id and calibration metadata to sessions
alter table sessions
    add column if not exists user_id uuid references auth.users(id) on delete cascade,
    add column if not exists scale_factor double precision default 1.0,
    add column if not exists metric_available boolean default false,
    add column if not exists calibrated_at timestamptz;

create index if not exists idx_sessions_user_id on sessions(user_id);

-- 2. Furniture layouts table (Phase 4 interactive furniture persistence)
create table if not exists furniture_layouts (
    id          bigint generated always as identity primary key,
    session_id  text not null references sessions(id) on delete cascade,
    user_id     uuid references auth.users(id) on delete cascade,
    layout      jsonb not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    unique (session_id)
);

create index if not exists idx_furniture_layouts_session on furniture_layouts(session_id);
create index if not exists idx_furniture_layouts_user    on furniture_layouts(user_id);

-- 3. Artifacts metadata table (referencing private Supabase Storage objects)
create table if not exists artifacts (
    id            bigint generated always as identity primary key,
    session_id    text not null references sessions(id) on delete cascade,
    user_id       uuid references auth.users(id) on delete cascade,
    artifact_type text not null, -- 'sparse_cloud', 'plane_ply', 'recording', 'room_model', 'twin'
    storage_path  text not null, -- object key in visionforge-artifacts bucket
    byte_size     bigint,
    content_type  text not null default 'application/octet-stream',
    created_at    timestamptz not null default now(),
    unique (session_id, artifact_type)
);

create index if not exists idx_artifacts_session on artifacts(session_id);
create index if not exists idx_artifacts_user    on artifacts(user_id);

-- 4. Enable Row Level Security (RLS) on all user-accessible tables
alter table sessions enable row level security;
alter table room_models enable row level security;
alter table scene_graphs enable row level security;
alter table twins enable row level security;
alter table measurements enable row level security;
alter table experiment_results enable row level security;
alter table processing_status enable row level security;
alter table furniture_layouts enable row level security;
alter table artifacts enable row level security;

-- 5. RLS Policies: Sessions
drop policy if exists "Users can view own or unassigned sessions" on sessions;
create policy "Users can view own or unassigned sessions" on sessions
    for select using (auth.uid() = user_id or user_id is null);

drop policy if exists "Users can insert own sessions" on sessions;
create policy "Users can insert own sessions" on sessions
    for insert with check (auth.uid() = user_id or user_id is null);

drop policy if exists "Users can update own sessions" on sessions;
create policy "Users can update own sessions" on sessions
    for update using (auth.uid() = user_id or user_id is null);

drop policy if exists "Users can delete own sessions" on sessions;
create policy "Users can delete own sessions" on sessions
    for delete using (auth.uid() = user_id or user_id is null);

-- 6. Helper function for child table RLS (checks session ownership)
create or replace function public.is_session_accessible(p_session_id text)
returns boolean
language sql
stable
security definer
as $$
    select exists (
        select 1 from public.sessions
        where id = p_session_id
          and (user_id = auth.uid() or user_id is null)
    );
$$;

-- 7. RLS Policies: Child tables (access tied to session accessibility)
-- room_models
drop policy if exists "Access room_models via session" on room_models;
create policy "Access room_models via session" on room_models
    for all using (public.is_session_accessible(session_id));

-- scene_graphs
drop policy if exists "Access scene_graphs via session" on scene_graphs;
create policy "Access scene_graphs via session" on scene_graphs
    for all using (public.is_session_accessible(session_id));

-- twins
drop policy if exists "Access twins via session" on twins;
create policy "Access twins via session" on twins
    for all using (public.is_session_accessible(session_id));

-- measurements
drop policy if exists "Access measurements via session" on measurements;
create policy "Access measurements via session" on measurements
    for all using (public.is_session_accessible(session_id));

-- experiment_results
drop policy if exists "Access experiment_results via session" on experiment_results;
create policy "Access experiment_results via session" on experiment_results
    for all using (public.is_session_accessible(session_id));

-- processing_status
drop policy if exists "Access processing_status via session" on processing_status;
create policy "Access processing_status via session" on processing_status
    for all using (public.is_session_accessible(session_id));

-- furniture_layouts
drop policy if exists "Access furniture_layouts via session" on furniture_layouts;
create policy "Access furniture_layouts via session" on furniture_layouts
    for all using (public.is_session_accessible(session_id));

-- artifacts
drop policy if exists "Access artifacts via session" on artifacts;
create policy "Access artifacts via session" on artifacts
    for all using (public.is_session_accessible(session_id));

-- 8. Supabase Storage: visionforge-artifacts bucket
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'visionforge-artifacts',
    'visionforge-artifacts',
    false, -- private bucket
    524288000, -- 500 MB limit
    null -- all mime types allowed (ply, json, jpg, mp4)
) on conflict (id) do update set
    public = false,
    file_size_limit = 524288000;

-- Storage object policies
drop policy if exists "Authenticated users can read visionforge artifacts" on storage.objects;
create policy "Authenticated users can read visionforge artifacts" on storage.objects
    for select using (
        bucket_id = 'visionforge-artifacts'
        and (auth.role() = 'authenticated' or auth.role() = 'service_role')
    );

drop policy if exists "Authenticated users can upload visionforge artifacts" on storage.objects;
create policy "Authenticated users can upload visionforge artifacts" on storage.objects
    for insert with check (
        bucket_id = 'visionforge-artifacts'
        and (auth.role() = 'authenticated' or auth.role() = 'service_role')
    );

drop policy if exists "Authenticated users can update visionforge artifacts" on storage.objects;
create policy "Authenticated users can update visionforge artifacts" on storage.objects
    for update using (
        bucket_id = 'visionforge-artifacts'
        and (auth.role() = 'authenticated' or auth.role() = 'service_role')
    );

drop policy if exists "Authenticated users can delete visionforge artifacts" on storage.objects;
create policy "Authenticated users can delete visionforge artifacts" on storage.objects
    for delete using (
        bucket_id = 'visionforge-artifacts'
        and (auth.role() = 'authenticated' or auth.role() = 'service_role')
    );
