import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pipeline import run_pipeline

DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

jobs: dict[str, dict] = {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    recent = sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)[:10]
    return templates.TemplateResponse("index.html", {"request": request, "recent": recent})


@app.post("/ingest")
async def ingest(
    request: Request,
    text:       str            = Form(""),
    source_url: str            = Form(""),
    file:       Optional[UploadFile] = File(None),
):
    job_id    = str(uuid.uuid4())[:8]
    file_path = None
    file_name = None

    if file and file.filename:
        file_path = str(DATA_DIR / f"{job_id}_{file.filename}")
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(await file.read())
        file_name = file.filename

    label = file_name or source_url or (text[:60] + "…" if len(text) > 60 else text) or "—"

    jobs[job_id] = {
        "id":         job_id,
        "label":      label,
        "status":     "queued",
        "steps":      [],
        "result":     None,
        "error":      None,
        "created_at": datetime.now().isoformat(),
    }

    asyncio.create_task(_run(job_id, text, source_url, file_path, file_name))
    return RedirectResponse(f"/job/{job_id}", status_code=303)


async def _run(job_id: str, text: str, url: str, file_path: Optional[str], file_name: Optional[str]):
    def step(msg: str):
        jobs[job_id]["steps"].append(msg)
        jobs[job_id]["status"] = "running"

    try:
        result = await run_pipeline(text=text, url=url, file_path=file_path,
                                    file_name=file_name, on_step=step)
        jobs[job_id].update({"status": "done", "result": result})
    except Exception as e:
        jobs[job_id].update({"status": "error", "error": str(e)})
    finally:
        if file_path:
            Path(file_path).unlink(missing_ok=True)


@app.get("/job/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    job = jobs.get(job_id)
    if not job:
        return HTMLResponse("Job not found", status_code=404)
    return templates.TemplateResponse("job.html", {"request": request, "job": job})


@app.get("/api/job/{job_id}")
async def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(job)
