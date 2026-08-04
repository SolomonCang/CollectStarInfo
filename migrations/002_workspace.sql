-- Shared scientific workspace, local accounts, and private LLM data.
-- The application creates this schema automatically; this file is provided
-- for PostgreSQL deployments where a DBA owns schema changes.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(128) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role VARCHAR(16) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_hash VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    csrf_token VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_expires_at ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS workspace_targets (
    target_id VARCHAR(36) PRIMARY KEY,
    target_key VARCHAR(512) NOT NULL UNIQUE,
    display_name VARCHAR(512) NOT NULL,
    target_type VARCHAR(128),
    ra_deg DOUBLE PRECISION,
    dec_deg DOUBLE PRECISION,
    latest_snapshot_id VARCHAR(36),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_workspace_targets_display_name ON workspace_targets(display_name);

CREATE TABLE IF NOT EXISTS target_aliases (
    alias_key VARCHAR(512) PRIMARY KEY,
    target_id VARCHAR(36) NOT NULL REFERENCES workspace_targets(target_id) ON DELETE CASCADE,
    display_alias VARCHAR(512) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_target_aliases_target_id ON target_aliases(target_id);

CREATE TABLE IF NOT EXISTS target_snapshots (
    snapshot_id VARCHAR(36) PRIMARY KEY,
    target_id VARCHAR(36) NOT NULL REFERENCES workspace_targets(target_id) ON DELETE CASCADE,
    generated_at TIMESTAMPTZ NOT NULL,
    source VARCHAR(64) NOT NULL,
    artifact_path TEXT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_target_snapshots_target_id ON target_snapshots(target_id);

CREATE TABLE IF NOT EXISTS file_assets (
    asset_id VARCHAR(36) PRIMARY KEY,
    sha256 VARCHAR(64) NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    size_bytes BIGINT NOT NULL,
    media_type VARCHAR(128),
    origin VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_file_assets_sha256 ON file_assets(sha256);

CREATE TABLE IF NOT EXISTS workspace_lightcurve_datasets (
    dataset_id VARCHAR(64) PRIMARY KEY,
    target_id VARCHAR(36) REFERENCES workspace_targets(target_id) ON DELETE SET NULL,
    target_name VARCHAR(512) NOT NULL,
    download_dir TEXT NOT NULL UNIQUE,
    manifest_path TEXT NOT NULL,
    missions JSONB NOT NULL,
    product_count INTEGER NOT NULL DEFAULT 0,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_workspace_datasets_target ON workspace_lightcurve_datasets(target_name);

CREATE TABLE IF NOT EXISTS workspace_lightcurve_products (
    product_id VARCHAR(36) PRIMARY KEY,
    dataset_id VARCHAR(64) NOT NULL REFERENCES workspace_lightcurve_datasets(dataset_id) ON DELETE CASCADE,
    product_uri TEXT,
    asset_id VARCHAR(36) REFERENCES file_assets(asset_id) ON DELETE SET NULL,
    metadata JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_workspace_products_dataset ON workspace_lightcurve_products(dataset_id);

CREATE TABLE IF NOT EXISTS llm_profiles (
    profile_id VARCHAR(36) PRIMARY KEY,
    owner_user_id VARCHAR(36) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    base_url TEXT NOT NULL,
    model VARCHAR(256) NOT NULL,
    timeout_sec INTEGER NOT NULL DEFAULT 45,
    secret_nonce BYTEA NOT NULL,
    secret_ciphertext BYTEA NOT NULL,
    secret_suffix VARCHAR(8) NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_llm_profile_owner_name UNIQUE(owner_user_id, name)
);
CREATE INDEX IF NOT EXISTS ix_llm_profiles_owner ON llm_profiles(owner_user_id);

CREATE TABLE IF NOT EXISTS llm_runs (
    run_id VARCHAR(36) PRIMARY KEY,
    owner_user_id VARCHAR(36) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    target_id VARCHAR(36) REFERENCES workspace_targets(target_id) ON DELETE SET NULL,
    target_name VARCHAR(512) NOT NULL,
    task_type VARCHAR(64) NOT NULL,
    profile_snapshot JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    artifact_path TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_llm_runs_owner ON llm_runs(owner_user_id);
CREATE INDEX IF NOT EXISTS ix_llm_runs_target ON llm_runs(target_name);
CREATE INDEX IF NOT EXISTS ix_llm_runs_task ON llm_runs(task_type);

CREATE TABLE IF NOT EXISTS migration_runs (
    migration_id VARCHAR(36) PRIMARY KEY,
    mode VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    report_path TEXT,
    summary JSONB NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

INSERT INTO schema_migrations(version, applied_at)
VALUES (2, CURRENT_TIMESTAMP)
ON CONFLICT (version) DO NOTHING;
