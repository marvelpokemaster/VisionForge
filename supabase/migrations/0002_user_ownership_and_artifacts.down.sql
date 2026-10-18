-- Rollback migration for 0002_user_ownership_and_artifacts.sql

-- Drop storage policies and bucket
drop policy if exists "Authenticated users can delete visionforge artifacts" on storage.objects;
drop policy if exists "Authenticated users can update visionforge artifacts" on storage.objects;
drop policy if exists "Authenticated users can upload visionforge artifacts" on storage.objects;
drop policy if exists "Authenticated users can read visionforge artifacts" on storage.objects;
delete from storage.buckets where id = 'visionforge-artifacts';

-- Drop child table RLS policies
drop policy if exists "Access artifacts via session" on artifacts;
drop policy if exists "Access furniture_layouts via session" on furniture_layouts;
drop policy if exists "Access processing_status via session" on processing_status;
drop policy if exists "Access experiment_results via session" on experiment_results;
drop policy if exists "Access measurements via session" on measurements;
drop policy if exists "Access twins via session" on twins;
drop policy if exists "Access scene_graphs via session" on scene_graphs;
drop policy if exists "Access room_models via session" on room_models;

-- Drop session RLS policies
drop policy if exists "Users can delete own sessions" on sessions;
drop policy if exists "Users can update own sessions" on sessions;
drop policy if exists "Users can insert own sessions" on sessions;
drop policy if exists "Users can view own or unassigned sessions" on sessions;

-- Drop function
drop function if exists public.is_session_accessible(text);

-- Drop tables
drop table if exists artifacts;
drop table if exists furniture_layouts;

-- Drop columns from sessions
alter table sessions
    drop column if exists calibrated_at,
    drop column if exists metric_available,
    drop column if exists scale_factor,
    drop column if exists user_id;
