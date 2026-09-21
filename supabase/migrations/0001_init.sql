-- VisionForge persistence schema (Task G).
--
-- Stores project-level digital twin data only: sessions, room models, scene
-- graphs, twins, measurements, experiment results, and per-stage processing
-- status. Never stores frames, PLY point cloud data, or per-frame camera
-- poses -- those stay on local disk under outputs/<run>/ and are referenced
-- by path (see room_model.json's ply_path / twin.json's sparse_cloud_path),
-- not duplicated into the database.

create table if not exists sessions (
    id          text primary key,
    created_at  timestamptz not null default now(),
    input_type  text not null default 'unknown',
    video_name  text,
    status      text
);

create table if not exists room_models (
    id          bigint generated always as identity primary key,
    session_id  text not null references sessions(id) on delete cascade,
    version     int not null,
    payload     jsonb not null,
    created_at  timestamptz not null default now(),
    unique (session_id, version)
);

create table if not exists scene_graphs (
    id          bigint generated always as identity primary key,
    session_id  text not null references sessions(id) on delete cascade,
    version     int not null,
    payload     jsonb not null,
    created_at  timestamptz not null default now(),
    unique (session_id, version)
);

create table if not exists twins (
    id          bigint generated always as identity primary key,
    session_id  text not null references sessions(id) on delete cascade,
    version     int not null,
    payload     jsonb not null,
    created_at  timestamptz not null default now(),
    unique (session_id, version)
);

-- One row per measurement (length/width/height/floor_area/...), not one
-- jsonb blob, so individual fields are directly queryable/filterable.
create table if not exists measurements (
    id          bigint generated always as identity primary key,
    session_id  text not null references sessions(id) on delete cascade,
    name        text not null,
    value       double precision,
    units       text,
    metric      boolean,
    method      text,
    created_at  timestamptz not null default now()
);

create table if not exists experiment_results (
    id          bigint generated always as identity primary key,
    session_id  text not null references sessions(id) on delete cascade,
    key         text not null,
    json        jsonb not null,
    created_at  timestamptz not null default now()
);

create table if not exists processing_status (
    id          bigint generated always as identity primary key,
    session_id  text not null references sessions(id) on delete cascade,
    stage       text not null,
    status      text not null,
    updated_at  timestamptz not null default now()
);

create index if not exists idx_room_models_session       on room_models(session_id);
create index if not exists idx_scene_graphs_session       on scene_graphs(session_id);
create index if not exists idx_twins_session               on twins(session_id);
create index if not exists idx_measurements_session         on measurements(session_id);
create index if not exists idx_experiment_results_session   on experiment_results(session_id);
create index if not exists idx_processing_status_session    on processing_status(session_id);
