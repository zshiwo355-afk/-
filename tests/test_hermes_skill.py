from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "integrations"
    / "hermes"
    / "book-translator"
    / "scripts"
    / "book_translator.py"
)


def _load_client() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hermes_book_translator", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Hermes book translator client: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


client = _load_client()


class HermesBookTranslatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.hermes_home = Path(self.temp_dir.name) / "hermes-home"
        self.book_path = Path(self.temp_dir.name) / "book.md"
        self.book_path.write_text("# Chapter\n\nHello world.", encoding="utf-8")
        self.env_patcher = patch.dict(
            os.environ, {"HERMES_HOME": str(self.hermes_home)}, clear=False
        )
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def _submit(self, *extra_args: str) -> tuple[int, dict]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = client.main(
                ["submit", "--file", str(self.book_path), *extra_args]
            )
        payload = json.loads(stdout.getvalue())
        self.assertIsInstance(payload, dict, stderr.getvalue())
        return exit_code, payload

    def test_request_identity_is_stable_and_changes_with_translation_parameters(self) -> None:
        upload_responses = iter(
            [
                {"job_id": "job-a", "status": "running", "reused": False},
                {"job_id": "job-a", "status": "running", "reused": True},
                {"job_id": "job-b", "status": "running", "reused": False},
            ]
        )

        def fake_request(_api_url, method, path, **_kwargs):
            if (method, path) == ("POST", "/api/jobs/upload"):
                return next(upload_responses)
            if method == "GET" and path in {"/api/jobs/job-a", "/api/jobs/job-b"}:
                return {
                    "job_id": path.rsplit("/", 1)[-1],
                    "status": "running",
                    "runner_active": True,
                }
            self.fail(f"Unexpected request: {method} {path}")

        with patch.object(client, "_request_json", side_effect=fake_request):
            first_code, first = self._submit()
            repeated_code, repeated = self._submit()
            changed_code, changed = self._submit("--target-language", "日本語")

        self.assertEqual((first_code, repeated_code, changed_code), (0, 0, 0))
        self.assertEqual(first["client_request_id"], repeated["client_request_id"])
        self.assertNotEqual(first["client_request_id"], changed["client_request_id"])
        state = json.loads(client._state_path().read_text(encoding="utf-8"))
        self.assertEqual(state["requests"][first["client_request_id"]], "job-a")
        self.assertEqual(state["requests"][changed["client_request_id"]], "job-b")
        self.assertEqual(state["last_job_id"], "job-b")

    def test_repeated_submit_reuses_running_job_without_starting_it_again(self) -> None:
        calls: list[tuple[str, str]] = []
        upload_count = 0
        status_count = 0

        def fake_request(_api_url, method, path, **_kwargs):
            nonlocal status_count, upload_count
            calls.append((method, path))
            if path == "/api/jobs/upload":
                upload_count += 1
                if upload_count == 1:
                    return {"job_id": "job-one", "status": "pending", "reused": False}
                return {"job_id": "job-one", "status": "running", "reused": True}
            if (method, path) == ("GET", "/api/jobs/job-one"):
                status_count += 1
                if status_count == 1:
                    return {
                        "job_id": "job-one",
                        "status": "pending",
                        "runner_active": False,
                    }
                return {
                    "job_id": "job-one",
                    "status": "running",
                    "runner_active": True,
                }
            if path == "/api/jobs/job-one/start":
                return {"ok": True, "job_id": "job-one", "status": "running"}
            self.fail(f"Unexpected request: {method} {path}")

        with patch.object(client, "_request_json", side_effect=fake_request):
            first_code, first = self._submit()
            repeated_code, repeated = self._submit()

        self.assertEqual((first_code, repeated_code), (0, 0))
        self.assertEqual(first["action"], "start")
        self.assertEqual(repeated["action"], "reuse")
        self.assertFalse(first["reused"])
        self.assertTrue(repeated["reused"])
        self.assertEqual(first["client_request_id"], repeated["client_request_id"])
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-one/start")),
            1,
        )
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-one/resume")),
            0,
        )
        self.assertEqual(calls.count(("GET", "/api/jobs/job-one")), 3)
        state = json.loads(client._state_path().read_text(encoding="utf-8"))
        self.assertEqual(state["last_job_id"], "job-one")
        self.assertEqual(
            state["requests"][first["client_request_id"]],
            "job-one",
        )

    def test_submit_resumes_a_running_job_without_an_active_runner(self) -> None:
        calls: list[tuple[str, str]] = []
        status_count = 0

        def fake_request(_api_url, method, path, **_kwargs):
            nonlocal status_count
            calls.append((method, path))
            if (method, path) == ("POST", "/api/jobs/upload"):
                return {"job_id": "job-stale", "status": "running", "reused": True}
            if (method, path) == ("GET", "/api/jobs/job-stale"):
                status_count += 1
                return {
                    "job_id": "job-stale",
                    "status": "running",
                    "runner_active": status_count > 1,
                }
            if (method, path) == ("POST", "/api/jobs/job-stale/resume"):
                return {"ok": True, "job_id": "job-stale", "status": "running"}
            self.fail(f"Unexpected request: {method} {path}")

        with patch.object(client, "_request_json", side_effect=fake_request):
            exit_code, result = self._submit()

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["action"], "resume")
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-stale/resume")),
            1,
        )
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-stale/start")),
            0,
        )
        self.assertEqual(calls.count(("GET", "/api/jobs/job-stale")), 2)

    def test_submit_resumes_a_pausing_job_without_an_active_runner(self) -> None:
        calls: list[tuple[str, str]] = []
        status_count = 0

        def fake_request(_api_url, method, path, **_kwargs):
            nonlocal status_count
            calls.append((method, path))
            if (method, path) == ("POST", "/api/jobs/upload"):
                return {"job_id": "job-pausing", "status": "pausing", "reused": True}
            if (method, path) == ("GET", "/api/jobs/job-pausing"):
                status_count += 1
                return {
                    "job_id": "job-pausing",
                    "status": "pausing" if status_count == 1 else "running",
                    "runner_active": status_count > 1,
                }
            if (method, path) == ("POST", "/api/jobs/job-pausing/resume"):
                return {"ok": True, "job_id": "job-pausing", "status": "running"}
            self.fail(f"Unexpected request: {method} {path}")

        with patch.object(client, "_request_json", side_effect=fake_request):
            exit_code, result = self._submit()

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["action"], "resume")
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-pausing/resume")),
            1,
        )
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-pausing/start")),
            0,
        )

    def test_submit_reuses_a_pausing_job_with_an_active_runner(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_request(_api_url, method, path, **_kwargs):
            calls.append((method, path))
            if (method, path) == ("POST", "/api/jobs/upload"):
                return {"job_id": "job-pausing", "status": "pausing", "reused": True}
            if (method, path) == ("GET", "/api/jobs/job-pausing"):
                return {
                    "job_id": "job-pausing",
                    "status": "pausing",
                    "runner_active": True,
                }
            self.fail(f"Unexpected request: {method} {path}")

        with patch.object(client, "_request_json", side_effect=fake_request):
            exit_code, result = self._submit()

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["action"], "reuse")
        self.assertEqual(calls.count(("GET", "/api/jobs/job-pausing")), 1)
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-pausing/resume")),
            0,
        )
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-pausing/start")),
            0,
        )

    def test_submit_rebuilds_a_completed_job_with_a_missing_result(self) -> None:
        calls: list[tuple[str, str]] = []
        status_count = 0

        def fake_request(_api_url, method, path, **_kwargs):
            nonlocal status_count
            calls.append((method, path))
            if (method, path) == ("POST", "/api/jobs/upload"):
                return {"job_id": "job-complete", "status": "completed", "reused": True}
            if (method, path) == ("GET", "/api/jobs/job-complete"):
                status_count += 1
                return {
                    "job_id": "job-complete",
                    "status": "completed",
                    "result_ready": status_count > 1,
                }
            if (method, path) == ("POST", "/api/jobs/job-complete/resume"):
                return {"ok": True, "job_id": "job-complete", "status": "completed"}
            self.fail(f"Unexpected request: {method} {path}")

        with patch.object(client, "_request_json", side_effect=fake_request):
            exit_code, result = self._submit()

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["action"], "resume")
        self.assertTrue(result["result_ready"])
        self.assertEqual(calls.count(("GET", "/api/jobs/job-complete")), 2)
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-complete/resume")),
            1,
        )
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-complete/start")),
            0,
        )

    def test_submit_reuses_a_completed_job_with_a_ready_result(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_request(_api_url, method, path, **_kwargs):
            calls.append((method, path))
            if (method, path) == ("POST", "/api/jobs/upload"):
                return {"job_id": "job-complete", "status": "completed", "reused": True}
            if (method, path) == ("GET", "/api/jobs/job-complete"):
                return {
                    "job_id": "job-complete",
                    "status": "completed",
                    "result_ready": True,
                }
            self.fail(f"Unexpected request: {method} {path}")

        with patch.object(client, "_request_json", side_effect=fake_request):
            exit_code, result = self._submit()

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["action"], "reuse")
        self.assertTrue(result["result_ready"])
        self.assertEqual(calls.count(("GET", "/api/jobs/job-complete")), 1)
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-complete/resume")),
            0,
        )
        self.assertEqual(
            calls.count(("POST", "/api/jobs/job-complete/start")),
            0,
        )


if __name__ == "__main__":
    unittest.main()
