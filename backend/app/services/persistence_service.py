"""PostgreSQL metadata + S3/MinIO object persistence.

The astronomy processing stack still needs local seekable files.  In external
mode this module treats the local ``results/`` and ``data/`` directories as a
working cache while PostgreSQL and object storage remain authoritative.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalized_target(value: str) -> str:
    return " ".join(value.strip().casefold().split())


@dataclass(frozen=True)
class PersistenceSettings:
    backend: str
    database_url: str
    s3_endpoint_url: str | None
    s3_access_key: str | None
    s3_secret_key: str | None
    s3_bucket: str
    s3_region: str
    s3_prefix: str
    s3_create_bucket: bool

    @property
    def external(self) -> bool:
        return self.backend == "postgres-s3"

    @classmethod
    def from_env(cls) -> "PersistenceSettings":
        backend = os.getenv("PERSISTENCE_BACKEND", "filesystem").strip().lower()
        return cls(
            backend=backend,
            database_url=os.getenv("DATABASE_URL", ""),
            s3_endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
            s3_access_key=os.getenv("S3_ACCESS_KEY") or None,
            s3_secret_key=os.getenv("S3_SECRET_KEY") or None,
            s3_bucket=os.getenv("S3_BUCKET", "target-info-search"),
            s3_region=os.getenv("S3_REGION", "us-east-1"),
            s3_prefix=os.getenv("S3_PREFIX", "").strip("/"),
            s3_create_bucket=os.getenv("S3_CREATE_BUCKET", "true").lower()
            in {"1", "true", "yes", "on"},
        )


class PersistenceService:
    def __init__(self, settings: PersistenceSettings | None = None) -> None:
        self.settings = settings or PersistenceSettings.from_env()
        self._engine: Any = None
        self._s3: Any = None
        self._metadata: Any = None
        self._tables: dict[str, Any] = {}
        self._initialized = False

    @property
    def enabled(self) -> bool:
        return self.settings.external

    def _require_config(self) -> None:
        if not self.settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is required when PERSISTENCE_BACKEND=postgres-s3"
            )
        if not self.settings.s3_bucket:
            raise RuntimeError(
                "S3_BUCKET is required when PERSISTENCE_BACKEND=postgres-s3"
            )

    def _init_clients(self) -> None:
        if not self.enabled or self._engine is not None:
            return
        self._require_config()
        try:
            import boto3
            import sqlalchemy as sa
            from sqlalchemy.dialects.postgresql import JSONB
        except ImportError as exc:
            raise RuntimeError(
                "postgres-s3 persistence requires sqlalchemy, psycopg and boto3"
            ) from exc

        self._engine = sa.create_engine(
            self.settings.database_url,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        self._s3 = boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name=self.settings.s3_region,
        )
        metadata = sa.MetaData()
        json_type = JSONB()
        self._tables["targets"] = sa.Table(
            "target_results",
            metadata,
            sa.Column("target_key", sa.String(512), primary_key=True),
            sa.Column("display_name", sa.String(512), nullable=False, index=True),
            sa.Column("payload", json_type, nullable=False),
            sa.Column("object_key", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        self._tables["datasets"] = sa.Table(
            "lightcurve_datasets",
            metadata,
            sa.Column("dataset_key", sa.String(64), primary_key=True),
            sa.Column("target_name", sa.String(512), nullable=False, index=True),
            sa.Column("download_dir", sa.Text(), nullable=False, unique=True),
            sa.Column("object_prefix", sa.Text(), nullable=False),
            sa.Column("manifest", json_type, nullable=False),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False, default=0),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        self._tables["catalog"] = sa.Table(
            "catalog_entries",
            metadata,
            sa.Column("entry_id", sa.String(512), primary_key=True),
            sa.Column("entry_type", sa.String(64), nullable=False, index=True),
            sa.Column("display_name", sa.String(512), nullable=False, index=True),
            sa.Column("entry", json_type, nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        self._metadata = metadata

    def initialize(self) -> None:
        if not self.enabled or self._initialized:
            return
        self._init_clients()
        self._metadata.create_all(self._engine)
        if not self.settings.s3_create_bucket:
            self._initialized = True
            return
        try:
            self._s3.head_bucket(Bucket=self.settings.s3_bucket)
        except Exception:
            params: dict[str, Any] = {"Bucket": self.settings.s3_bucket}
            if (
                self.settings.s3_region
                and self.settings.s3_region != "us-east-1"
                and not self.settings.s3_endpoint_url
            ):
                params["CreateBucketConfiguration"] = {
                    "LocationConstraint": self.settings.s3_region
                }
            self._s3.create_bucket(**params)
        self._initialized = True

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        self.initialize()
        with self._engine.begin() as connection:
            yield connection

    @contextmanager
    def distributed_lock(self, key: str) -> Iterator[None]:
        """Use a PostgreSQL advisory lock to coordinate multiple API nodes."""
        if not self.enabled:
            yield
            return
        import sqlalchemy as sa

        digest = hashlib.sha256(key.encode("utf-8")).digest()[:8]
        lock_id = int.from_bytes(digest, "big", signed=True)
        self.initialize()
        with self._engine.connect() as connection:
            connection.execute(
                sa.text("SELECT pg_advisory_lock(:lock_id)"),
                {"lock_id": lock_id},
            )
            try:
                yield
            finally:
                connection.execute(
                    sa.text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": lock_id},
                )

    def _object_key(self, suffix: str) -> str:
        suffix = suffix.lstrip("/")
        return f"{self.settings.s3_prefix}/{suffix}" if self.settings.s3_prefix else suffix

    def _put_bytes(
        self, key: str, payload: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self.initialize()
        self._s3.put_object(
            Bucket=self.settings.s3_bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
        )

    def _upload_file(self, path: Path, key: str) -> None:
        self.initialize()
        self._s3.upload_file(str(path), self.settings.s3_bucket, key)

    def _download_file(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.s3-part")
        self._s3.download_file(self.settings.s3_bucket, key, str(temporary))
        os.replace(temporary, destination)

    def _delete_prefix(self, prefix: str) -> None:
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.settings.s3_bucket, Prefix=prefix):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if keys:
                self._s3.delete_objects(
                    Bucket=self.settings.s3_bucket, Delete={"Objects": keys}
                )

    def save_target(self, target: str, payload: dict[str, Any]) -> str | None:
        if not self.enabled:
            return None
        from sqlalchemy.dialects.postgresql import insert

        target_key = _normalized_target(target)
        object_name = hashlib.sha256(target_key.encode("utf-8")).hexdigest()
        object_key = self._object_key(f"targets/{object_name}.json")
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._put_bytes(object_key, raw, "application/json")
        now = _utc_now()
        table = self._tables["targets"]
        statement = insert(table).values(
            target_key=target_key,
            display_name=target,
            payload=payload,
            object_key=object_key,
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.target_key],
            set_={
                "display_name": statement.excluded.display_name,
                "payload": statement.excluded.payload,
                "object_key": statement.excluded.object_key,
                "updated_at": statement.excluded.updated_at,
            },
        )
        with self._connection() as connection:
            connection.execute(statement)
        return f"s3://{self.settings.s3_bucket}/{object_key}"

    def load_target(self, target: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        import sqlalchemy as sa

        table = self._tables["targets"]
        with self._connection() as connection:
            row = connection.execute(
                sa.select(table.c.payload).where(
                    table.c.target_key == _normalized_target(target)
                )
            ).scalar_one_or_none()
        return dict(row) if isinstance(row, dict) else None

    def delete_target(self, target: str) -> int | None:
        if not self.enabled:
            return None
        import sqlalchemy as sa

        table = self._tables["targets"]
        with self._connection() as connection:
            row = connection.execute(
                sa.select(table).where(
                    table.c.target_key == _normalized_target(target)
                )
            ).mappings().one_or_none()
        if row is None:
            return None
        self._s3.delete_object(
            Bucket=self.settings.s3_bucket, Key=row["object_key"]
        )
        with self._connection() as connection:
            connection.execute(
                sa.delete(table).where(
                    table.c.target_key == row["target_key"]
                )
            )
        return len(
            json.dumps(row["payload"], ensure_ascii=False).encode("utf-8")
        )

    def save_dataset(self, dataset_dir: Path, manifest: dict[str, Any]) -> None:
        if not self.enabled:
            return
        from sqlalchemy.dialects.postgresql import insert

        dataset_key = str(manifest["dataset_key"])
        prefix = self._object_key(f"datasets/{dataset_key}/")
        size_bytes = 0
        for path in dataset_dir.rglob("*"):
            if not path.is_file():
                continue
            relative_path = path.relative_to(dataset_dir).as_posix()
            if relative_path == "manifest.json":
                continue
            size_bytes += path.stat().st_size
            self._upload_file(path, f"{prefix}{relative_path}")
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=False, indent=2
        ).encode("utf-8")
        size_bytes += len(manifest_bytes)
        self._put_bytes(
            f"{prefix}manifest.json", manifest_bytes, "application/json"
        )
        now = _utc_now()
        table = self._tables["datasets"]
        statement = insert(table).values(
            dataset_key=dataset_key,
            target_name=str(manifest.get("target") or dataset_dir.parent.name),
            download_dir=str(manifest["download_dir"]),
            object_prefix=prefix,
            manifest=manifest,
            size_bytes=size_bytes,
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.dataset_key],
            set_={
                "manifest": statement.excluded.manifest,
                "size_bytes": statement.excluded.size_bytes,
                "updated_at": statement.excluded.updated_at,
            },
        )
        with self._connection() as connection:
            connection.execute(statement)

    def find_dataset(self, dataset_key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        import sqlalchemy as sa

        table = self._tables["datasets"]
        with self._connection() as connection:
            row = connection.execute(
                sa.select(table).where(table.c.dataset_key == dataset_key)
            ).mappings().one_or_none()
        return dict(row) if row else None

    def list_datasets(self, target: str | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        import sqlalchemy as sa

        table = self._tables["datasets"]
        query = sa.select(table).order_by(table.c.updated_at.desc())
        if target:
            query = query.where(
                sa.func.lower(table.c.target_name) == target.strip().lower()
            )
        with self._connection() as connection:
            rows = connection.execute(query).mappings().all()
        return [dict(row) for row in rows]

    def ensure_dataset_local(self, download_dir: str) -> Path | None:
        if not self.enabled:
            return None
        import sqlalchemy as sa

        table = self._tables["datasets"]
        with self._connection() as connection:
            row = connection.execute(
                sa.select(table).where(table.c.download_dir == download_dir)
            ).mappings().one_or_none()
        if row is None:
            return None
        destination = (PROJECT_ROOT / download_dir).resolve()
        allowed_root = (PROJECT_ROOT / "data" / "lightcurves").resolve()
        if destination != allowed_root and allowed_root not in destination.parents:
            raise RuntimeError(
                f"Refusing to materialize dataset outside {allowed_root}: {download_dir}"
            )
        if (destination / "manifest.json").exists():
            return destination
        prefix = row["object_prefix"]
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=self.settings.s3_bucket, Prefix=prefix
        ):
            for item in page.get("Contents", []):
                relative = item["Key"][len(prefix):]
                if not relative:
                    continue
                target = (destination / relative).resolve()
                if destination != target and destination not in target.parents:
                    raise RuntimeError(
                        f"Unsafe object key below dataset prefix: {item['Key']}"
                    )
                self._download_file(item["Key"], target)
        return destination if (destination / "manifest.json").exists() else None

    def delete_dataset(self, download_dir: str) -> int | None:
        if not self.enabled:
            return None
        import sqlalchemy as sa

        table = self._tables["datasets"]
        with self._connection() as connection:
            row = connection.execute(
                sa.select(table).where(table.c.download_dir == download_dir)
            ).mappings().one_or_none()
        if row is None:
            return None
        self._delete_prefix(row["object_prefix"])
        with self._connection() as connection:
            connection.execute(
                sa.delete(table).where(table.c.dataset_key == row["dataset_key"])
            )
        return int(row["size_bytes"] or 0)

    def delete_dataset_object(self, file_path: str) -> int | None:
        """Delete one persisted dataset object addressed by its API file path."""
        if not self.enabled:
            return None
        import sqlalchemy as sa

        normalized = file_path.lstrip("/")
        table = self._tables["datasets"]
        with self._connection() as connection:
            rows = connection.execute(sa.select(table)).mappings().all()
            row = next(
                (
                    item
                    for item in rows
                    if normalized.startswith(
                        str(item["download_dir"]).rstrip("/") + "/"
                    )
                ),
                None,
            )
            if row is None:
                return None
            relative = normalized[len(str(row["download_dir"]).rstrip("/")) + 1 :]
            key = f"{row['object_prefix']}{relative}"
            try:
                response = self._s3.head_object(
                    Bucket=self.settings.s3_bucket, Key=key
                )
                size = int(response.get("ContentLength") or 0)
            except Exception:
                return None
            self._s3.delete_object(Bucket=self.settings.s3_bucket, Key=key)
            connection.execute(
                sa.update(table)
                .where(table.c.dataset_key == row["dataset_key"])
                .values(
                    size_bytes=max(0, int(row["size_bytes"] or 0) - size),
                    updated_at=_utc_now(),
                )
            )
        return size

    def load_catalog(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        import sqlalchemy as sa

        table = self._tables["catalog"]
        with self._connection() as connection:
            rows = connection.execute(
                sa.select(table.c.entry).order_by(table.c.updated_at.desc())
            ).scalars().all()
        return [dict(row) for row in rows if isinstance(row, dict)]

    def upsert_catalog(self, entries: list[dict[str, Any]]) -> None:
        if not self.enabled or not entries:
            return
        from sqlalchemy.dialects.postgresql import insert

        table = self._tables["catalog"]
        now = _utc_now()
        with self._connection() as connection:
            for entry in entries:
                statement = insert(table).values(
                    entry_id=entry["id"],
                    entry_type=entry.get("type", "unknown"),
                    display_name=entry.get("display_name", ""),
                    entry=entry,
                    updated_at=now,
                )
                connection.execute(
                    statement.on_conflict_do_update(
                        index_elements=[table.c.entry_id],
                        set_={
                            "entry_type": statement.excluded.entry_type,
                            "display_name": statement.excluded.display_name,
                            "entry": statement.excluded.entry,
                            "updated_at": statement.excluded.updated_at,
                        },
                    )
                )

    def delete_catalog_entry(self, entry_id: str) -> None:
        if not self.enabled:
            return
        import sqlalchemy as sa

        table = self._tables["catalog"]
        with self._connection() as connection:
            connection.execute(
                sa.delete(table).where(table.c.entry_id == entry_id)
            )

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"backend": "filesystem", "status": "ok"}
        import sqlalchemy as sa

        try:
            with self._connection() as connection:
                connection.execute(sa.text("SELECT 1"))
            self._s3.head_bucket(Bucket=self.settings.s3_bucket)
            return {
                "backend": "postgres-s3",
                "status": "ok",
                "bucket": self.settings.s3_bucket,
            }
        except Exception as exc:
            return {
                "backend": "postgres-s3",
                "status": "error",
                "detail": str(exc),
            }


persistence = PersistenceService()
