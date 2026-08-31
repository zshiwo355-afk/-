from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend import app as app_module
from backend.translator.exporter import export_outputs
from backend.translator.pipeline import (
    EventBroker,
    JobAlreadyRunningError,
    TranslationPipeline,
)
from backend.translator.storage import FileStorage


class AgentApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = FileStorage(Path(self.temp_dir.name))
        self.pipeline = TranslationPipeline(storage=self.storage, broker=EventBroker())
        self.patchers = [
            patch.object(app_module, "storage", self.storage),
            patch.object(app_module, "pipeline", self.pipeline),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        self.client.close()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def _upload(self, content: bytes = b"# Chapter\n\nHello world.", **fields: str):
        return self.client.post(
            "/api/jobs/upload",
            files={"file": ("book.md", content, "text/markdown")},
            data=fields,
        )

    def _mark_running(self, job_id: str) -> None:
        job = asyncio.run(self.pipeline.get_job(job_id))
        job.status = "running"
        asyncio.run(self.storage.save_job(job))

    def _export_completed_outputs(self, job_id: str) -> None:
        job = asyncio.run(self.pipeline.get_job(job_id))
        job.status = "completed"
        asyncio.run(self.storage.save_job(job))
        segments = asyncio.run(self.pipeline.get_segments(job_id))
        for segment in segments:
            segment.status = "success"
            segment.translated_text = "你好，世界。"
        asyncio.run(self.storage.save_segments(job_id, segments))
        chunks = asyncio.run(self.storage.load_chunks(job_id))
        asyncio.run(export_outputs(self.storage, job, segments, chunks))

    def test_health_exposes_agent_capabilities_without_model_credentials(self) -> None:
        config = SimpleNamespace(
            tokenhub_api_key="unit-test-secret",
            tokenhub_base_url="https://private-model.invalid/v1",
            model="private-model",
        )

        with patch.object(app_module, "reload_config", return_value=config):
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["configured"])
        capabilities = payload["capabilities"]
        self.assertEqual(capabilities["file_types"], [".txt", ".md"])
        self.assertIn("pause", capabilities["control_actions"])
        self.assertIn("bilingual.md", capabilities["output_types"])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("unit-test-secret", serialized)
        self.assertNotIn("private-model.invalid", serialized)
        self.assertNotIn("api_key", payload)
        self.assertNotIn("base_url", payload)

    def test_upload_reuses_an_identical_client_request(self) -> None:
        request_id = f"request-{uuid4().hex}"

        first = self._upload(client_request_id=request_id, target_language="简体中文")
        second = self._upload(client_request_id=request_id, target_language="简体中文")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertFalse(first.json()["reused"])
        self.assertTrue(second.json()["reused"])
        self.assertEqual(first.json()["job_id"], second.json()["job_id"])

    def test_upload_rejects_reusing_a_request_id_for_different_content(self) -> None:
        request_id = f"request-{uuid4().hex}"
        first = self._upload(b"First version", client_request_id=request_id)

        conflict = self._upload(b"Different version", client_request_id=request_id)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["detail"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_upload_rejects_an_empty_document(self) -> None:
        response = self._upload(b" \n\t\n")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"]["code"], "EMPTY_DOCUMENT")

    def test_completed_job_reports_a_downloadable_output_manifest(self) -> None:
        uploaded = self._upload()
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        job_id = uploaded.json()["job_id"]
        self._export_completed_outputs(job_id)

        response = self.client.get(f"/api/jobs/{job_id}")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["result_ready"])
        outputs = payload["outputs"]
        self.assertEqual(
            {item["type"] for item in outputs},
            {"translated.txt", "translated.md", "bilingual.txt", "bilingual.md"},
        )
        for item in outputs:
            self.assertTrue(item["filename"])
            self.assertGreater(item["size_bytes"], 0)
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                item["download_url"],
                f"/api/jobs/{job_id}/download/{item['type']}",
            )

    def test_resume_rebuilds_outputs_when_all_segments_are_already_done(self) -> None:
        uploaded = self._upload()
        job_id = uploaded.json()["job_id"]
        job = asyncio.run(self.pipeline.get_job(job_id))
        job.status = "paused"
        asyncio.run(self.storage.save_job(job))
        segments = asyncio.run(self.pipeline.get_segments(job_id))
        for segment in segments:
            segment.status = "success"
            segment.translated_text = "已经完成。"
        asyncio.run(self.storage.save_segments(job_id, segments))

        resumed = asyncio.run(self.pipeline.resume_job(job_id))
        response = self.client.get(f"/api/jobs/{job_id}")

        self.assertEqual(resumed.status, "completed")
        self.assertTrue(response.json()["result_ready"])
        self.assertEqual(len(response.json()["outputs"]), 4)

    def test_resume_rebuilds_a_missing_manifest_for_a_completed_job(self) -> None:
        uploaded = self._upload()
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        job_id = uploaded.json()["job_id"]
        self._export_completed_outputs(job_id)
        asyncio.run(self.storage.clear_result_manifest(job_id))

        before_resume = self.client.get(f"/api/jobs/{job_id}")
        resumed = self.client.post(f"/api/jobs/{job_id}/resume")
        after_resume = self.client.get(f"/api/jobs/{job_id}")

        self.assertEqual(before_resume.status_code, 200, before_resume.text)
        self.assertFalse(before_resume.json()["result_ready"])
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(resumed.json()["status"], "completed")
        self.assertEqual(after_resume.status_code, 200, after_resume.text)
        self.assertTrue(after_resume.json()["result_ready"])
        self.assertEqual(len(after_resume.json()["outputs"]), 4)

    def test_running_job_hides_and_refuses_stale_outputs(self) -> None:
        uploaded = self._upload()
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        job_id = uploaded.json()["job_id"]
        self._export_completed_outputs(job_id)
        self._mark_running(job_id)

        status_response = self.client.get(f"/api/jobs/{job_id}")
        download_response = self.client.get(
            f"/api/jobs/{job_id}/download/bilingual.md"
        )

        self.assertEqual(status_response.status_code, 200, status_response.text)
        self.assertFalse(status_response.json()["result_ready"])
        self.assertEqual(status_response.json()["outputs"], [])
        self.assertEqual(download_response.status_code, 404, download_response.text)

    def test_concurrent_start_creates_only_one_background_runner(self) -> None:
        async def scenario() -> None:
            source_path = Path(self.temp_dir.name) / "book.md"
            source_path.write_text("# Chapter\n\nHello world.", encoding="utf-8")
            job = await self.pipeline.create_job_from_file(source_path, file_name="book.md")
            release_runner = asyncio.Event()
            created_tasks: list[asyncio.Task[bool]] = []
            create_count = 0
            original_load_segments = self.storage.load_segments

            async def slow_load_segments(job_id: str):
                await asyncio.sleep(0.02)
                return await original_load_segments(job_id)

            def fake_create_background_task(job_id: str) -> None:
                nonlocal create_count
                create_count += 1
                task = asyncio.create_task(release_runner.wait())
                created_tasks.append(task)
                self.pipeline.tasks[job_id] = task

            configured = SimpleNamespace(tokenhub_api_key="configured", model="test-model")
            try:
                with (
                    patch("backend.translator.pipeline.reload_config", return_value=configured),
                    patch.object(self.storage, "load_segments", side_effect=slow_load_segments),
                    patch.object(
                        self.pipeline,
                        "_create_background_task",
                        side_effect=fake_create_background_task,
                    ),
                ):
                    await asyncio.gather(
                        self.pipeline.start_job(job.job_id),
                        self.pipeline.start_job(job.job_id),
                    )

                self.assertEqual(create_count, 1)
            finally:
                release_runner.set()
                if created_tasks:
                    await asyncio.gather(*created_tasks)
                self.pipeline.tasks.clear()

        asyncio.run(scenario())

    def test_pause_accepts_agent_requests_and_keeps_browser_click_compatibility(self) -> None:
        agent_job_id = self._upload().json()["job_id"]
        browser_job_id = self._upload(b"A second book").json()["job_id"]
        self._mark_running(agent_job_id)
        self._mark_running(browser_job_id)

        agent_response = self.client.post(
            f"/api/jobs/{agent_job_id}/pause",
            json={"reason": "agent_request"},
        )
        browser_response = self.client.post(
            f"/api/jobs/{browser_job_id}/pause",
            json={"reason": "user_click_pause"},
            headers={"X-Manual-User-Action": "true"},
        )

        self.assertEqual(agent_response.status_code, 200, agent_response.text)
        self.assertEqual(agent_response.json()["status"], "pausing")
        self.assertEqual(browser_response.status_code, 200, browser_response.text)
        self.assertEqual(browser_response.json()["status"], "pausing")

    def test_missing_job_controls_and_download_share_a_machine_readable_404(self) -> None:
        missing_job_id = "job-does-not-exist"
        configured = SimpleNamespace(tokenhub_api_key="configured", model="test-model")
        isolated_client = TestClient(app_module.app, raise_server_exceptions=False)
        requests = [
            ("start", lambda: isolated_client.post(f"/api/jobs/{missing_job_id}/start")),
            ("resume", lambda: isolated_client.post(f"/api/jobs/{missing_job_id}/resume")),
            (
                "pause",
                lambda: isolated_client.post(
                    f"/api/jobs/{missing_job_id}/pause",
                    json={"reason": "agent_request"},
                ),
            ),
            ("cancel", lambda: isolated_client.post(f"/api/jobs/{missing_job_id}/cancel")),
            (
                "download",
                lambda: isolated_client.get(
                    f"/api/jobs/{missing_job_id}/download/bilingual.md"
                ),
            ),
        ]
        try:
            with patch.object(app_module, "reload_config", return_value=configured):
                for action, request in requests:
                    with self.subTest(action=action):
                        response = request()
                        self.assertEqual(response.status_code, 404, response.text)
                        self.assertEqual(
                            response.json()["detail"]["code"],
                            "JOB_NOT_FOUND",
                        )
        finally:
            isolated_client.close()

    def test_repair_stuck_rejects_an_active_runner_without_repairing(self) -> None:
        uploaded = self._upload()
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        job_id = uploaded.json()["job_id"]
        self._mark_running(job_id)
        job = asyncio.run(self.pipeline.get_job(job_id))

        with (
            patch.object(self.pipeline, "has_active_task", return_value=True),
            patch.object(
                self.pipeline,
                "repair_stuck_job",
                new=AsyncMock(return_value=job),
            ) as repair,
        ):
            response = self.client.post(f"/api/jobs/{job_id}/repair-stuck")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "JOB_ALREADY_RUNNING")
        repair.assert_not_awaited()

    def test_pipeline_repair_stuck_preserves_state_while_runner_is_active(self) -> None:
        async def scenario() -> None:
            source_path = Path(self.temp_dir.name) / "active-book.md"
            source_path.write_text("# Chapter\n\nHello world.", encoding="utf-8")
            job = await self.pipeline.create_job_from_file(
                source_path,
                file_name="active-book.md",
            )
            job.status = "running"
            segments = await self.pipeline.get_segments(job.job_id)
            segments[0].status = "running"
            segments[0].error = "in progress"
            await self.storage.save_job(job)
            await self.storage.save_segments(job.job_id, segments)
            job_before = job.model_dump()
            segments_before = [segment.model_dump() for segment in segments]

            release_runner = asyncio.Event()
            active_task = asyncio.create_task(release_runner.wait())
            self.pipeline.tasks[job.job_id] = active_task
            try:
                with self.assertRaises(JobAlreadyRunningError):
                    await self.pipeline.repair_stuck_job(job.job_id)

                job_after = await self.pipeline.get_job(job.job_id)
                segments_after = await self.pipeline.get_segments(job.job_id)
                self.assertEqual(job_after.model_dump(), job_before)
                self.assertEqual(
                    [segment.model_dump() for segment in segments_after],
                    segments_before,
                )
            finally:
                release_runner.set()
                await active_task
                self.pipeline.tasks.clear()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
