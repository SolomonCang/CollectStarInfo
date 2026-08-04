#!/usr/bin/env python3
"""Copy legacy results and light curves into the authoritative warehouse.

The operation is resumable and never removes source files.  A manifest with
source/destination SHA-256 pairs is emitted for independent verification.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Iterator
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.workspace_service import (  # noqa: E402
    CACHE_ROOT,
    LIGHTCURVE_OBJECT_ROOT,
    MANIFEST_ROOT,
    OBJECT_ROOT,
    atomic_write_json,
    safe_slug,
    sha256_file,
    workspace,
)
from src.astro_agent.config import load_settings  # noqa: E402


LEGACY_RESULTS = PROJECT_ROOT / "results"
LEGACY_LIGHTCURVES = PROJECT_ROOT / "data" / "lightcurves"


def iter_files(root: Path) -> Iterator[Path]:
    if root.exists():
        yield from (path for path in root.rglob("*") if path.is_file())


def copy_verified(source: Path, destination: Path, report: dict[str, Any]) -> bool:
    source_hash = sha256_file(source)
    content_index: dict[str, str] = report.setdefault("_content_index", {})
    if destination.exists():
        destination_hash = sha256_file(destination)
        if destination_hash == source_hash:
            content_index.setdefault(source_hash, str(destination))
            report["skipped_identical"] += 1
            report["files"].append({"source": str(source), "destination": str(destination), "sha256": source_hash, "status": "identical"})
            return True
        report["conflicts"].append({"source": str(source), "destination": str(destination), "source_sha256": source_hash, "destination_sha256": destination_hash})
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
    canonical = Path(content_index[source_hash]) if source_hash in content_index else None
    linked = False
    if canonical is not None and canonical.is_file():
        try:
            os.link(canonical, temporary)
            linked = True
        except OSError:
            shutil.copy2(source, temporary)
    else:
        shutil.copy2(source, temporary)
    if sha256_file(temporary) != source_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum mismatch while copying {source}")
    os.replace(temporary, destination)
    report["copied_files"] += 1
    if linked:
        report["deduplicated_files"] += 1
    else:
        report["copied_bytes"] += source.stat().st_size
    content_index.setdefault(source_hash, str(destination))
    report["files"].append({"source": str(source), "destination": str(destination), "sha256": source_hash, "status": "linked" if linked else "copied"})
    return True


def target_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("target"), dict) else None


def same_target_payload(left: dict[str, Any], right: dict[str, Any]) -> bool:
    def clean(value: dict[str, Any]) -> dict[str, Any]:
        copied = json.loads(json.dumps(value, ensure_ascii=False))
        copied.pop("source", None); copied.pop("result_path", None)
        if isinstance(copied.get("target"), dict):
            copied["target"]["summary"] = None
        return copied
    return clean(left) == clean(right)


def migrate_targets(report: dict[str, Any], *, execute: bool, owner: dict[str, Any] | None) -> None:
    if not LEGACY_RESULTS.exists():
        return
    all_files = list(iter_files(LEGACY_RESULTS))
    report["result_files_seen"] = len(all_files)
    report["source_bytes"] += sum(path.stat().st_size for path in all_files)
    attached: set[Path] = set()
    for json_path in sorted(LEGACY_RESULTS.glob("*.json")):
        payload = target_payload(json_path)
        if payload is None:
            report["invalid_results"].append(str(json_path))
            continue
        target = payload["target"]
        name = str(target.get("resolved_target") or target.get("query_target") or json_path.stem)
        report["targets_seen"] += 1
        attached.add(json_path.resolve())
        related_files: list[tuple[Path, Path]] = []
        for candidate in (
            LEGACY_RESULTS / f"{json_path.stem}.md",
            LEGACY_RESULTS / f"{json_path.stem}_extrapar.md",
        ):
            if candidate.is_file():
                attached.add(candidate.resolve())
                related_files.append((candidate, Path(candidate.name)))
        asset_dir = LEGACY_RESULTS / json_path.stem
        if asset_dir.is_dir():
            for source in iter_files(asset_dir):
                attached.add(source.resolve())
                related_files.append((source, Path(asset_dir.name) / source.relative_to(asset_dir)))
        if not execute:
            continue
        existing = workspace.load_target(name)
        if existing is not None and same_target_payload(existing, payload):
            report["targets_skipped"] += 1
            artifact_path = existing["result_path"]
        else:
            artifact_path = workspace.save_target(name, payload, source="legacy-migration")
            report["targets_imported"] += 1
        artifact_dir = (PROJECT_ROOT / artifact_path).parent
        legacy_dir = artifact_dir / "legacy-assets"
        copy_verified(json_path, legacy_dir / "original" / json_path.name, report)
        for source, relative in related_files:
            copy_verified(source, legacy_dir / relative, report)
        summary = target.get("summary")
        if summary and owner is not None:
            source_key = str(json_path.relative_to(PROJECT_ROOT))
            already_imported = False
            for item in workspace.list_llm_runs(
                owner["user_id"], target_name=name, task_type="target_summary", limit=500
            ):
                detail = workspace.get_llm_run(owner["user_id"], item["id"])
                if (detail.get("request") or {}).get("source") == source_key:
                    already_imported = True
                    break
            if already_imported:
                report["legacy_summaries_skipped"] += 1
            else:
                run_id = workspace.start_llm_run(
                    owner["user_id"], name, "target_summary",
                    {"id": "legacy", "name": "Legacy DeepSeek", "provider": "deepseek", "base_url": "legacy", "model": "legacy", "timeout_sec": 45},
                    {"source": source_key},
                )
                workspace.finish_llm_run(owner["user_id"], run_id, {"summary": summary, "target": name})
                report["legacy_summaries"] += 1
    orphan_files = [path for path in all_files if path.resolve() not in attached]
    report["orphan_result_files"] = len(orphan_files)
    if execute:
        for source in orphan_files:
            copy_verified(
                source,
                OBJECT_ROOT / "legacy-results-unassigned" / source.relative_to(LEGACY_RESULTS),
                report,
            )


def rewrite_manifest_paths(manifest: dict[str, Any], old_root: Path, new_root: Path) -> dict[str, Any]:
    rewritten = json.loads(json.dumps(manifest, ensure_ascii=False))
    rewritten["download_dir"] = str(new_root.relative_to(PROJECT_ROOT))
    if rewritten.get("csv_path"):
        rewritten["csv_path"] = str((new_root / Path(rewritten["csv_path"]).name).relative_to(PROJECT_ROOT))
    for entry in rewritten.get("manifest", []):
        key = "Local Path" if "Local Path" in entry else "local_path" if "local_path" in entry else None
        if not key:
            continue
        old = Path(str(entry[key]))
        absolute = old if old.is_absolute() else PROJECT_ROOT / old
        try:
            relative = absolute.resolve().relative_to(old_root.resolve())
        except ValueError:
            relative = Path(absolute.name)
        entry[key] = str((new_root / relative).relative_to(PROJECT_ROOT))
    return rewritten


def migrate_lightcurves(report: dict[str, Any], *, execute: bool) -> None:
    if not LEGACY_LIGHTCURVES.exists():
        return
    cache = LEGACY_LIGHTCURVES / "_cache"
    for source in iter_files(cache):
        report["cache_files_seen"] += 1
        report["source_bytes"] += source.stat().st_size
        if execute:
            relative = source.relative_to(cache)
            if relative.parts and relative.parts[0] == "search":
                relative = Path("mast-search", *relative.parts[1:])
            copy_verified(source, CACHE_ROOT / relative, report)
    for manifest_path in sorted(LEGACY_LIGHTCURVES.rglob("manifest.json")):
        if cache in manifest_path.parents:
            continue
        old_dir = manifest_path.parent
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report["invalid_datasets"].append(str(old_dir))
            continue
        if not isinstance(manifest, dict):
            report["invalid_datasets"].append(str(old_dir)); continue
        target = str(manifest.get("target") or old_dir.parent.name)
        dataset_key = str(manifest.get("dataset_key") or old_dir.name)
        destination = LIGHTCURVE_OBJECT_ROOT / safe_slug(target) / safe_slug(dataset_key)
        report["datasets_seen"] += 1
        for source in iter_files(old_dir):
            report["source_bytes"] += source.stat().st_size
            if execute and source.name != "manifest.json":
                copy_verified(source, destination / source.relative_to(old_dir), report)
        if execute:
            rewritten = rewrite_manifest_paths(manifest, old_dir, destination)
            rewritten.setdefault("dataset_key", dataset_key)
            rewritten.setdefault("target", target)
            destination.mkdir(parents=True, exist_ok=True)
            manifest_destination = destination / "manifest.json"
            payload = json.dumps(rewritten, ensure_ascii=False, indent=2).encode("utf-8")
            temporary = manifest_destination.with_name(f".{manifest_destination.name}.{uuid4().hex}.part")
            temporary.write_bytes(payload)
            os.replace(temporary, manifest_destination)
            workspace.register_dataset(destination, rewritten)
            report["datasets_imported"] += 1


def import_legacy_profile(report: dict[str, Any], owner: dict[str, Any] | None, execute: bool) -> None:
    if owner is None:
        return
    settings = load_settings()
    if not settings.deepseek_api_key:
        return
    report["legacy_profile_found"] = True
    existing = workspace.list_profiles(owner["user_id"])
    if not execute or any(item["name"] == "Legacy DeepSeek" for item in existing):
        return
    workspace.save_profile(owner["user_id"], {
        "name": "Legacy DeepSeek", "provider": "deepseek",
        "base_url": settings.deepseek_base_url, "model": settings.deepseek_model,
        "api_key": settings.deepseek_api_key, "timeout_sec": settings.timeout_sec,
        "is_default": True, "is_enabled": True,
    })
    report["legacy_profile_imported"] = True


def verify_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    failures: list[dict[str, str]] = []
    checked = 0
    for item in report.get("files", []):
        destination = Path(item["destination"])
        checked += 1
        if not destination.is_file():
            failures.append({"path": str(destination), "error": "missing"})
        elif sha256_file(destination) != item["sha256"]:
            failures.append({"path": str(destination), "error": "checksum mismatch"})
    return {"checked": checked, "failures": failures, "status": "ok" if not failures else "failed"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy Target Info data into warehouse/")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--verify", metavar="REPORT", type=Path)
    parser.add_argument("--owner", help="Administrator receiving legacy private LLM settings/history")
    args = parser.parse_args()
    workspace.initialize()
    if args.verify:
        result = verify_report(args.verify.resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ok" else 1

    owner = workspace.find_user(args.owner) if args.owner else None
    if args.owner and owner is None:
        parser.error(f"Owner account not found: {args.owner}")
    migration_id = str(uuid4())
    report: dict[str, Any] = {
        "migration_id": migration_id, "mode": "execute" if args.execute else "dry-run",
        "generated_at": datetime.now(timezone.utc).isoformat(), "owner": args.owner,
        "targets_seen": 0, "targets_imported": 0, "targets_skipped": 0,
        "datasets_seen": 0, "datasets_imported": 0, "cache_files_seen": 0,
        "legacy_summaries": 0, "legacy_summaries_skipped": 0,
        "legacy_profile_found": False,
        "legacy_profile_imported": False, "copied_files": 0,
        "deduplicated_files": 0, "skipped_identical": 0,
        "source_bytes": 0, "copied_bytes": 0,
        "invalid_results": [], "invalid_datasets": [], "conflicts": [], "files": [],
        "result_files_seen": 0, "orphan_result_files": 0,
    }
    workspace.record_migration(mode=report["mode"], status="running", summary={}, migration_id=migration_id)
    try:
        migrate_targets(report, execute=args.execute, owner=owner)
        migrate_lightcurves(report, execute=args.execute)
        import_legacy_profile(report, owner, args.execute)
        report_path = MANIFEST_ROOT / f"migration-{migration_id}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        persisted_report = {
            key: value for key, value in report.items() if not key.startswith("_")
        }
        atomic_write_json(report_path, persisted_report)
        status = "failed" if report["conflicts"] else "complete"
        workspace.record_migration(
            mode=report["mode"], status=status, summary={
                key: value for key, value in report.items()
                if key != "files" and not key.startswith("_")
            },
            report_path=str(report_path.relative_to(PROJECT_ROOT)), migration_id=migration_id,
        )
    except Exception as exc:
        workspace.record_migration(mode=report["mode"], status="failed", summary={"error": str(exc)}, migration_id=migration_id)
        raise
    print(json.dumps({
        key: value for key, value in report.items()
        if key != "files" and not key.startswith("_")
    }, ensure_ascii=False, indent=2))
    return 1 if report["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
