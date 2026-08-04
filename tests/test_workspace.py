from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

import sqlalchemy as sa

from backend.app.services import workspace_service as module


class WorkspaceServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.master_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        self.environment = patch.dict(os.environ, {"APP_MASTER_KEY": self.master_key})
        self.environment.start()
        self.paths = patch.multiple(
            module,
            PROJECT_ROOT=self.root,
            WAREHOUSE_ROOT=self.root / "warehouse",
            DATABASE_PATH=self.root / "warehouse" / "db" / "target.sqlite",
            OBJECT_ROOT=self.root / "warehouse" / "objects",
            TARGET_OBJECT_ROOT=self.root / "warehouse" / "objects" / "targets",
            LIGHTCURVE_OBJECT_ROOT=self.root / "warehouse" / "objects" / "lightcurves",
            LLM_OBJECT_ROOT=self.root / "warehouse" / "objects" / "llm",
            CACHE_ROOT=self.root / "warehouse" / "cache",
            MANIFEST_ROOT=self.root / "warehouse" / "manifests",
            SECRET_ROOT=self.root / "warehouse" / "secrets",
            MASTER_KEY_PATH=self.root / "warehouse" / "secrets" / "master.key",
        )
        self.paths.start()
        self.service = module.WorkspaceService(
            f"sqlite:///{self.root / 'warehouse' / 'db' / 'target.sqlite'}"
        )
        self.service.initialize()

    def tearDown(self) -> None:
        self.paths.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def test_accounts_sessions_and_forced_password_change(self) -> None:
        user = self.service.create_user(
            "alice", "initial-password", must_change_password=True
        )
        token, identity = self.service.authenticate("alice", "initial-password")
        self.assertTrue(identity.must_change_password)
        self.assertEqual(self.service.get_session(token).user_id, user["id"])

        self.service.change_password(user["id"], "initial-password", "new-secure-password")
        changed_token, changed = self.service.authenticate("alice", "new-secure-password")
        self.assertFalse(changed.must_change_password)
        self.service.delete_session(token)
        self.assertIsNone(self.service.get_session(token))
        _, temporary = self.service.update_user(user["id"], reset_password=True)
        self.assertIsNotNone(temporary)
        self.assertIsNone(self.service.get_session(changed_token))

    def test_llm_profiles_are_encrypted_and_owner_scoped(self) -> None:
        alice = self.service.create_user("alice", "alice-password")
        bob = self.service.create_user("bob-user", "bobs-password")
        profile = self.service.save_profile(alice["id"], {
            "name": "Research", "provider": "custom",
            "base_url": "https://llm.example/v1", "model": "test-model",
            "api_key": "private-key-1234", "is_default": True,
        })
        self.assertEqual(profile["api_key_suffix"], "1234")
        self.assertNotIn("api_key", profile)
        self.assertEqual(
            self.service.get_profile_secret(alice["id"], profile["id"])["api_key"],
            "private-key-1234",
        )
        with self.assertRaises(KeyError):
            self.service.get_profile_secret(bob["id"], profile["id"])

        table = self.service.tables["llm_profiles"]
        with self.service.connection() as connection:
            row = connection.execute(sa.select(table)).mappings().one()
        self.assertNotIn(b"private-key", bytes(row["secret_ciphertext"]))

    def test_deepseek_profile_can_use_server_default_key(self) -> None:
        alice = self.service.create_user("alice", "alice-password")
        with patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "test-server-default-key"},
        ):
            profile = self.service.save_profile(
                alice["id"],
                {
                    "name": "Default DeepSeek",
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat",
                    "api_key": "",
                    "is_default": True,
                },
            )
        self.assertEqual(profile["api_key_suffix"], "默认")
        self.assertEqual(
            self.service.get_profile_secret(alice["id"], profile["id"])[
                "api_key"
            ],
            "test-server-default-key",
        )

    def test_custom_profile_still_requires_api_key(self) -> None:
        alice = self.service.create_user("alice", "alice-password")
        with self.assertRaisesRegex(ValueError, "API Key 不能为空"):
            self.service.save_profile(
                alice["id"],
                {
                    "name": "Custom",
                    "provider": "custom",
                    "base_url": "https://llm.example/v1",
                    "model": "custom-model",
                    "api_key": "",
                },
            )

    def test_local_master_key_is_created_with_owner_only_permissions(self) -> None:
        with patch.dict(os.environ, {"APP_MASTER_KEY": ""}):
            local_service = module.WorkspaceService(self.service.database_url)
            self.assertEqual(len(local_service._master_key()), 32)
        self.assertEqual(module.MASTER_KEY_PATH.stat().st_mode & 0o777, 0o600)

    def test_scientific_target_is_shared_but_llm_run_is_private(self) -> None:
        alice = self.service.create_user("alice", "alice-password")
        bob = self.service.create_user("bob-user", "bobs-password")
        payload = {
            "generated_at": module.iso(),
            "target": {
                "query_target": "AD Leo", "resolved_target": "AD Leo",
                "target_type": "star", "simbad": {"object_name": "AD Leo", "ra_deg": 1.0, "dec_deg": 2.0},
                "summary": "private legacy summary",
            },
            "source": "fresh",
        }
        self.service.save_target("AD Leo", payload)
        shared = self.service.load_target("ad leo")
        self.assertIsNone(shared["target"]["summary"])
        self.assertEqual(len(self.service.list_targets()), 1)

        run_id = self.service.start_llm_run(
            alice["id"], "AD Leo", "target_summary",
            {"id": "p1", "name": "Private", "provider": "custom", "base_url": "x", "model": "m", "timeout_sec": 5},
            {"target": "AD Leo"},
        )
        self.service.finish_llm_run(alice["id"], run_id, {"summary": "alice only"})
        self.assertEqual(len(self.service.list_llm_runs(alice["id"])), 1)
        run = self.service.get_llm_run(alice["id"], run_id)
        self.assertEqual(run["request"], {"target": "AD Leo"})
        self.assertEqual(run["result"]["summary"], "alice only")
        self.assertEqual(self.service.list_llm_runs(bob["id"]), [])
        with self.assertRaises(KeyError):
            self.service.get_llm_run(bob["id"], run_id)

    def test_v1_body_columns_are_removed_idempotently(self) -> None:
        self.service._engine.dispose()
        with sa.create_engine(self.service.database_url).begin() as connection:
            connection.exec_driver_sql("ALTER TABLE target_snapshots ADD COLUMN payload JSON")
            connection.exec_driver_sql("ALTER TABLE llm_runs ADD COLUMN request_payload JSON")
            connection.exec_driver_sql("DELETE FROM schema_migrations")
            connection.exec_driver_sql(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (1, CURRENT_TIMESTAMP)"
            )

        upgraded = module.WorkspaceService(self.service.database_url)
        upgraded.initialize()
        inspector = sa.inspect(upgraded._engine)
        self.assertNotIn("payload", {column["name"] for column in inspector.get_columns("target_snapshots")})
        self.assertNotIn("request_payload", {column["name"] for column in inspector.get_columns("llm_runs")})
        with upgraded.connection() as connection:
            versions = set(connection.execute(sa.select(upgraded.tables["schema_migrations"].c.version)).scalars())
        self.assertIn(module.SCHEMA_VERSION, versions)
        upgraded.initialize()

    def test_dataset_assets_and_products_are_registered_idempotently(self) -> None:
        dataset = self.root / "warehouse" / "objects" / "lightcurves" / "AD_Leo" / "dataset-1"
        dataset.mkdir(parents=True)
        product = dataset / "ad-leo-lc.fits"
        product.write_bytes(b"mock-fits-data")
        (dataset / "selected_products.json").write_text(json.dumps([{
            "productFilename": product.name,
            "dataURI": "mast:TESS/product/ad-leo-lc.fits",
            "obs_collection": "TESS",
        }]), encoding="utf-8")
        manifest = {
            "dataset_key": "dataset-1", "target": "AD Leo",
            "missions": ["TESS"], "selected_count": 1,
            "manifest": [{"Local Path": str(product), "Status": "COMPLETE"}],
        }
        (dataset / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        self.service.register_dataset(dataset, manifest)
        self.service.register_dataset(dataset, manifest)
        with self.service.connection() as connection:
            asset_count = connection.execute(sa.select(sa.func.count()).select_from(
                self.service.tables["file_assets"]
            )).scalar_one()
            product_count = connection.execute(sa.select(sa.func.count()).select_from(
                self.service.tables["products"]
            )).scalar_one()
        self.assertEqual(asset_count, 3)
        self.assertEqual(product_count, 3)

        self.service.unregister_dataset(str(dataset.resolve().relative_to(self.root.resolve())))
        with self.service.connection() as connection:
            self.assertEqual(connection.execute(sa.select(sa.func.count()).select_from(
                self.service.tables["products"]
            )).scalar_one(), 0)
            self.assertEqual(connection.execute(sa.select(sa.func.count()).select_from(
                self.service.tables["file_assets"]
            )).scalar_one(), 0)


if __name__ == "__main__":
    unittest.main()
