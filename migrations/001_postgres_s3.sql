CREATE TABLE IF NOT EXISTS target_results (
    target_key VARCHAR(512) PRIMARY KEY,
    display_name VARCHAR(512) NOT NULL,
    payload JSONB NOT NULL,
    object_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_target_results_display_name
    ON target_results (display_name);

CREATE TABLE IF NOT EXISTS lightcurve_datasets (
    dataset_key VARCHAR(64) PRIMARY KEY,
    target_name VARCHAR(512) NOT NULL,
    download_dir TEXT NOT NULL UNIQUE,
    object_prefix TEXT NOT NULL,
    manifest JSONB NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lightcurve_datasets_target_name
    ON lightcurve_datasets (target_name);

CREATE TABLE IF NOT EXISTS catalog_entries (
    entry_id VARCHAR(512) PRIMARY KEY,
    entry_type VARCHAR(64) NOT NULL,
    display_name VARCHAR(512) NOT NULL,
    entry JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_catalog_entries_entry_type
    ON catalog_entries (entry_type);
CREATE INDEX IF NOT EXISTS ix_catalog_entries_display_name
    ON catalog_entries (display_name);
