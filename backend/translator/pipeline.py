from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.config import build_runtime_config, reload_config
from backend.translator.chunker import build_chunks
from backend.translator.context_builder import build_messages
from backend.translator.exporter import export_outputs
from backend.translator.hy_mt2_client import HyMT2Client
from backend.translator.storage import FileStorage
from backend.translator.text_loader import load_text_file
from backend.translator.segmenter import segment_document
from backend.translator.validator import (
    AUTH_FAILURE_MESSAGE,
    ChunkRecord,
    JobConfigSnapshot,
    JobRecord,
    LogEntry,
    SegmentRecord,
    TranslationParseResult,
    TranslationAuthError,
    utc_now_iso,
)


SEGMENT_TRANSLATION_RE = re.compile(
    r'<segment\s+id="([^"]+)">\s*(.*?)\s*</segment>', re.DOTALL | re.IGNORECASE
)


class EventBroker:
    def __init__(self) -> None:
        self.subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers[job_id].append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if job_id not in self.subscribers:
            return
        self.subscribers[job_id] = [item for item in self.subscribers[job_id] if item is not queue]
        if not self.subscribers[job_id]:
            self.subscribers.pop(job_id, None)

    async def publish(self, job_id: str, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, "data": data, "timestamp": utc_now_iso()}
        for queue in self.subscribers.get(job_id, []):
            await queue.put(payload)


class TranslationPipeline:
    def __init__(self, storage: FileStorage, broker: EventBroker):
        self.storage = storage
        self.broker = broker
        self.tasks: dict[str, asyncio.Task[None]] = {}

    async def create_job_from_file(
        self,
        source_path: str | Path,
        file_name: str,
        target_language: str | None = None,
        translation_mode: str = "忠实翻译",
        stream: bool | None = None,
        chunk_size_chars: int | None = None,
    ) -> JobRecord:
        source_path = str(Path(source_path).resolve())
        config = build_runtime_config(
            {
                "default_target_language": target_language,
                "stream": stream,
                "chunk_size_chars": chunk_size_chars,
            }
        )
        text = load_text_file(source_path)
        segment_limit = max(800, min(2200, config.chunk_size_chars - 800))
        segments = segment_document(text, max_segment_chars=segment_limit)
        chunks = build_chunks(segments, config.chunk_size_chars)
        avg_segment_chars = round(sum(len(segment.source_text) for segment in segments) / max(len(segments), 1), 2)
        max_segment_chars_value = max((len(segment.source_text) for segment in segments), default=0)

        job = JobRecord(
            job_id=f"job_{uuid4().hex[:12]}",
            file_name=file_name,
            source_path=source_path,
            target_language=target_language or config.default_target_language,
            total_segments=len(segments),
            total_chunks=len(chunks),
            avg_segment_chars=avg_segment_chars,
            max_segment_chars=max_segment_chars_value,
            config=JobConfigSnapshot(
                model=config.model,
                temperature=config.temperature,
                stream=config.stream,
                chunk_size_chars=config.chunk_size_chars,
                max_retries=config.max_retries,
                target_language=target_language or config.default_target_language,
                translation_mode=translation_mode,
            ),
        )
        await self.storage.create_job(job, segments, chunks)
        return job

    async def create_job_from_upload(
        self,
        file_name: str,
        content: bytes,
        target_language: str | None = None,
        translation_mode: str = "忠实翻译",
        stream: bool | None = None,
        chunk_size_chars: int | None = None,
    ) -> JobRecord:
        temp_job_id = f"upload_{uuid4().hex[:12]}"
        upload_path = await self.storage.save_uploaded_file(file_name, content, temp_job_id)
        return await self.create_job_from_file(
            upload_path,
            file_name=file_name,
            target_language=target_language,
            translation_mode=translation_mode,
            stream=stream,
            chunk_size_chars=chunk_size_chars,
        )

    async def get_job(self, job_id: str) -> JobRecord:
        return await self.storage.load_job(job_id)

    async def get_segments(self, job_id: str) -> list[SegmentRecord]:
        return await self.storage.load_segments(job_id)

    async def request_pause(self, job_id: str) -> JobRecord:
        job = await self.storage.load_job(job_id)
        if job.status in {"running", "pausing"}:
            job.status = "pausing"
            job.updated_at = utc_now_iso()
            await self.storage.save_job(job)
            await self.broker.publish(job_id, "job_pausing", {"job_id": job_id, "status": job.status})
        return job

    async def request_cancel(self, job_id: str) -> JobRecord:
        job = await self.storage.load_job(job_id)
        if job.status in {"pending", "paused", "running", "pausing", "failed"}:
            job.status = "cancelled"
            job.updated_at = utc_now_iso()
            await self.storage.save_job(job)
            await self.broker.publish(job_id, "job_cancelled", {"job_id": job_id, "status": job.status})
        return job

    async def start_job(self, job_id: str) -> JobRecord:
        job = await self.storage.load_job(job_id)
        if job.status in {"completed", "cancelled"}:
            return job
        if task := self.tasks.get(job_id):
            if not task.done():
                return job
        segments = await self.storage.load_segments(job_id)
        chunks = await self.storage.load_chunks(job_id)
        changed = self.normalize_interrupted_segments(segments, chunks)
        if changed:
            await self.storage.save_segments(job_id, segments)
            for chunk in chunks:
                await self.storage.save_chunk(job_id, chunk)
        job.status = "running"
        job.last_error = ""
        await self._recompute_job_progress(job, segments)
        job.updated_at = utc_now_iso()
        await self.storage.save_job(job)
        self.tasks[job_id] = asyncio.create_task(self._run_job(job_id))
        return job

    async def resume_job(self, job_id: str) -> JobRecord:
        job = await self.storage.load_job(job_id)
        if job.status == "completed":
            return job
        if job.status == "cancelled":
            return job
        segments = await self.storage.load_segments(job_id)
        chunks = await self.storage.load_chunks(job_id)
        if all(segment.status == "success" for segment in segments):
            job.status = "completed"
            await self.storage.save_job(job)
            return job
        self.normalize_interrupted_segments(segments, chunks)
        await self.storage.save_segments(job_id, segments)
        for chunk in chunks:
            await self.storage.save_chunk(job_id, chunk)
        if job.status not in {"paused", "pausing", "failed", "pending", "running"}:
            return job
        return await self.start_job(job_id)

    def normalize_interrupted_segments(self, segments: list[SegmentRecord], chunks: list[ChunkRecord]) -> bool:
        changed = False
        segment_map = {segment.segment_id: segment for segment in segments}
        for segment in segments:
            if segment.status == "running":
                segment.status = "pending"
                changed = True

        for chunk in chunks:
            chunk_segments = [segment_map[segment_id] for segment_id in chunk.segment_ids if segment_id in segment_map]
            if chunk.status == "running":
                chunk.status = "pending"
                changed = True
            if chunk_segments and all(segment.status == "success" for segment in chunk_segments):
                if chunk.status != "completed":
                    chunk.status = "completed"
                    changed = True
            elif chunk.status == "completed":
                chunk.status = "pending"
                changed = True
        return changed

    def _build_client(self, job: JobRecord) -> HyMT2Client:
        config = reload_config()
        runtime_config = build_runtime_config(
            {
                "model": job.config.model,
                "temperature": job.config.temperature,
                "stream": job.config.stream,
                "chunk_size_chars": job.config.chunk_size_chars,
                "max_retries": job.config.max_retries,
                "default_target_language": job.target_language,
                "tokenhub_api_key": config.tokenhub_api_key,
                "tokenhub_base_url": config.tokenhub_base_url,
            }
        )
        return HyMT2Client(runtime_config)

    def _parse_translation_response(
        self,
        response_text: str,
        segment_ids: list[str],
    ) -> TranslationParseResult:
        translation_match = re.search(r"<translation>(.*?)</translation>", response_text, re.DOTALL | re.IGNORECASE)
        summary_match = re.search(r"<summary>(.*?)</summary>", response_text, re.DOTALL | re.IGNORECASE)
        terms_match = re.search(r"<terms>(.*?)</terms>", response_text, re.DOTALL | re.IGNORECASE)

        translations: dict[str, str] = {}
        if translation_match:
            for segment_id, translated_text in SEGMENT_TRANSLATION_RE.findall(translation_match.group(1)):
                translations[segment_id] = translated_text.strip()

        terms: dict[str, str] = {}
        if terms_match:
            for line in terms_match.group(1).splitlines():
                if "=" not in line:
                    continue
                source, target = line.split("=", 1)
                source = source.strip()
                target = target.strip()
                if source and target:
                    terms[source] = target

        missing_segment_ids = [segment_id for segment_id in segment_ids if not translations.get(segment_id)]
        return TranslationParseResult(
            translations=translations,
            summary=(summary_match.group(1).strip() if summary_match else ""),
            terms=terms,
            missing_segment_ids=missing_segment_ids,
        )

    def _extract_stream_translations(
        self,
        stream_buffer: str,
        segment_ids: list[str],
    ) -> dict[str, str]:
        translation_start = stream_buffer.find("<translation>")
        if translation_start == -1:
            return {}

        content = stream_buffer[translation_start + len("<translation>") :]
        previews: dict[str, str] = {}
        for index, segment_id in enumerate(segment_ids):
            start_token = f'<segment id="{segment_id}">'
            start_index = content.find(start_token)
            if start_index == -1:
                continue
            start_index += len(start_token)

            end_index = len(content)
            closing_index = content.find("</segment>", start_index)
            if closing_index != -1:
                end_index = min(end_index, closing_index)

            for next_segment_id in segment_ids[index + 1 :]:
                next_token_index = content.find(f'<segment id="{next_segment_id}">', start_index)
                if next_token_index != -1:
                    end_index = min(end_index, next_token_index)
                    break

            preview = content[start_index:end_index].strip()
            if preview:
                previews[segment_id] = preview
        return previews

    async def _emit_job_snapshot(self, job: JobRecord) -> None:
        await self.broker.publish(job.job_id, "job_updated", job.model_dump())

    async def _recompute_job_progress(self, job: JobRecord, segments: list[SegmentRecord]) -> JobRecord:
        job.completed_segments = sum(1 for segment in segments if segment.status == "success")
        job.failed_segments = sum(1 for segment in segments if segment.status == "failed")
        job.updated_at = utc_now_iso()
        return job

    async def _fail_job_for_auth_error(
        self,
        job: JobRecord,
        chunk: ChunkRecord,
        source_segments: list[SegmentRecord],
        segments: list[SegmentRecord],
        chunks: list[ChunkRecord],
        raw_error: str,
    ) -> None:
        chunk.status = "failed"
        chunk.error = AUTH_FAILURE_MESSAGE
        chunk.completed_at = utc_now_iso()
        for segment in source_segments:
            if segment.status != "success":
                segment.status = "failed"
                segment.error = AUTH_FAILURE_MESSAGE

        job.status = "failed"
        job.last_error = AUTH_FAILURE_MESSAGE
        job.current_segment_id = source_segments[0].segment_id if source_segments else job.current_segment_id
        job.current_chapter = chunk.chapter_title
        await self._recompute_job_progress(job, segments)

        await self.storage.save_chunk(job.job_id, chunk)
        await self.storage.save_segments(job.job_id, segments)
        await self.storage.save_job(job)
        await self.storage.append_log(
            job.job_id,
            LogEntry(
                event="job_failed_auth",
                payload={
                    "chunk_id": chunk.chunk_id,
                    "segment_ids": chunk.segment_ids,
                    "error": raw_error,
                    "message": AUTH_FAILURE_MESSAGE,
                },
            ),
        )
        await export_outputs(self.storage, job, segments, chunks)
        await self.broker.publish(
            job.job_id,
            "chunk_failed",
            {
                "job_id": job.job_id,
                "chunk_id": chunk.chunk_id,
                "error": AUTH_FAILURE_MESSAGE,
                "segment_ids": chunk.segment_ids,
            },
        )
        await self.broker.publish(job.job_id, "job_failed", job.model_dump())

    async def _run_job(self, job_id: str) -> None:
        job = await self.storage.load_job(job_id)
        segments = await self.storage.load_segments(job_id)
        chunks = await self.storage.load_chunks(job_id)
        client = self._build_client(job)
        segment_map = {segment.segment_id: segment for segment in segments}
        loop = asyncio.get_running_loop()

        await self.broker.publish(
            job_id,
            "job_started",
            {"job_id": job_id, "status": "running", "completed_segments": job.completed_segments},
        )

        try:
            for chunk in chunks:
                latest_job = await self.storage.load_job(job_id)
                if latest_job.status == "cancelled":
                    break
                if latest_job.status == "pausing":
                    latest_job.status = "paused"
                    latest_job.updated_at = utc_now_iso()
                    await self.storage.save_job(latest_job)
                    await export_outputs(self.storage, latest_job, segments, chunks)
                    await self.broker.publish(job_id, "job_paused", latest_job.model_dump())
                    return

                source_segments = [segment_map[segment_id] for segment_id in chunk.segment_ids if segment_id in segment_map]
                pending_segments = [segment for segment in source_segments if segment.status != "success"]

                if chunk.status == "completed" or not pending_segments:
                    if source_segments and chunk.status != "completed":
                        chunk.status = "completed"
                        await self.storage.save_chunk(job_id, chunk)
                    continue

                for segment in pending_segments:
                    if segment.status != "success":
                        segment.status = "running"
                        segment.error = ""

                chunk.status = "running"
                chunk.started_at = utc_now_iso()
                chunk.error = ""
                job.status = "running"
                job.current_segment_id = pending_segments[0].segment_id
                job.current_chapter = chunk.chapter_title
                await self.storage.save_segments(job_id, segments)
                await self.storage.save_chunk(job_id, chunk)
                await self._recompute_job_progress(job, segments)
                await self.storage.save_job(job)

                await self.broker.publish(
                    job_id,
                    "chunk_started",
                    {
                        "job_id": job_id,
                        "chunk_id": chunk.chunk_id,
                        "segment_ids": chunk.segment_ids,
                        "current_segment_id": pending_segments[0].segment_id,
                        "chapter_title": chunk.chapter_title,
                    },
                )

                messages = build_messages(
                    job=job,
                    chunk=chunk,
                    source_segments=pending_segments,
                    completed_chunks=[item for item in chunks if item.status == "completed"],
                )

                chunk_response = None
                parse_result = None
                last_error = ""
                for attempt in range(1, job.config.max_retries + 1):
                    chunk.attempt_count = attempt
                    stream_buffer = ""
                    emitted_previews: dict[str, str] = {}

                    def on_delta(delta: str) -> None:
                        nonlocal stream_buffer, emitted_previews
                        stream_buffer += delta
                        previews = self._extract_stream_translations(
                            stream_buffer,
                            [segment.segment_id for segment in pending_segments],
                        )
                        for segment_id, preview in previews.items():
                            previous_preview = emitted_previews.get(segment_id, "")
                            if preview == previous_preview:
                                continue
                            emitted_delta = preview[len(previous_preview) :]
                            emitted_previews[segment_id] = preview
                            asyncio.run_coroutine_threadsafe(
                                self.broker.publish(
                                    job_id,
                                    "segment_delta",
                                    {
                                        "job_id": job_id,
                                        "chunk_id": chunk.chunk_id,
                                        "segment_id": segment_id,
                                        "delta": emitted_delta,
                                    },
                                ),
                                loop,
                            )

                    try:
                        chunk_response = await client.translate_chunk(
                            messages=messages,
                            stream=job.config.stream,
                            on_delta=on_delta,
                        )
                        parse_result = self._parse_translation_response(
                            chunk_response.text,
                            [segment.segment_id for segment in pending_segments],
                        )
                        if parse_result.missing_segment_ids:
                            raise ValueError(f"Missing translations for: {', '.join(parse_result.missing_segment_ids)}")
                        break
                    except TranslationAuthError as exc:
                        await self._fail_job_for_auth_error(
                            job=job,
                            chunk=chunk,
                            source_segments=pending_segments,
                            segments=segments,
                            chunks=chunks,
                            raw_error=exc.raw_error,
                        )
                        return
                    except Exception as exc:
                        last_error = str(exc)
                        chunk.error = last_error
                        await self.storage.append_log(
                            job_id,
                            LogEntry(
                                event="chunk_retry",
                                payload={
                                    "chunk_id": chunk.chunk_id,
                                    "attempt": attempt,
                                    "error": last_error,
                                },
                            ),
                        )

                if parse_result and not parse_result.missing_segment_ids and chunk_response:
                    chunk.status = "completed"
                    chunk.summary = parse_result.summary
                    chunk.terms = parse_result.terms
                    chunk.response_text = chunk_response.text
                    chunk.stream_fallback_used = chunk_response.stream_fallback_used
                    chunk.completed_at = utc_now_iso()
                    chunk.error = chunk_response.raw_error if chunk_response.stream_fallback_used else ""

                    for segment in pending_segments:
                        segment.translated_text = parse_result.translations.get(segment.segment_id, "")
                        segment.summary = parse_result.summary
                        segment.terms = parse_result.terms
                        segment.status = "success"
                        segment.error = ""

                    await self.storage.save_chunk(job_id, chunk)
                    await self.storage.save_segments(job_id, segments)
                    await self.storage.append_log(
                        job_id,
                        LogEntry(
                            event="chunk_completed",
                            payload={
                                "chunk_id": chunk.chunk_id,
                                "segment_ids": chunk.segment_ids,
                                "stream_fallback_used": chunk.stream_fallback_used,
                            },
                        ),
                    )

                    for segment in pending_segments:
                        await self.broker.publish(job_id, "segment_completed", segment.model_dump())
                    await self.broker.publish(
                        job_id,
                        "chunk_completed",
                        {
                            "job_id": job_id,
                            "chunk_id": chunk.chunk_id,
                            "summary": chunk.summary,
                            "segment_ids": chunk.segment_ids,
                        },
                    )
                else:
                    chunk.status = "failed"
                    chunk.error = last_error or "Failed to parse model output"
                    chunk.completed_at = utc_now_iso()
                    for segment in pending_segments:
                        if segment.status != "success":
                            segment.status = "failed"
                            segment.error = chunk.error
                    await self.storage.save_chunk(job_id, chunk)
                    await self.storage.save_segments(job_id, segments)
                    await self.broker.publish(
                        job_id,
                        "chunk_failed",
                        {
                            "job_id": job_id,
                            "chunk_id": chunk.chunk_id,
                            "error": chunk.error,
                            "segment_ids": chunk.segment_ids,
                        },
                    )

                latest_job = await self.storage.load_job(job_id)
                job = latest_job
                await self._recompute_job_progress(job, segments)
                if pending_segments:
                    job.current_segment_id = pending_segments[-1].segment_id
                    job.current_chapter = chunk.chapter_title

                if latest_job.status == "cancelled":
                    await self.storage.save_job(job)
                    break

                if latest_job.status == "pausing":
                    job.status = "paused"
                    job.updated_at = utc_now_iso()
                    await self.storage.save_job(job)
                    await export_outputs(self.storage, job, segments, chunks)
                    await self.broker.publish(job_id, "job_paused", job.model_dump())
                    return

                await self.storage.save_job(job)
                await self._emit_job_snapshot(job)

            job = await self.storage.load_job(job_id)
            await self._recompute_job_progress(job, segments)
            if job.status == "cancelled":
                await export_outputs(self.storage, job, segments, chunks)
                await self.storage.save_job(job)
                return

            if job.status == "paused":
                await export_outputs(self.storage, job, segments, chunks)
                await self.storage.save_job(job)
                return

            if any(segment.status == "failed" for segment in segments) and any(
                segment.status in {"pending", "running", "partial"} for segment in segments
            ):
                job.status = "failed"
            elif any(segment.status == "failed" for segment in segments):
                job.status = "failed"
            else:
                job.status = "completed"

            await export_outputs(self.storage, job, segments, chunks)
            await self.storage.save_job(job)
            final_event = "job_completed" if job.status == "completed" else "job_failed"
            await self.broker.publish(job_id, final_event, job.model_dump())
        except Exception as exc:
            job = await self.storage.load_job(job_id)
            job.status = "failed"
            job.last_error = str(exc) or AUTH_FAILURE_MESSAGE
            job.updated_at = utc_now_iso()
            await self.storage.save_job(job)
            await self.storage.append_log(
                job_id,
                LogEntry(event="job_failed", payload={"error": str(exc)}),
            )
            await self.broker.publish(job_id, "job_failed", job.model_dump())
        finally:
            self.tasks.pop(job_id, None)
