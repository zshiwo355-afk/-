from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from backend import config
from backend.app import ApiSettingsPayload, get_api_settings, pipeline, update_api_settings
from backend.translator.validator import JobConfigSnapshot


class ApiSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base_dir = Path(self.temp_dir.name)
        self.example_path = base_dir / "config.example.json"
        self.local_path = base_dir / "config.local.json"
        self.env_path = base_dir / ".env"
        self.example_path.write_text(
            json.dumps(
                {
                    "tokenhub_api_key": "",
                    "tokenhub_base_url": "https://example.invalid/v1",
                    "model": "hy-mt2-pro",
                }
            ),
            encoding="utf-8",
        )
        self.env_path.write_text(
            "TOKENHUB_API_KEY=env-key\nTOKENHUB_BASE_URL=https://env.invalid/v1\n",
            encoding="utf-8",
        )
        self.patchers = [
            patch.object(config, "CONFIG_EXAMPLE_PATH", self.example_path),
            patch.object(config, "CONFIG_LOCAL_PATH", self.local_path),
            patch.object(config, "ENV_FILE_PATHS", (self.env_path,)),
            patch.object(
                config,
                "PROCESS_ENV",
                {
                    "TOKENHUB_API_KEY": "process-key",
                    "TOKENHUB_BASE_URL": "https://process.invalid/v1",
                    "TOKENHUB_MODEL": "process-model",
                },
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
        config.load_config.cache_clear()

    def tearDown(self) -> None:
        config.load_config.cache_clear()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_put_persists_local_settings_and_never_returns_key(self) -> None:
        response = asyncio.run(
            update_api_settings(
                ApiSettingsPayload(
                    base_url="https://local.invalid/v1",
                    api_key="local-secret",
                    model="  custom-model  ",
                )
            )
        )

        self.assertEqual(
            response,
            {
                "base_url": "https://local.invalid/v1",
                "model": "custom-model",
                "has_api_key": True,
            },
        )
        self.assertNotIn("local-secret", str(response))
        self.assertEqual(config.reload_config().tokenhub_api_key, "local-secret")
        self.assertEqual(config.reload_config().tokenhub_base_url, "https://local.invalid/v1")
        self.assertEqual(config.reload_config().model, "custom-model")
        saved = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["tokenhub_api_key"], "local-secret")
        self.assertEqual(saved["model"], "custom-model")

    def test_blank_key_preserves_existing_key(self) -> None:
        self.local_path.write_text(
            json.dumps(
                {
                    "tokenhub_api_key": "legacy-local-key",
                    "tokenhub_base_url": "https://legacy.invalid/v1",
                }
            ),
            encoding="utf-8",
        )
        config.load_config.cache_clear()

        response = asyncio.run(
            update_api_settings(
                ApiSettingsPayload(
                    base_url="http://127.0.0.1:9000/v1",
                    api_key="  ",
                    model="next-model",
                )
            )
        )

        self.assertTrue(response["has_api_key"])
        self.assertEqual(config.reload_config().tokenhub_api_key, "process-key")
        self.assertEqual(config.reload_config().tokenhub_base_url, "http://127.0.0.1:9000/v1")
        self.assertEqual(config.reload_config().model, "next-model")
        self.assertEqual(json.loads(self.local_path.read_text(encoding="utf-8"))["tokenhub_api_key"], "process-key")

    def test_invalid_url_is_rejected_without_writing_file(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                update_api_settings(
                    ApiSettingsPayload(base_url="file:///tmp/model", api_key="secret", model="test-model")
                )
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(self.local_path.exists())

    def test_get_returns_only_safe_fields(self) -> None:
        response = asyncio.run(get_api_settings())

        self.assertEqual(
            response,
            {
                "base_url": "https://process.invalid/v1",
                "model": "process-model",
                "has_api_key": True,
            },
        )
        self.assertNotIn("process-key", str(response))

    def test_blank_model_is_rejected_without_writing_file(self) -> None:
        with self.assertRaises(ValidationError):
            ApiSettingsPayload(base_url="https://local.invalid/v1", api_key="secret", model="   ")

        self.assertFalse(self.local_path.exists())

    def test_first_save_requires_an_api_key(self) -> None:
        self.env_path.write_text("", encoding="utf-8")
        with patch.object(config, "PROCESS_ENV", {}):
            config.load_config.cache_clear()
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    update_api_settings(
                        ApiSettingsPayload(
                            base_url="https://local.invalid/v1",
                            api_key="",
                            model="test-model",
                        )
                    )
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(self.local_path.exists())

    def test_old_saved_settings_without_model_keep_effective_model(self) -> None:
        self.local_path.write_text(
            json.dumps(
                {
                    "tokenhub_api_key": "local-key",
                    "tokenhub_base_url": "https://local.invalid/v1",
                    config.LOCAL_API_SETTINGS_FLAG: True,
                }
            ),
            encoding="utf-8",
        )

        loaded = config.reload_config()

        self.assertEqual(loaded.tokenhub_base_url, "https://local.invalid/v1")
        self.assertEqual(loaded.tokenhub_api_key, "local-key")
        self.assertEqual(loaded.model, "process-model")

    def test_existing_job_uses_the_current_connection_as_one_set(self) -> None:
        current = config.AppConfig(
            tokenhub_api_key="new-key",
            tokenhub_base_url="https://new.invalid/v1",
            model="new-model",
        )
        job = SimpleNamespace(
            target_language="简体中文",
            config=JobConfigSnapshot(
                model="old-model",
                temperature=0.1,
                stream=False,
                chunk_size_chars=3500,
                max_retries=3,
                target_language="简体中文",
            ),
        )

        with (
            patch("backend.translator.pipeline.reload_config", return_value=current),
            patch(
                "backend.translator.pipeline.build_runtime_config",
                side_effect=lambda overrides: config.AppConfig(**overrides),
            ),
        ):
            client = pipeline._build_client(job)

        self.assertEqual(job.config.model, "new-model")
        self.assertEqual(client.config.model, "new-model")
        self.assertEqual(client.config.tokenhub_base_url, "https://new.invalid/v1")
        self.assertEqual(client.config.tokenhub_api_key, "new-key")


if __name__ == "__main__":
    unittest.main()
