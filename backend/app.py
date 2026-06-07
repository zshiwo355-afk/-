from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.config import reload_config
from backend.translator.corpus_manager import CorpusManager
from backend.translator.exporter import build_output_filenames, export_outputs
from backend.translator.pipeline import EventBroker, TranslationPipeline
from backend.translator.storage import FileStorage


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


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
corpus_manager = CorpusManager(storage.base_dir / "corpus")


class CorpusCreatePayload(BaseModel):
    name: str
    description: str = ""


class DomainPromptPayload(BaseModel):
    domain_prompt: str


class GlossaryPayload(BaseModel):
    source: str
    target: str
    note: str = ""
    enabled: bool = True


class ExamplePayload(BaseModel):
    source: str
    target: str
    note: str = ""
    enabled: bool = True


class CorpusImportJsonPayload(BaseModel):
    mode: str
    target_corpus_id: str = "default"
    data: dict


class SpeedModePayload(BaseModel):
    speed_mode: str = "stable"


class PausePayload(BaseModel):
    reason: str = "unknown"


@app.on_event("startup")
async def on_startup() -> None:
    await storage.ensure_base_dirs()
    corpus_manager.ensure_default_corpus()
    config = reload_config()
    print(
        "Config loaded:\n"
        f"- has_api_key: {bool(config.tokenhub_api_key.strip())}\n"
        f"- base_url: {config.tokenhub_base_url}\n"
        f"- model: {config.model}"
    )


@app.get("/api/config/check")
async def check_config():
    config = reload_config()
    return {
        "has_api_key": bool(config.tokenhub_api_key.strip()),
        "base_url": config.tokenhub_base_url,
        "model": config.model,
    }


@app.post("/api/jobs/upload")
async def upload_job(
    file: UploadFile = File(...),
    target_language: str = Form("简体中文"),
    translation_mode: str = Form("忠实翻译"),
    stream: bool = Form(True),
    chunk_size_chars: int = Form(3500),
    corpus_id: str = Form("default"),
    use_corpus: bool = Form(True),
    use_glossary: bool = Form(True),
    use_style_examples: bool = Form(True),
    use_domain_prompt: bool = Form(True),
    translate_mode: str = Form("psychology"),
    translation_level: int = Form(3),
    speed_mode: str = Form("stable"),
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
        corpus_id=corpus_id,
        use_corpus=use_corpus,
        use_glossary=use_glossary,
        use_style_examples=use_style_examples,
        use_domain_prompt=use_domain_prompt,
        translate_mode=translate_mode,
        translation_level=translation_level,
        speed_mode=speed_mode,
    )
    return job.model_dump()


@app.get("/api/corpus")
async def list_corpora():
    return corpus_manager.list_corpora()


@app.get("/api/corpus/{corpus_id}")
async def get_corpus(corpus_id: str):
    try:
        return corpus_manager.get_corpus(corpus_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Corpus not found") from exc


@app.post("/api/corpus")
async def create_corpus(payload: CorpusCreatePayload):
    return corpus_manager.create_corpus(payload.name, payload.description)


@app.put("/api/corpus/{corpus_id}")
async def save_corpus(corpus_id: str, payload: dict):
    return corpus_manager.save_corpus(corpus_id, payload)


@app.delete("/api/corpus/{corpus_id}")
async def delete_corpus(corpus_id: str):
    try:
        corpus_manager.delete_corpus(corpus_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/corpus/{corpus_id}/domain-prompt")
async def update_domain_prompt(corpus_id: str, payload: DomainPromptPayload):
    return corpus_manager.update_domain_prompt(corpus_id, payload.domain_prompt)


@app.post("/api/corpus/{corpus_id}/glossary")
async def add_glossary(corpus_id: str, payload: GlossaryPayload):
    return corpus_manager.add_glossary_term(corpus_id, payload.source, payload.target, payload.note, payload.enabled)


@app.put("/api/corpus/{corpus_id}/glossary/{term_id}")
async def update_glossary(corpus_id: str, term_id: str, payload: GlossaryPayload):
    return corpus_manager.update_glossary_term(corpus_id, term_id, payload.source, payload.target, payload.note, payload.enabled)


@app.delete("/api/corpus/{corpus_id}/glossary/{term_id}")
async def delete_glossary(corpus_id: str, term_id: str):
    corpus_manager.delete_glossary_term(corpus_id, term_id)
    return {"ok": True}


@app.post("/api/corpus/{corpus_id}/examples")
async def add_example(corpus_id: str, payload: ExamplePayload):
    return corpus_manager.add_style_example(corpus_id, payload.source, payload.target, payload.note, payload.enabled)


@app.put("/api/corpus/{corpus_id}/examples/{example_id}")
async def update_example(corpus_id: str, example_id: str, payload: ExamplePayload):
    return corpus_manager.update_style_example(corpus_id, example_id, payload.source, payload.target, payload.note, payload.enabled)


@app.delete("/api/corpus/{corpus_id}/examples/{example_id}")
async def delete_example(corpus_id: str, example_id: str):
    corpus_manager.delete_style_example(corpus_id, example_id)
    return {"ok": True}


@app.post("/api/corpus/{corpus_id}/import")
async def import_corpus(corpus_id: str, file: UploadFile = File(...)):
    data = json.loads((await file.read()).decode("utf-8-sig"))
    return corpus_manager.save_corpus(corpus_id, data)


@app.post("/api/corpus/import-json")
async def import_corpus_json(payload: CorpusImportJsonPayload):
    try:
        return corpus_manager.import_corpus_json(payload.mode, payload.data, payload.target_corpus_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/corpus/{corpus_id}/export")
async def export_corpus(corpus_id: str):
    path = corpus_manager.base_dir / corpus_id / "corpus.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Corpus not found")
    return FileResponse(path, filename="corpus.json", media_type="application/json")


@app.post("/api/jobs/{job_id}/start")
async def start_job(job_id: str):
    config = reload_config()
    if not config.tokenhub_api_key.strip():
        raise HTTPException(status_code=400, detail="TokenHub API Key 未配置，请检查 .env 或 backend/config.local.json")
    job = await pipeline.start_job(job_id)
    return {"ok": True, **job.model_dump()}


@app.post("/api/jobs/{job_id}/pause")
async def pause_job(
    job_id: str,
    payload: PausePayload | None = None,
    x_manual_user_action: str | None = Header(default=None),
):
    current_job = await pipeline.get_job(job_id)
    if current_job.status == "completed":
        raise HTTPException(status_code=400, detail="任务已完成，不能暂停")
    reason = payload.reason if payload else "unknown"
    print(f"[pause] job_id={job_id} reason={reason or 'unknown'}")
    if reason != "user_click_pause" or x_manual_user_action != "true":
        raise HTTPException(status_code=400, detail="pause 只能由用户点击触发")
    job = await pipeline.request_pause(job_id)
    return {"ok": True, **job.model_dump()}


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    job = await pipeline.resume_job(job_id)
    if job.status == "completed":
        return {"ok": True, **job.model_dump(), "message": "任务已完成，无需继续"}
    if job.status == "cancelled":
        return {"ok": False, **job.model_dump(), "message": "任务已停止，不能继续。"}
    return {"ok": True, "job_id": job.job_id, "status": job.status, **job.model_dump()}


@app.post("/api/jobs/{job_id}/repair-stuck")
async def repair_stuck_job(job_id: str):
    job = await pipeline.repair_stuck_job(job_id)
    return {"ok": True, **job.model_dump()}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = await pipeline.request_cancel(job_id)
    return {"ok": True, **job.model_dump()}


@app.post("/api/jobs/{job_id}/speed-mode")
async def update_speed_mode(job_id: str, payload: SpeedModePayload):
    valid = {"stable", "balanced", "fast"}
    if payload.speed_mode not in valid:
        raise HTTPException(status_code=400, detail=f"speed_mode must be one of {valid}")
    job = await pipeline.set_speed_mode(job_id, payload.speed_mode)
    return {"ok": True, **job.model_dump()}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    try:
        job = await pipeline.get_job(job_id)
        payload = job.model_dump()
        payload.update(
            {
                "corpus_id": job.config.corpus_id,
                "translate_mode": job.config.translate_mode,
                "translation_level": job.config.translation_level,
                "use_corpus": job.config.use_corpus,
                "use_glossary": job.config.use_glossary,
                "use_style_examples": job.config.use_style_examples,
                "use_domain_prompt": job.config.use_domain_prompt,
                "speed_mode": job.config.speed_mode,
            }
        )
        return payload
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
    if file_type not in {"translated.txt", "translated.md", "bilingual.txt", "bilingual.md"}:
        raise HTTPException(status_code=404, detail="Unknown file type")

    job = await pipeline.get_job(job_id)
    segments = await pipeline.get_segments(job_id)
    chunks = await storage.load_chunks(job_id)
    await pipeline.storage.ensure_base_dirs()
    await export_outputs(storage, job, segments, chunks)
    output_filenames = build_output_filenames(job.file_name)
    path = storage.job_outputs_dir(job_id) / output_filenames[file_type]
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not ready")
    return FileResponse(path, filename=output_filenames[file_type], media_type="application/octet-stream")
