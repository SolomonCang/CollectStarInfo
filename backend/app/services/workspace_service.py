"""Shared scientific catalog, authentication, and private LLM workspace.

SQLite + ``warehouse/`` is the default authoritative store.  When the
PostgreSQL/S3 persistence backend is selected the same relational schema is
created in PostgreSQL, while existing S3 mirroring remains handled by
``persistence_service``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import tempfile
from typing import Any, Iterator
from uuid import NAMESPACE_URL, uuid4, uuid5

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import sqlalchemy as sa


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WAREHOUSE_ROOT = Path(
    os.getenv("WAREHOUSE_ROOT", str(PROJECT_ROOT / "warehouse"))
).expanduser().resolve()
DATABASE_PATH = WAREHOUSE_ROOT / "db" / "target_info.sqlite"
OBJECT_ROOT = WAREHOUSE_ROOT / "objects"
TARGET_OBJECT_ROOT = OBJECT_ROOT / "targets"
LIGHTCURVE_OBJECT_ROOT = OBJECT_ROOT / "lightcurves"
LLM_OBJECT_ROOT = OBJECT_ROOT / "llm"
CACHE_ROOT = WAREHOUSE_ROOT / "cache"
MANIFEST_ROOT = WAREHOUSE_ROOT / "manifests"
SECRET_ROOT = WAREHOUSE_ROOT / "secrets"
MASTER_KEY_PATH = SECRET_ROOT / "master.key"
SCHEMA_VERSION = 2
SESSION_COOKIE = "target_info_session"
SESSION_TTL_DAYS = 7


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def normalized_target(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def safe_slug(value: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in value.strip()
    ).strip("._")
    return cleaned[:96] or "item"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, payload: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_bytes(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
    )


def _database_url() -> str:
    explicit = os.getenv("WORKSPACE_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    if os.getenv("PERSISTENCE_BACKEND", "").strip().lower() == "postgres-s3":
        external = os.getenv("DATABASE_URL", "").strip()
        if external:
            return external
    return f"sqlite:///{DATABASE_PATH}"


def _default_deepseek_api_key() -> str:
    key_file = os.getenv("DEEPSEEK_API_KEY_FILE", "/app/DSAPI.key").strip()
    if key_file:
        try:
            value = Path(key_file).read_text(encoding="utf-8").strip()
        except OSError:
            value = ""
        if value:
            return value
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


@dataclass(frozen=True)
class SessionIdentity:
    user_id: str
    username: str
    role: str
    must_change_password: bool
    csrf_token: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict[str, Any]:
        return {
            "id": self.user_id,
            "username": self.username,
            "role": self.role,
            "is_admin": self.is_admin,
            "must_change_password": self.must_change_password,
            "csrf_token": self.csrf_token,
        }


class WorkspaceService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or _database_url()
        self._engine: sa.Engine | None = None
        self._metadata: sa.MetaData | None = None
        self.tables: dict[str, sa.Table] = {}
        self._initialized = False
        self._passwords = PasswordHasher()
        self._cipher: AESGCM | None = None

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite:")

    def _build_schema(self) -> None:
        metadata = sa.MetaData()
        json_type = sa.JSON()
        self.tables["schema_migrations"] = sa.Table(
            "schema_migrations", metadata,
            sa.Column("version", sa.Integer, primary_key=True),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        )
        self.tables["users"] = sa.Table(
            "users", metadata,
            sa.Column("user_id", sa.String(36), primary_key=True),
            sa.Column("username", sa.String(128), nullable=False, unique=True, index=True),
            sa.Column("password_hash", sa.Text, nullable=False),
            sa.Column("role", sa.String(16), nullable=False, default="user"),
            sa.Column("is_active", sa.Boolean, nullable=False, default=True),
            sa.Column("must_change_password", sa.Boolean, nullable=False, default=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        self.tables["sessions"] = sa.Table(
            "sessions", metadata,
            sa.Column("session_hash", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("csrf_token", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        self.tables["targets"] = sa.Table(
            "workspace_targets", metadata,
            sa.Column("target_id", sa.String(36), primary_key=True),
            sa.Column("target_key", sa.String(512), nullable=False, unique=True, index=True),
            sa.Column("display_name", sa.String(512), nullable=False, index=True),
            sa.Column("target_type", sa.String(128)),
            sa.Column("ra_deg", sa.Float),
            sa.Column("dec_deg", sa.Float),
            sa.Column("latest_snapshot_id", sa.String(36)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        self.tables["target_aliases"] = sa.Table(
            "target_aliases", metadata,
            sa.Column("alias_key", sa.String(512), primary_key=True),
            sa.Column("target_id", sa.String(36), sa.ForeignKey("workspace_targets.target_id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("display_alias", sa.String(512), nullable=False),
        )
        self.tables["target_snapshots"] = sa.Table(
            "target_snapshots", metadata,
            sa.Column("snapshot_id", sa.String(36), primary_key=True),
            sa.Column("target_id", sa.String(36), sa.ForeignKey("workspace_targets.target_id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source", sa.String(64), nullable=False),
            sa.Column("artifact_path", sa.Text, nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("size_bytes", sa.BigInteger, nullable=False),
        )
        self.tables["file_assets"] = sa.Table(
            "file_assets", metadata,
            sa.Column("asset_id", sa.String(36), primary_key=True),
            sa.Column("sha256", sa.String(64), nullable=False, index=True),
            sa.Column("relative_path", sa.Text, nullable=False, unique=True),
            sa.Column("size_bytes", sa.BigInteger, nullable=False),
            sa.Column("media_type", sa.String(128)),
            sa.Column("origin", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        self.tables["datasets"] = sa.Table(
            "workspace_lightcurve_datasets", metadata,
            sa.Column("dataset_id", sa.String(64), primary_key=True),
            sa.Column("target_id", sa.String(36), sa.ForeignKey("workspace_targets.target_id", ondelete="SET NULL"), index=True),
            sa.Column("target_name", sa.String(512), nullable=False, index=True),
            sa.Column("download_dir", sa.Text, nullable=False, unique=True),
            sa.Column("manifest_path", sa.Text, nullable=False),
            sa.Column("missions", json_type, nullable=False),
            sa.Column("product_count", sa.Integer, nullable=False, default=0),
            sa.Column("size_bytes", sa.BigInteger, nullable=False, default=0),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        self.tables["products"] = sa.Table(
            "workspace_lightcurve_products", metadata,
            sa.Column("product_id", sa.String(36), primary_key=True),
            sa.Column("dataset_id", sa.String(64), sa.ForeignKey("workspace_lightcurve_datasets.dataset_id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("product_uri", sa.Text),
            sa.Column("asset_id", sa.String(36), sa.ForeignKey("file_assets.asset_id", ondelete="SET NULL")),
            sa.Column("metadata", json_type, nullable=False),
        )
        self.tables["llm_profiles"] = sa.Table(
            "llm_profiles", metadata,
            sa.Column("profile_id", sa.String(36), primary_key=True),
            sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("provider", sa.String(64), nullable=False),
            sa.Column("base_url", sa.Text, nullable=False),
            sa.Column("model", sa.String(256), nullable=False),
            sa.Column("timeout_sec", sa.Integer, nullable=False, default=45),
            sa.Column("secret_nonce", sa.LargeBinary, nullable=False),
            sa.Column("secret_ciphertext", sa.LargeBinary, nullable=False),
            sa.Column("secret_suffix", sa.String(8), nullable=False),
            sa.Column("is_default", sa.Boolean, nullable=False, default=False),
            sa.Column("is_enabled", sa.Boolean, nullable=False, default=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("owner_user_id", "name", name="uq_llm_profile_owner_name"),
        )
        self.tables["llm_runs"] = sa.Table(
            "llm_runs", metadata,
            sa.Column("run_id", sa.String(36), primary_key=True),
            sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("target_id", sa.String(36), sa.ForeignKey("workspace_targets.target_id", ondelete="SET NULL"), index=True),
            sa.Column("target_name", sa.String(512), nullable=False, index=True),
            sa.Column("task_type", sa.String(64), nullable=False, index=True),
            sa.Column("profile_snapshot", json_type, nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("artifact_path", sa.Text),
            sa.Column("error_message", sa.Text),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
        )
        self.tables["migration_runs"] = sa.Table(
            "migration_runs", metadata,
            sa.Column("migration_id", sa.String(36), primary_key=True),
            sa.Column("mode", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("report_path", sa.Text),
            sa.Column("summary", json_type, nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
        )
        self._metadata = metadata

    def _upgrade_schema(self) -> None:
        """Remove v1 body columns after their file artifacts became authoritative."""
        assert self._engine is not None
        inspector = sa.inspect(self._engine)
        with self._engine.begin() as connection:
            run_columns = {item["name"] for item in inspector.get_columns("llm_runs")}
            if "request_payload" in run_columns:
                rows = connection.execute(sa.text(
                    "SELECT run_id, owner_user_id, target_id, target_name, artifact_path, request_payload FROM llm_runs"
                )).mappings().all()
                for row in rows:
                    existing = Path(row["artifact_path"]) if row["artifact_path"] else None
                    if existing is not None and not existing.is_absolute():
                        existing = PROJECT_ROOT / existing
                    directory = existing.parent if existing and existing.suffix else existing
                    if directory is None:
                        directory = (
                            LLM_OBJECT_ROOT / safe_slug(row["owner_user_id"])
                            / safe_slug(row["target_id"] or row["target_name"])
                            / row["run_id"]
                        )
                    payload = row["request_payload"]
                    if isinstance(payload, str):
                        try:
                            payload = json.loads(payload)
                        except json.JSONDecodeError:
                            payload = {"legacy_request": payload}
                    atomic_write_json(directory / "request.json", payload or {})
                    connection.execute(sa.text(
                        "UPDATE llm_runs SET artifact_path = :artifact_path WHERE run_id = :run_id"
                    ), {
                        "artifact_path": str(directory.relative_to(PROJECT_ROOT)),
                        "run_id": row["run_id"],
                    })
                connection.exec_driver_sql(
                    'ALTER TABLE "llm_runs" DROP COLUMN "request_payload"'
                )
            snapshot_columns = {
                item["name"] for item in inspector.get_columns("target_snapshots")
            }
            if "payload" in snapshot_columns:
                connection.exec_driver_sql(
                    'ALTER TABLE "target_snapshots" DROP COLUMN "payload"'
                )

    def initialize(self) -> None:
        if self._initialized:
            return
        for path in (
            DATABASE_PATH.parent, TARGET_OBJECT_ROOT, LIGHTCURVE_OBJECT_ROOT,
            LLM_OBJECT_ROOT, CACHE_ROOT, MANIFEST_ROOT, SECRET_ROOT,
        ):
            path.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if self.is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        self._engine = sa.create_engine(self.database_url, **kwargs)
        if self.is_sqlite:
            @sa.event.listens_for(self._engine, "connect")
            def _configure_sqlite(dbapi_connection: Any, _: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.close()
        self._build_schema()
        assert self._metadata is not None
        self._metadata.create_all(self._engine)
        self._upgrade_schema()
        migrations = self.tables["schema_migrations"]
        with self._engine.begin() as connection:
            exists = connection.execute(
                sa.select(migrations.c.version).where(migrations.c.version == SCHEMA_VERSION)
            ).scalar_one_or_none()
            if exists is None:
                connection.execute(migrations.insert().values(
                    version=SCHEMA_VERSION, applied_at=utc_now()
                ))
        self._initialized = True

    def connection(self) -> Iterator[sa.Connection]:
        self.initialize()
        assert self._engine is not None
        return self._engine.begin()

    def health(self) -> dict[str, Any]:
        try:
            self.initialize()
            with self.connection() as connection:
                users = connection.execute(sa.select(sa.func.count()).select_from(self.tables["users"])).scalar_one()
            database = "external"
            if self.is_sqlite:
                database = self.database_url.removeprefix("sqlite:///")
            return {
                "status": "ok",
                "backend": "sqlite-warehouse" if self.is_sqlite else "postgres-s3",
                "database": database,
                "users": int(users),
                "setup_required": int(users) == 0,
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    # Authentication -------------------------------------------------
    def create_user(
        self, username: str, password: str, *, role: str = "user",
        must_change_password: bool = False,
    ) -> dict[str, Any]:
        username = username.strip()
        if len(username) < 3:
            raise ValueError("Username must contain at least 3 characters")
        if len(password) < 10:
            raise ValueError("Password must contain at least 10 characters")
        if role not in {"user", "admin"}:
            raise ValueError("Role must be user or admin")
        now = utc_now()
        row = {
            "user_id": str(uuid4()), "username": username,
            "password_hash": self._passwords.hash(password), "role": role,
            "is_active": True, "must_change_password": must_change_password,
            "created_at": now, "updated_at": now,
        }
        with self.connection() as connection:
            connection.execute(self.tables["users"].insert().values(**row))
        return self._public_user(row)

    @staticmethod
    def _public_user(row: Any) -> dict[str, Any]:
        mapping = dict(row)
        return {
            "id": mapping["user_id"], "username": mapping["username"],
            "role": mapping["role"], "is_admin": mapping["role"] == "admin",
            "is_active": bool(mapping["is_active"]),
            "must_change_password": bool(mapping["must_change_password"]),
            "created_at": mapping["created_at"].isoformat() if hasattr(mapping["created_at"], "isoformat") else mapping["created_at"],
        }

    def list_users(self) -> list[dict[str, Any]]:
        users = self.tables["users"]
        with self.connection() as connection:
            rows = connection.execute(sa.select(users).order_by(users.c.username)).mappings().all()
        return [self._public_user(row) for row in rows]

    def find_user(self, username: str) -> dict[str, Any] | None:
        users = self.tables["users"]
        with self.connection() as connection:
            row = connection.execute(sa.select(users).where(
                sa.func.lower(users.c.username) == username.strip().lower()
            )).mappings().one_or_none()
        return dict(row) if row else None

    def authenticate(self, username: str, password: str) -> tuple[str, SessionIdentity]:
        users = self.tables["users"]
        with self.connection() as connection:
            row = connection.execute(
                sa.select(users).where(sa.func.lower(users.c.username) == username.strip().lower())
            ).mappings().one_or_none()
        if row is None or not row["is_active"]:
            raise ValueError("用户名或密码错误")
        try:
            self._passwords.verify(row["password_hash"], password)
        except VerifyMismatchError as exc:
            raise ValueError("用户名或密码错误") from exc
        if self._passwords.check_needs_rehash(row["password_hash"]):
            with self.connection() as connection:
                connection.execute(users.update().where(users.c.user_id == row["user_id"]).values(
                    password_hash=self._passwords.hash(password), updated_at=utc_now()
                ))
        token = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        session_hash = hashlib.sha256(token.encode()).hexdigest()
        sessions = self.tables["sessions"]
        with self.connection() as connection:
            connection.execute(sessions.delete().where(sessions.c.expires_at < utc_now()))
            connection.execute(sessions.insert().values(
                session_hash=session_hash, user_id=row["user_id"], csrf_token=csrf,
                expires_at=utc_now() + timedelta(days=SESSION_TTL_DAYS), created_at=utc_now(),
            ))
        return token, SessionIdentity(
            user_id=row["user_id"], username=row["username"], role=row["role"],
            must_change_password=bool(row["must_change_password"]), csrf_token=csrf,
        )

    def get_session(self, token: str | None) -> SessionIdentity | None:
        if not token:
            return None
        session_hash = hashlib.sha256(token.encode()).hexdigest()
        sessions, users = self.tables["sessions"], self.tables["users"]
        with self.connection() as connection:
            row = connection.execute(
                sa.select(sessions, users.c.username, users.c.role, users.c.is_active, users.c.must_change_password)
                .join(users, users.c.user_id == sessions.c.user_id)
                .where(sessions.c.session_hash == session_hash)
            ).mappings().one_or_none()
        expires = row["expires_at"] if row else None
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if row is None or not row["is_active"] or expires <= utc_now():
            if row is not None:
                self.delete_session(token)
            return None
        return SessionIdentity(
            user_id=row["user_id"], username=row["username"], role=row["role"],
            must_change_password=bool(row["must_change_password"]), csrf_token=row["csrf_token"],
        )

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connection() as connection:
            connection.execute(self.tables["sessions"].delete().where(
                self.tables["sessions"].c.session_hash == digest
            ))

    def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        if len(new_password) < 10:
            raise ValueError("新密码至少需要 10 个字符")
        users = self.tables["users"]
        with self.connection() as connection:
            row = connection.execute(sa.select(users).where(users.c.user_id == user_id)).mappings().one()
        try:
            self._passwords.verify(row["password_hash"], current_password)
        except VerifyMismatchError as exc:
            raise ValueError("当前密码错误") from exc
        with self.connection() as connection:
            connection.execute(users.update().where(users.c.user_id == user_id).values(
                password_hash=self._passwords.hash(new_password),
                must_change_password=False, updated_at=utc_now(),
            ))

    def update_user(self, user_id: str, *, is_active: bool | None = None, reset_password: bool = False) -> tuple[dict[str, Any], str | None]:
        users = self.tables["users"]
        temporary: str | None = None
        values: dict[str, Any] = {"updated_at": utc_now()}
        if is_active is not None:
            values["is_active"] = is_active
        if reset_password:
            temporary = secrets.token_urlsafe(12)
            values.update(password_hash=self._passwords.hash(temporary), must_change_password=True)
        with self.connection() as connection:
            connection.execute(users.update().where(users.c.user_id == user_id).values(**values))
            row = connection.execute(sa.select(users).where(users.c.user_id == user_id)).mappings().one_or_none()
            if is_active is False or reset_password:
                connection.execute(self.tables["sessions"].delete().where(self.tables["sessions"].c.user_id == user_id))
        if row is None:
            raise KeyError(user_id)
        return self._public_user(row), temporary

    # Encryption and LLM profiles -----------------------------------
    def _master_key(self) -> bytes:
        configured = os.getenv("APP_MASTER_KEY", "").strip()
        if configured:
            try:
                key = base64.urlsafe_b64decode(configured.encode())
            except Exception as exc:
                raise RuntimeError("APP_MASTER_KEY must be URL-safe base64") from exc
            if len(key) != 32:
                raise RuntimeError("APP_MASTER_KEY must decode to 32 bytes")
            return key
        if not self.is_sqlite:
            raise RuntimeError("APP_MASTER_KEY is required for external deployments")
        if not MASTER_KEY_PATH.exists():
            atomic_write_bytes(MASTER_KEY_PATH, AESGCM.generate_key(bit_length=256), 0o600)
        elif MASTER_KEY_PATH.stat().st_mode & 0o077:
            os.chmod(MASTER_KEY_PATH, 0o600)
        key = MASTER_KEY_PATH.read_bytes()
        if len(key) != 32:
            raise RuntimeError("Invalid warehouse master key")
        return key

    def _aes(self) -> AESGCM:
        if self._cipher is None:
            self._cipher = AESGCM(self._master_key())
        return self._cipher

    def _encrypt(self, value: str) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        return nonce, self._aes().encrypt(nonce, value.encode(), b"llm-profile-v1")

    def _decrypt(self, nonce: bytes, ciphertext: bytes) -> str:
        return self._aes().decrypt(nonce, ciphertext, b"llm-profile-v1").decode()

    @staticmethod
    def _profile_public(row: Any) -> dict[str, Any]:
        item = dict(row)
        return {
            "id": item["profile_id"], "name": item["name"],
            "provider": item["provider"], "base_url": item["base_url"],
            "model": item["model"], "timeout_sec": item["timeout_sec"],
            "is_default": bool(item["is_default"]),
            "is_enabled": bool(item["is_enabled"]),
            "api_key_configured": True, "api_key_suffix": item["secret_suffix"],
            "created_at": item["created_at"].isoformat() if hasattr(item["created_at"], "isoformat") else item["created_at"],
            "updated_at": item["updated_at"].isoformat() if hasattr(item["updated_at"], "isoformat") else item["updated_at"],
        }

    def list_profiles(self, owner_user_id: str) -> list[dict[str, Any]]:
        table = self.tables["llm_profiles"]
        with self.connection() as connection:
            rows = connection.execute(
                sa.select(table).where(table.c.owner_user_id == owner_user_id)
                .order_by(table.c.is_default.desc(), table.c.name)
            ).mappings().all()
        return [self._profile_public(row) for row in rows]

    def save_profile(self, owner_user_id: str, payload: dict[str, Any], profile_id: str | None = None) -> dict[str, Any]:
        table = self.tables["llm_profiles"]
        now = utc_now()
        provider = str(payload.get("provider") or "custom").strip()
        api_key = str(payload.get("api_key") or "").strip()
        uses_server_default = False
        if not api_key and profile_id is None and provider == "deepseek":
            api_key = _default_deepseek_api_key()
            uses_server_default = bool(api_key)
        with self.connection() as connection:
            existing = None
            if profile_id:
                existing = connection.execute(sa.select(table).where(
                    (table.c.profile_id == profile_id) & (table.c.owner_user_id == owner_user_id)
                )).mappings().one_or_none()
            if profile_id and existing is None:
                raise KeyError(profile_id)
            if api_key:
                nonce, ciphertext = self._encrypt(api_key)
                suffix = "默认" if uses_server_default else api_key[-4:]
            elif existing is not None:
                nonce, ciphertext, suffix = existing["secret_nonce"], existing["secret_ciphertext"], existing["secret_suffix"]
            elif provider == "deepseek":
                raise ValueError("服务器默认 DeepSeek API Key 未配置，请填写 API Key 或联系管理员")
            else:
                raise ValueError("API Key 不能为空")
            is_default = bool(payload.get("is_default", existing["is_default"] if existing else False))
            values = {
                "name": str(payload.get("name") or "").strip(),
                "provider": provider,
                "base_url": str(payload.get("base_url") or "").strip().rstrip("/"),
                "model": str(payload.get("model") or "").strip(),
                "timeout_sec": max(5, min(300, int(payload.get("timeout_sec") or 45))),
                "secret_nonce": nonce, "secret_ciphertext": ciphertext,
                "secret_suffix": suffix, "is_default": is_default,
                "is_enabled": bool(payload.get("is_enabled", True)), "updated_at": now,
            }
            if not values["name"] or not values["base_url"] or not values["model"]:
                raise ValueError("名称、Base URL 和模型不能为空")
            if is_default:
                connection.execute(table.update().where(table.c.owner_user_id == owner_user_id).values(is_default=False))
            if existing is None:
                profile_id = str(uuid4())
                connection.execute(table.insert().values(
                    profile_id=profile_id, owner_user_id=owner_user_id,
                    created_at=now, **values,
                ))
            else:
                connection.execute(table.update().where(table.c.profile_id == profile_id).values(**values))
            row = connection.execute(sa.select(table).where(table.c.profile_id == profile_id)).mappings().one()
        return self._profile_public(row)

    def get_profile_secret(self, owner_user_id: str, profile_id: str | None = None) -> dict[str, Any]:
        table = self.tables["llm_profiles"]
        query = sa.select(table).where(
            (table.c.owner_user_id == owner_user_id) & (table.c.is_enabled.is_(True))
        )
        if profile_id:
            query = query.where(table.c.profile_id == profile_id)
        else:
            query = query.order_by(table.c.is_default.desc(), table.c.created_at).limit(1)
        with self.connection() as connection:
            row = connection.execute(query).mappings().one_or_none()
        if row is None:
            raise KeyError(profile_id or "default")
        result = self._profile_public(row)
        result["api_key"] = self._decrypt(row["secret_nonce"], row["secret_ciphertext"])
        return result

    def delete_profile(self, owner_user_id: str, profile_id: str) -> None:
        table = self.tables["llm_profiles"]
        with self.connection() as connection:
            result = connection.execute(table.delete().where(
                (table.c.profile_id == profile_id) & (table.c.owner_user_id == owner_user_id)
            ))
        if result.rowcount == 0:
            raise KeyError(profile_id)

    # Shared targets and artifacts ----------------------------------
    def save_target(self, target_name: str, payload: dict[str, Any], *, source: str = "fresh") -> str:
        clean_payload = json.loads(json.dumps(payload, ensure_ascii=False))
        target_payload = clean_payload.get("target") or {}
        private_summary = target_payload.pop("summary", None)
        if private_summary is not None:
            target_payload["summary"] = None
        display = target_payload.get("resolved_target") or target_payload.get("query_target") or target_name
        key = normalized_target(str(display))
        target_id = str(uuid4())
        snapshot_id = str(uuid4())
        generated = clean_payload.get("generated_at") or iso()
        directory = TARGET_OBJECT_ROOT / safe_slug(target_id) / snapshot_id
        artifact = directory / "target.json"
        atomic_write_json(artifact, clean_payload)
        checksum, size = sha256_file(artifact), artifact.stat().st_size
        target_table, snapshots, aliases = self.tables["targets"], self.tables["target_snapshots"], self.tables["target_aliases"]
        simbad = target_payload.get("simbad") or {}
        now = utc_now()
        alias_values = {
            str(target_name), str(display),
            str(target_payload.get("query_target") or ""),
        }
        alias_keys = {
            normalized_target(alias) for alias in alias_values if alias.strip()
        }
        with self.connection() as connection:
            existing = connection.execute(
                sa.select(target_table).outerjoin(
                    aliases, aliases.c.target_id == target_table.c.target_id
                ).where(
                    (target_table.c.target_key == key)
                    | (aliases.c.alias_key.in_(alias_keys))
                ).limit(1)
            ).mappings().one_or_none()
            if existing:
                target_id = existing["target_id"]
                final_directory = TARGET_OBJECT_ROOT / safe_slug(target_id) / snapshot_id
                if final_directory != directory:
                    final_directory.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(directory, final_directory)
                    artifact = final_directory / "target.json"
                connection.execute(target_table.update().where(target_table.c.target_id == target_id).values(
                    display_name=display, target_type=target_payload.get("target_type"),
                    ra_deg=simbad.get("ra_deg"), dec_deg=simbad.get("dec_deg"),
                    latest_snapshot_id=snapshot_id, updated_at=now,
                ))
            else:
                connection.execute(target_table.insert().values(
                    target_id=target_id, target_key=key, display_name=display,
                    target_type=target_payload.get("target_type"), ra_deg=simbad.get("ra_deg"),
                    dec_deg=simbad.get("dec_deg"), latest_snapshot_id=snapshot_id,
                    created_at=now, updated_at=now,
                ))
            connection.execute(snapshots.insert().values(
                snapshot_id=snapshot_id, target_id=target_id,
                generated_at=_parse_datetime(generated), source=source,
                artifact_path=str(artifact.relative_to(PROJECT_ROOT)), sha256=checksum,
                size_bytes=size,
            ))
            for alias in alias_values:
                if not alias.strip():
                    continue
                alias_key = normalized_target(alias)
                exists = connection.execute(sa.select(aliases.c.alias_key).where(aliases.c.alias_key == alias_key)).scalar_one_or_none()
                if exists is None:
                    connection.execute(aliases.insert().values(alias_key=alias_key, target_id=target_id, display_alias=alias))
        return str(artifact.relative_to(PROJECT_ROOT))

    def load_target(self, target_name: str) -> dict[str, Any] | None:
        targets, aliases, snapshots = self.tables["targets"], self.tables["target_aliases"], self.tables["target_snapshots"]
        key = normalized_target(target_name)
        with self.connection() as connection:
            row = connection.execute(
                sa.select(targets).outerjoin(aliases, aliases.c.target_id == targets.c.target_id)
                .where((targets.c.target_key == key) | (aliases.c.alias_key == key)).limit(1)
            ).mappings().one_or_none()
            if row is None or not row["latest_snapshot_id"]:
                return None
            snapshot = connection.execute(sa.select(snapshots).where(
                snapshots.c.snapshot_id == row["latest_snapshot_id"]
            )).mappings().one_or_none()
        if snapshot is None:
            return None
        artifact = Path(snapshot["artifact_path"])
        if not artifact.is_absolute():
            artifact = PROJECT_ROOT / artifact
        try:
            payload = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        payload["source"] = "warehouse"
        payload["result_path"] = snapshot["artifact_path"]
        return payload

    def resolve_target_id(self, target_name: str) -> str | None:
        targets, aliases = self.tables["targets"], self.tables["target_aliases"]
        key = normalized_target(target_name)
        with self.connection() as connection:
            return connection.execute(
                sa.select(targets.c.target_id).outerjoin(aliases, aliases.c.target_id == targets.c.target_id)
                .where((targets.c.target_key == key) | (aliases.c.alias_key == key)).limit(1)
            ).scalar_one_or_none()

    def delete_target(self, target_name: str) -> int:
        target_id = self.resolve_target_id(target_name)
        if target_id is None:
            return 0
        targets, snapshots, aliases = self.tables["targets"], self.tables["target_snapshots"], self.tables["target_aliases"]
        with self.connection() as connection:
            paths = connection.execute(sa.select(snapshots.c.artifact_path).where(
                snapshots.c.target_id == target_id
            )).scalars().all()
            connection.execute(aliases.delete().where(aliases.c.target_id == target_id))
            connection.execute(snapshots.delete().where(snapshots.c.target_id == target_id))
            connection.execute(targets.delete().where(targets.c.target_id == target_id))
        removed = 0
        for relative in paths:
            path = (PROJECT_ROOT / relative).resolve()
            if WAREHOUSE_ROOT not in path.parents or not path.exists():
                continue
            root = path.parent
            removed += sum(item.stat().st_size for item in root.rglob("*") if item.is_file())
            shutil.rmtree(root, ignore_errors=True)
        target_root = TARGET_OBJECT_ROOT / safe_slug(target_id)
        if target_root.exists() and not any(target_root.iterdir()):
            target_root.rmdir()
        return removed

    def list_targets(self, search: str | None = None) -> list[dict[str, Any]]:
        targets = self.tables["targets"]
        query = sa.select(targets).order_by(targets.c.display_name)
        if search:
            query = query.where(sa.func.lower(targets.c.display_name).like(f"%{search.lower()}%"))
        with self.connection() as connection:
            rows = connection.execute(query).mappings().all()
        return [{
            "id": row["target_id"], "name": row["display_name"],
            "normalized": row["target_key"], "target_type": row["target_type"],
            "ra_deg": row["ra_deg"], "dec_deg": row["dec_deg"],
            "updated_at": _serialize_datetime(row["updated_at"]),
        } for row in rows]

    def register_dataset(self, dataset_dir: Path, manifest: dict[str, Any]) -> None:
        dataset_dir = dataset_dir.resolve()
        project_root = PROJECT_ROOT.resolve()
        target_name = str(manifest.get("target") or dataset_dir.parent.name)
        target_id = self.resolve_target_id(target_name)
        dataset_id = str(manifest.get("dataset_key") or hashlib.sha256(str(dataset_dir).encode()).hexdigest())
        size = sum(path.stat().st_size for path in dataset_dir.rglob("*") if path.is_file())
        now = utc_now()
        datasets = self.tables["datasets"]
        products = self.tables["products"]
        assets = self.tables["file_assets"]
        selected_path = dataset_dir / "selected_products.json"
        try:
            selected_products = json.loads(selected_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            selected_products = []
        selected_by_name = {
            str(item.get("productFilename") or item.get("filename") or ""): item
            for item in selected_products if isinstance(item, dict)
        }
        with self.connection() as connection:
            existing = connection.execute(sa.select(datasets.c.dataset_id).where(datasets.c.dataset_id == dataset_id)).scalar_one_or_none()
            values = dict(
                target_id=target_id, target_name=target_name,
                download_dir=str(dataset_dir.relative_to(project_root)),
                manifest_path=str((dataset_dir / "manifest.json").relative_to(project_root)),
                missions=manifest.get("missions") or [],
                product_count=int(manifest.get("selected_count") or len(manifest.get("manifest") or [])),
                size_bytes=size, updated_at=now,
            )
            if existing:
                connection.execute(datasets.update().where(datasets.c.dataset_id == dataset_id).values(**values))
            else:
                connection.execute(datasets.insert().values(dataset_id=dataset_id, created_at=now, **values))
            connection.execute(products.delete().where(products.c.dataset_id == dataset_id))
            for path in sorted(item for item in dataset_dir.rglob("*") if item.is_file()):
                checksum = sha256_file(path)
                stored_path = str(path.relative_to(project_root))
                existing_asset = connection.execute(
                    sa.select(assets).where(assets.c.relative_path == stored_path)
                ).mappings().one_or_none()
                asset_id = existing_asset["asset_id"] if existing_asset else None
                if existing_asset and existing_asset["sha256"] != checksum:
                    connection.execute(assets.update().where(
                        assets.c.asset_id == asset_id
                    ).values(
                        sha256=checksum, size_bytes=path.stat().st_size,
                        media_type=mimetypes.guess_type(path.name)[0],
                    ))
                if asset_id is None:
                    asset_id = str(uuid4())
                    connection.execute(assets.insert().values(
                        asset_id=asset_id, sha256=checksum,
                        relative_path=stored_path, size_bytes=path.stat().st_size,
                        media_type=mimetypes.guess_type(path.name)[0],
                        origin="lightcurve-dataset", created_at=now,
                    ))
                selected = selected_by_name.get(path.name)
                product_uri = None if selected is None else (
                    selected.get("dataURI") or selected.get("productURI")
                )
                product_id = str(uuid5(
                    NAMESPACE_URL,
                    f"{dataset_id}:{product_uri or path.relative_to(dataset_dir)}:{checksum}",
                ))
                connection.execute(products.insert().values(
                    product_id=product_id, dataset_id=dataset_id,
                    product_uri=product_uri, asset_id=asset_id,
                    metadata=selected or {
                        "filename": path.name,
                        "kind": "derived" if path.suffix.lower() in {".csv", ".npz"} else "dataset-asset",
                    },
                ))

    def unregister_dataset(self, download_dir: str) -> None:
        table = self.tables["datasets"]
        products = self.tables["products"]
        assets = self.tables["file_assets"]
        with self.connection() as connection:
            connection.execute(table.delete().where(table.c.download_dir == download_dir))
            referenced = sa.select(products.c.asset_id).where(products.c.asset_id.is_not(None))
            connection.execute(assets.delete().where(assets.c.asset_id.not_in(referenced)))

    # LLM runs -------------------------------------------------------
    def start_llm_run(self, owner_user_id: str, target_name: str, task_type: str, profile: dict[str, Any], request_payload: dict[str, Any]) -> str:
        run_id = str(uuid4())
        snapshot = {key: profile.get(key) for key in ("id", "name", "provider", "base_url", "model", "timeout_sec")}
        target_id = self.resolve_target_id(target_name)
        directory = LLM_OBJECT_ROOT / safe_slug(owner_user_id) / safe_slug(target_id or target_name) / run_id
        atomic_write_json(directory / "request.json", request_payload)
        with self.connection() as connection:
            connection.execute(self.tables["llm_runs"].insert().values(
                run_id=run_id, owner_user_id=owner_user_id,
                target_id=target_id, target_name=target_name,
                task_type=task_type, profile_snapshot=snapshot,
                status="running", artifact_path=str(directory.relative_to(PROJECT_ROOT)),
                created_at=utc_now(),
            ))
        return run_id

    def finish_llm_run(self, owner_user_id: str, run_id: str, result: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
        table = self.tables["llm_runs"]
        with self.connection() as connection:
            row = connection.execute(sa.select(table).where(
                (table.c.run_id == run_id) & (table.c.owner_user_id == owner_user_id)
            )).mappings().one()
        directory = LLM_OBJECT_ROOT / safe_slug(owner_user_id) / safe_slug(row["target_id"] or row["target_name"]) / run_id
        if result is not None:
            artifact = directory / "result.json"
            atomic_write_json(artifact, result)
            report = result.get("report") or result.get("summary")
            if report:
                atomic_write_bytes(directory / "report.md", str(report).encode("utf-8"))
        with self.connection() as connection:
            connection.execute(table.update().where(table.c.run_id == run_id).values(
                status="failed" if error else "complete",
                error_message=error, completed_at=utc_now(),
            ))
        return self.get_llm_run(owner_user_id, run_id)

    def get_llm_run(self, owner_user_id: str, run_id: str) -> dict[str, Any]:
        table = self.tables["llm_runs"]
        with self.connection() as connection:
            row = connection.execute(sa.select(table).where(
                (table.c.run_id == run_id) & (table.c.owner_user_id == owner_user_id)
            )).mappings().one_or_none()
        if row is None:
            raise KeyError(run_id)
        result = self._run_public(row)
        if row["artifact_path"]:
            path = Path(row["artifact_path"])
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            try:
                result["request"] = json.loads((path / "request.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result["request"] = None
            try:
                result["result"] = json.loads((path / "result.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result["result"] = None
        return result

    def list_llm_runs(self, owner_user_id: str, *, target_name: str | None = None, task_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        table = self.tables["llm_runs"]
        query = sa.select(table).where(table.c.owner_user_id == owner_user_id)
        if target_name:
            query = query.where(sa.func.lower(table.c.target_name) == target_name.strip().lower())
        if task_type:
            query = query.where(table.c.task_type == task_type)
        query = query.order_by(table.c.created_at.desc()).limit(max(1, min(500, limit)))
        with self.connection() as connection:
            rows = connection.execute(query).mappings().all()
        return [self._run_public(row) for row in rows]

    @staticmethod
    def _run_public(row: Any) -> dict[str, Any]:
        item = dict(row)
        return {
            "id": item["run_id"], "target": item["target_name"],
            "task_type": item["task_type"], "profile": item["profile_snapshot"],
            "status": item["status"],
            "error": item["error_message"], "artifact_path": item["artifact_path"],
            "created_at": _serialize_datetime(item["created_at"]),
            "completed_at": _serialize_datetime(item["completed_at"]),
        }

    def migration_status(self) -> list[dict[str, Any]]:
        table = self.tables["migration_runs"]
        with self.connection() as connection:
            rows = connection.execute(sa.select(table).order_by(table.c.started_at.desc()).limit(20)).mappings().all()
        return [{**dict(row), "started_at": _serialize_datetime(row["started_at"]), "completed_at": _serialize_datetime(row["completed_at"])} for row in rows]

    def record_migration(self, *, mode: str, status: str, summary: dict[str, Any], report_path: str | None = None, migration_id: str | None = None) -> str:
        table = self.tables["migration_runs"]
        migration_id = migration_id or str(uuid4())
        with self.connection() as connection:
            exists = connection.execute(sa.select(table.c.migration_id).where(table.c.migration_id == migration_id)).scalar_one_or_none()
            if exists:
                connection.execute(table.update().where(table.c.migration_id == migration_id).values(
                    status=status, summary=summary, report_path=report_path,
                    completed_at=utc_now() if status in {"complete", "failed"} else None,
                ))
            else:
                connection.execute(table.insert().values(
                    migration_id=migration_id, mode=mode, status=status,
                    summary=summary, report_path=report_path, started_at=utc_now(),
                    completed_at=utc_now() if status in {"complete", "failed"} else None,
                ))
        return migration_id

    def catalog_entries(self) -> list[dict[str, Any]]:
        targets, snapshots, datasets = self.tables["targets"], self.tables["target_snapshots"], self.tables["datasets"]
        entries: list[dict[str, Any]] = []
        with self.connection() as connection:
            target_rows = connection.execute(
                sa.select(targets, snapshots.c.artifact_path, snapshots.c.size_bytes, snapshots.c.generated_at)
                .join(snapshots, snapshots.c.snapshot_id == targets.c.latest_snapshot_id)
                .order_by(targets.c.display_name)
            ).mappings().all()
            dataset_rows = connection.execute(sa.select(datasets).order_by(datasets.c.updated_at.desc())).mappings().all()
        for row in target_rows:
            entries.append({
                "id": f"res_{row['target_id']}", "type": "target_result",
                "display_name": row["display_name"], "source": "SIMBAD+Gaia",
                "file_path": row["artifact_path"], "size_bytes": int(row["size_bytes"] or 0),
                "created_at": _serialize_datetime(row["generated_at"]),
                "tags": [str(row["target_type"] or "unknown").lower()],
                "metadata": {"target_type": row["target_type"], "ra_deg": row["ra_deg"], "dec_deg": row["dec_deg"], "persistence_target_key": row["display_name"]},
            })
        for row in dataset_rows:
            entries.append({
                "id": f"dataset_{row['dataset_id']}", "type": "lightcurve_dataset",
                "display_name": row["target_name"], "source": "MAST/" + "/".join(row["missions"] or []),
                "file_path": row["download_dir"], "size_bytes": int(row["size_bytes"] or 0),
                "created_at": _serialize_datetime(row["created_at"]), "tags": ["lightcurve", *[str(item).lower() for item in (row["missions"] or [])]],
                "valid": True, "metadata": {"missions": row["missions"] or [], "product_count": row["product_count"], "download_dir": row["download_dir"]},
            })
        return entries


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return utc_now()


def _serialize_datetime(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


workspace = WorkspaceService()
