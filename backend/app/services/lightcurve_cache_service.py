from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterator

from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data" / "lightcurves"
CACHE_ROOT = DATA_ROOT / "_cache"
SEARCH_CACHE_ROOT = CACHE_ROOT / "search"
PRODUCT_CACHE_ROOT = CACHE_ROOT / "products"
DERIVED_CACHE_ROOT = CACHE_ROOT / "derived"
ANALYSIS_CACHE_ROOT = CACHE_ROOT / "analysis"
LOCK_ROOT = CACHE_ROOT / "locks"
CACHE_SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(value: Any) -> str:
    payload = json.dumps(value,
                         ensure_ascii=False,
                         sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.",
                                          suffix=".tmp",
                                          dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


@contextmanager
def cache_lock(key: str) -> Iterator[None]:
    LOCK_ROOT.mkdir(parents=True, exist_ok=True)
    lock_path = LOCK_ROOT / f"{stable_hash(key)}.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def resolve_data_path(download_dir: str) -> Path:
    raw_path = Path(download_dir)
    candidate = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
    resolved = candidate.resolve()
    data_root = DATA_ROOT.resolve()
    if resolved != data_root and data_root not in resolved.parents:
        raise HTTPException(
            status_code=400,
            detail="download_dir must be under data/lightcurves")
    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(status_code=404,
                            detail=f"download_dir not found: {download_dir}")
    return resolved


def manifest_local_paths(manifest: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for item in manifest.get("manifest", []):
        local_path = item.get("Local Path") or item.get("local_path")
        if not local_path:
            continue
        path = Path(local_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        paths.append(path)
    return paths


def validate_dataset_dir(
        dataset_dir: Path,
        *,
        deep: bool = False) -> tuple[bool, list[str], dict[str, Any] | None]:
    errors: list[str] = []
    manifest_path = dataset_dir / "manifest.json"
    products_path = dataset_dir / "selected_products.json"
    manifest = read_json(manifest_path)
    products = read_json(products_path)
    if not isinstance(manifest, dict):
        errors.append("missing or invalid manifest.json")
    if not isinstance(products, list) or not products:
        errors.append("missing or invalid selected_products.json")
    if errors or manifest is None:
        return False, errors, manifest

    if manifest.get("status") not in {None, "complete"}:
        errors.append(f"dataset status is {manifest.get('status')!r}")

    entries = manifest.get("manifest", [])
    if not entries:
        errors.append("manifest contains no products")
    for index, entry in enumerate(entries):
        local_path = entry.get("Local Path") or entry.get("local_path")
        if not local_path:
            errors.append(f"product {index} has no local path")
            continue
        path = Path(local_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        status = str(entry.get("Status") or entry.get("status") or "").upper()
        if status not in {"", "COMPLETE"}:
            errors.append(f"product {index} status is {status}")
        if not path.exists() or not path.is_file():
            errors.append(f"product {index} file is missing: {path}")
            continue
        expected_size = entry.get("size") or entry.get("Size")
        if expected_size is not None:
            try:
                if path.stat().st_size != int(expected_size):
                    errors.append(f"product {index} size mismatch: {path}")
            except (TypeError, ValueError):
                pass
        expected_sha = entry.get("sha256")
        if deep and expected_sha and file_sha256(path) != expected_sha:
            errors.append(f"product {index} checksum mismatch: {path}")
    return not errors, errors, manifest


def iter_dataset_dirs() -> Iterator[Path]:
    if not DATA_ROOT.exists():
        return
    for manifest_path in DATA_ROOT.rglob("manifest.json"):
        if CACHE_ROOT in manifest_path.parents:
            continue
        yield manifest_path.parent


def unique_storage_size(paths: Iterator[Path]) -> int:
    total = 0
    seen: set[tuple[int, int]] = set()
    for root in paths:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            try:
                stat = path.stat()
            except OSError:
                continue
            if not path.is_file():
                continue
            identity = (stat.st_dev, stat.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            total += stat.st_size
    return total


def remove_tree(path: Path) -> int:
    size = unique_storage_size(iter([path]))
    shutil.rmtree(path)
    return size


class LightCurveCacheService:

    def stats(self) -> dict[str, Any]:
        datasets = list(iter_dataset_dirs())
        valid = 0
        invalid = 0
        for dataset_dir in datasets:
            ok, _, _ = validate_dataset_dir(dataset_dir)
            valid += int(ok)
            invalid += int(not ok)

        search_files = list(SEARCH_CACHE_ROOT.glob(
            "*.json")) if SEARCH_CACHE_ROOT.exists() else []
        product_dirs = (
            [path for path in PRODUCT_CACHE_ROOT.iterdir()
             if path.is_dir()] if PRODUCT_CACHE_ROOT.exists() else [])
        derived_files = list(DERIVED_CACHE_ROOT.rglob(
            "*.npz")) if DERIVED_CACHE_ROOT.exists() else []
        analysis_files = list(ANALYSIS_CACHE_ROOT.rglob(
            "*.json")) if ANALYSIS_CACHE_ROOT.exists() else []
        bytes_used = unique_storage_size(iter([DATA_ROOT
                                               ])) if DATA_ROOT.exists() else 0
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "bytes_used": bytes_used,
            "megabytes_used": round(bytes_used / 1024 / 1024, 2),
            "datasets": len(datasets),
            "valid_datasets": valid,
            "invalid_datasets": invalid,
            "search_entries": len(search_files),
            "product_entries": len(product_dirs),
            "derived_entries": len(derived_files),
            "analysis_entries": len(analysis_files),
        }

    def verify(self,
               *,
               deep: bool = False,
               repair: bool = False) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for dataset_dir in sorted(iter_dataset_dirs()):
            ok, errors, manifest = validate_dataset_dir(dataset_dir, deep=deep)
            if repair and not ok and isinstance(manifest, dict):
                manifest["status"] = "invalid"
                manifest["validation_errors"] = errors
                manifest["validated_at"] = utc_now()
                atomic_write_json(dataset_dir / "manifest.json", manifest)
            results.append({
                "download_dir":
                str(dataset_dir.relative_to(PROJECT_ROOT)),
                "valid":
                ok,
                "errors":
                errors,
            })
        return {
            "deep": deep,
            "repair": repair,
            "checked": len(results),
            "valid": sum(int(item["valid"]) for item in results),
            "invalid": sum(int(not item["valid"]) for item in results),
            "datasets": results,
        }

    def delete_dataset(self, download_dir: str) -> dict[str, Any]:
        dataset_dir = resolve_data_path(download_dir)
        if dataset_dir == DATA_ROOT.resolve() or CACHE_ROOT.resolve() in (
                dataset_dir,
                *dataset_dir.parents,
        ):
            raise HTTPException(status_code=400,
                                detail="Not a dataset directory")
        if not (dataset_dir / "manifest.json").exists():
            raise HTTPException(status_code=400,
                                detail="Dataset manifest not found")
        removed_bytes = remove_tree(dataset_dir)
        parent = dataset_dir.parent
        if parent != DATA_ROOT and not any(parent.iterdir()):
            parent.rmdir()
        return {"deleted": download_dir, "removed_bytes": removed_bytes}

    def cleanup(
        self,
        *,
        max_age_days: float | None = None,
        max_size_mb: float | None = None,
        dry_run: bool = True,
        remove_unreferenced_products: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).timestamp()
        datasets: list[tuple[Path, float, int]] = []
        for path in iter_dataset_dirs():
            manifest = read_json(path / "manifest.json", {})
            timestamp = path.stat().st_mtime
            generated_at = manifest.get("last_accessed_at") or manifest.get(
                "generated_at")
            if generated_at:
                try:
                    timestamp = datetime.fromisoformat(
                        generated_at).timestamp()
                except (TypeError, ValueError):
                    pass
            datasets.append(
                (path, timestamp, unique_storage_size(iter([path]))))
        datasets.sort(key=lambda item: item[1])

        selected: list[tuple[Path, str]] = []
        selected_paths: set[Path] = set()
        if max_age_days is not None:
            cutoff = now - max_age_days * 86400
            for path, timestamp, _ in datasets:
                if timestamp < cutoff:
                    selected.append((path, "age"))
                    selected_paths.add(path)

        if max_size_mb is not None:
            current = self.stats()["bytes_used"]
            limit = int(max_size_mb * 1024 * 1024)
            for path, _, size in datasets:
                if current <= limit:
                    break
                if path not in selected_paths:
                    selected.append((path, "size"))
                    selected_paths.add(path)
                current -= size

        removed_bytes = 0
        for path, _ in selected:
            if not dry_run and path.exists():
                removed_bytes += remove_tree(path)

        unreferenced: list[Path] = []
        unreferenced_derived: list[Path] = []
        unreferenced_analysis: list[Path] = []
        expired_search: list[Path] = []
        stale_partial: list[Path] = []
        if remove_unreferenced_products and PRODUCT_CACHE_ROOT.exists():
            referenced_keys: set[str] = set()
            for dataset_dir in iter_dataset_dirs():
                if dataset_dir in selected_paths:
                    continue
                manifest = read_json(dataset_dir / "manifest.json", {})
                for entry in manifest.get("manifest", []):
                    if entry.get("product_key"):
                        referenced_keys.add(entry["product_key"])
            unreferenced = [
                path for path in PRODUCT_CACHE_ROOT.iterdir()
                if path.is_dir() and path.name not in referenced_keys
            ]
            if not dry_run:
                for path in unreferenced:
                    removed_bytes += remove_tree(path)

        if remove_unreferenced_products:
            active_fingerprints: set[str] = set()
            active_analysis_keys: set[str] = set()
            for dataset_dir in iter_dataset_dirs():
                if dataset_dir in selected_paths:
                    continue
                manifest = read_json(dataset_dir / "manifest.json", {})
                if manifest.get("source_fingerprint"):
                    active_fingerprints.add(manifest["source_fingerprint"])
                active_analysis_keys.update(manifest.get("analysis_keys", []))

            if DERIVED_CACHE_ROOT.exists():
                unreferenced_derived = [
                    path for path in DERIVED_CACHE_ROOT.iterdir()
                    if path.is_dir() and path.name not in active_fingerprints
                ]
            if ANALYSIS_CACHE_ROOT.exists():
                unreferenced_analysis = [
                    path for path in ANALYSIS_CACHE_ROOT.glob("*.json")
                    if path.stem not in active_analysis_keys
                ]
            search_ttl = int(os.getenv("LIGHTCURVE_SEARCH_CACHE_TTL", "0"))
            if search_ttl > 0 and SEARCH_CACHE_ROOT.exists():
                expired_search = [
                    path for path in SEARCH_CACHE_ROOT.glob("*.json")
                    if now - path.stat().st_mtime > search_ttl
                ]
            if not dry_run:
                for path in unreferenced_derived:
                    removed_bytes += remove_tree(path)
                for path in (*unreferenced_analysis, *expired_search):
                    try:
                        removed_bytes += path.stat().st_size
                        path.unlink()
                    except FileNotFoundError:
                        pass

        if DATA_ROOT.exists():
            partial_candidates = list(DATA_ROOT.glob("*/.partial-*"))
            downloads_root = DATA_ROOT / ".downloads"
            if downloads_root.exists():
                partial_candidates.extend(path
                                          for path in downloads_root.iterdir()
                                          if path.is_dir())
            stale_partial = [
                path for path in partial_candidates
                if now - path.stat().st_mtime > 3600
            ]
            if not dry_run:
                for path in stale_partial:
                    removed_bytes += remove_tree(path)

        return {
            "dry_run":
            dry_run,
            "datasets": [{
                "download_dir": str(path.relative_to(PROJECT_ROOT)),
                "reason": reason
            } for path, reason in selected],
            "unreferenced_products":
            len(unreferenced),
            "unreferenced_derived":
            len(unreferenced_derived),
            "unreferenced_analysis":
            len(unreferenced_analysis),
            "expired_search_entries":
            len(expired_search),
            "stale_partial_directories":
            len(stale_partial),
            "removed_bytes":
            removed_bytes,
        }
