from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from backend.translator.pipeline import EventBroker, TranslationPipeline
from backend.translator.storage import FileStorage


app = FastAPI(title="Text Book Translator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = FileStorage(Path(__file__).resolve().parent / "data")
broker = EventBroker()
pipeline = TranslationPipeline(storage=storage, broker=broker)


@app.on_event("startup")
async def on_startup() -> None:
    await storage.ensure_base_dirs()


@app.post("/api/jobs/upload")
async def upload_job(
    file: UploadFile = File(...),
    target_language: str = Form("简体中文"),
    translation_mode: str = Form("忠实翻译"),
    stream: bool = Form(True),
    chunk_size_chars: int = Form(3500),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".txt", ".md"}:
        raise HTTPException(status_code=400, detail="Only .txt and .md files are supported.")

    content = await file.read()
    job = await pipeline.create_job_from_upload(
        file_name=file.filename or "book.txt",
        content=content,
        target_language=target_language,
        translation_mode=translation_mode,
        stream=stream,
        chunk_size_chars=chunk_size_chars,
    )
    return job.model_dump()


@app.post("/api/jobs/{job_id}/start")
async def start_job(job_id: str):
    job = await pipeline.start_job(job_id)
    return {"ok": True, **job.model_dump()}


@app.post("/api/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    job = await pipeline.request_pause(job_id)
    return {"ok": True, **job.model_dump()}


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    job = await pipeline.resume_job(job_id)
    if job.status == "completed":
        return {"ok": False, **job.model_dump(), "message": "任务已完成，不能继续。"}
    if job.status == "cancelled":
        return {"ok": False, **job.model_dump(), "message": "任务已停止，不能继续。"}
    return {"ok": True, "job_id": job.job_id, "status": job.status, **job.model_dump()}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = await pipeline.request_cancel(job_id)
    return {"ok": True, **job.model_dump()}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    try:
        return (await pipeline.get_job(job_id)).model_dump()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/segments")
async def get_segments(job_id: str):
    try:
        return [segment.model_dump() for segment in await pipeline.get_segments(job_id)]
    except Exception:
        return []


@app.get("/api/jobs/{job_id}/events")
async def get_events(job_id: str):
    queue = broker.subscribe(job_id)

    async def event_generator():
        yield {
            "event": "connected",
            "data": json.dumps({"job_id": job_id, "connected": True}, ensure_ascii=False),
        }
        try:
            while True:
                payload = await queue.get()
                yield {
                    "event": payload["event"],
                    "data": json.dumps(payload["data"], ensure_ascii=False),
                }
        finally:
            broker.unsubscribe(job_id, queue)

    return EventSourceResponse(event_generator())


@app.get("/api/jobs/{job_id}/download/{file_type}")
async def download_file(job_id: str, file_type: str):
    allowed = {
        "translated.md": "translated.md",
        "bilingual.md": "bilingual.md",
        "aligned.jsonl": "aligned.jsonl",
        "translation_log.json": "translation_log.json",
    }
    if file_type not in allowed:
        raise HTTPException(status_code=404, detail="Unknown file type")

    path = storage.job_outputs_dir(job_id) / allowed[file_type]
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not ready")
    return FileResponse(path, filename=allowed[file_type], media_type="application/octet-stream")
