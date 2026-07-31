#!/usr/bin/env python3
"""Copy existing filesystem data into PostgreSQL and S3/MinIO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.catalog_service import _rebuild_catalog  # noqa: E402
from backend.app.services.lightcurve_cache_service import (  # noqa: E402
    iter_dataset_dirs,
    read_json,
    stable_hash,
    validate_dataset_dir,
)
from backend.app.services.persistence_service import persistence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy local results/ and data/lightcurves/ into PostgreSQL + S3"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Only report what would be copied"
    )
    args = parser.parse_args()

    if not persistence.enabled:
        parser.error(
            "Set PERSISTENCE_BACKEND=postgres-s3 plus DATABASE_URL and S3 settings"
        )
    persistence.initialize()

    target_count = 0
    skipped_targets = 0
    for path in sorted((PROJECT_ROOT / "results").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped_targets += 1
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("target"), dict):
            skipped_targets += 1
            continue
        target = (
            payload["target"].get("query_target")
            or payload["target"].get("resolved_target")
            or path.stem
        )
        if not args.dry_run:
            persistence.save_target(str(target), payload)
        target_count += 1

    dataset_count = 0
    skipped_datasets = 0
    for dataset_dir in sorted(iter_dataset_dirs()):
        valid, _, manifest = validate_dataset_dir(dataset_dir)
        if not valid or not isinstance(manifest, dict):
            skipped_datasets += 1
            continue
        manifest = dict(manifest)
        if not manifest.get("dataset_key"):
            selected = read_json(dataset_dir / "selected_products.json", [])
            product_uris = sorted(
                {
                    str(item.get("product_uri") or item.get("dataURI"))
                    for item in selected
                    if isinstance(item, dict)
                    and (item.get("product_uri") or item.get("dataURI"))
                }
            )
            identity = product_uris or [
                str(dataset_dir.relative_to(PROJECT_ROOT))
            ]
            manifest["dataset_key"] = stable_hash(identity)
        manifest.setdefault(
            "download_dir", str(dataset_dir.relative_to(PROJECT_ROOT))
        )
        if not args.dry_run:
            persistence.save_dataset(dataset_dir, manifest)
        dataset_count += 1

    if not args.dry_run:
        _rebuild_catalog()
    print(
        json.dumps(
            {
                "dry_run": args.dry_run,
                "targets_copied": target_count,
                "targets_skipped": skipped_targets,
                "datasets_copied": dataset_count,
                "datasets_skipped": skipped_datasets,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
