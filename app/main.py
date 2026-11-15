"""Web server. Run: .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765"""
import asyncio
import hashlib
import contextlib
import json
import logging
import time
from io import BytesIO

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

from . import config, guard, jobs, nextcloud
from .agent import Sessions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
sessions = Sessions()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # A question left open by a previous run stays visible; answering it resumes the saved
    # Claude conversation (see api_answer).
    for j in jobs.all_jobs():  # catch up on documents built but not yet in Nextcloud
        _catch_up_sync(j)
    reaper = asyncio.create_task(sessions.reap_idle())
    sig = asyncio.create_task(_signature_loop())
    yield
    reaper.cancel()
    sig.cancel()
    await sessions.close_all()


async def _signature_loop():
    """Keep the cached signature in step with his Nextcloud (every 30 min)."""
    log = logging.getLogger("gcmv")
    while True:
        try:
            res = await nextcloud.pull_signature()
            if res in ("updated", "missing"):
                log.info("signature from Nextcloud: %s (%s)", res, config.NEXTCLOUD_SIGNATURE_PATH)
        except Exception as e:
            log.warning("signature refresh failed: %r", e)
        await asyncio.sleep(30 * 60)


def _catch_up_sync(j: jobs.Job):
    sync = j.sync or {}
    if (j.preview_version and j.outputs().get(j.format) and sync.get("state") not in ("conflict", "kept")
            and sync.get("version") != j.preview_version):
        sessions.get(j).request_sync()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(guard.DeviceGuard)


@app.middleware("http")
async def no_edge_cache(request: Request, call_next):
    """Cloudflare would otherwise cache /static/*.js|css for hours; the files are tiny, so
    always revalidate (ETag makes repeat loads cheap)."""
    resp = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path in ("/", "/sw.js", "/manifest.webmanifest"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp
app.mount("/static", StaticFiles(directory=config.WEB), name="static")


# ---- pages ------------------------------------------------------------------
def _busted_index() -> str:
    """index.html with ?v=<content hash> on our own JS/CSS, so a deploy is never hidden behind a
    cached copy (Cloudflare's browser-cache TTL overrides our no-cache on .js/.css)."""
    html = (config.WEB / "index.html").read_text()
    for name in ("app.js", "style.css"):
        h = hashlib.sha256((config.WEB / name).read_bytes()).hexdigest()[:10]
        html = html.replace(f"/static/{name}", f"/static/{name}?v={h}")
    return html


INDEX_HTML = _busted_index()


@app.get("/")
async def index():
    return HTMLResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(config.WEB / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def sw():
    return FileResponse(config.WEB / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


ENROLL_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Add this device</title>
<style>body{margin:0;min-height:100dvh;display:grid;place-items:center;background:#fbfaf7;color:#1c1c1a;
font:18px/1.45 system-ui,sans-serif;padding:1.5rem;box-sizing:border-box;text-align:center}
img{width:84px}h1{font-size:1.4rem;font-weight:500;margin:.8rem 0 .3rem}p{color:#64625d;margin:0 0 1.4rem}
button{font:inherit;font-weight:500;background:#1c1c1a;color:#fff;border:0;border-radius:14px;padding:.9rem 1.6rem}
small{display:block;margin-top:1.2rem;color:#9a988f;font-size:.8rem}</style></head><body><form method="post">
<img src="/static/icon-192.png" alt=""><h1>School Documents</h1><p>Use this app on this device?</p>
<button type="submit">Add this device</button>
<small>Open this page in Chrome or Brave, not inside WhatsApp.</small></form></body></html>"""


@app.get("/enroll/{code}")
async def enroll_page(code: str):
    if not guard.code_valid(code):
        return PlainTextResponse("This link has expired or was already used. Ask for a new one.", status_code=404)
    return HTMLResponse(ENROLL_PAGE, headers={"Cache-Control": "no-store"})


@app.post("/enroll/{code}")
async def enroll(code: str, request: Request):
    hit = guard.redeem(code)
    if not hit:
        return PlainTextResponse("This link has expired or was already used. Ask for a new one.", status_code=404)
    name, token = hit
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(guard.COOKIE, token, max_age=guard.ONE_YEAR, httponly=True, samesite="lax",
                    secure=guard.from_internet(request))
    logging.getLogger("gcmv").info("enrolled device %s", name)
    return resp


# ---- api --------------------------------------------------------------------
def _job_or_404(job_id: str) -> jobs.Job:
    j = jobs.load(job_id)
    if not j:
        raise HTTPException(404)
    return j


async def _save_photos(job: jobs.Job, photos: list[UploadFile]) -> list[str]:
    saved = []
    up = job.work / "uploads"
    n = len(list(up.glob("*.jpg")))
    for f in photos:
        if not f.filename:
            continue
        data = await f.read()
        try:
            img = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
        except Exception:
            continue
        img.thumbnail((2000, 2000))
        n += 1
        name = f"photo_{n}.jpg"
        img.save(up / name, "JPEG", quality=88)
        saved.append(f"uploads/{name}")
    return saved


def _compose(text: str, photos: list[str]) -> str:
    parts = []
    if photos:
        parts.append("He sent photo(s): " + ", ".join(photos) + ". Read them.")
    if text.strip():
        parts.append(f"His message:\n<<<\n{text.strip()}\n>>>")
    return "\n\n".join(parts) or "(empty message)"


@app.get("/api/templates")
async def api_templates():
    return jobs.templates()


@app.get("/api/jobs")
async def api_jobs():
    return [j.public() for j in jobs.all_jobs()[:50]]


@app.post("/api/jobs")
async def api_create(template: str = Form(...), format: str = Form("pdf"), text: str = Form(""),
                     photos: list[UploadFile] = File(default=[])):
    try:
        job = jobs.create(template, format)
    except ValueError:
        raise HTTPException(400, "unknown template")
    saved = await _save_photos(job, photos)
    fmt_name = "Word document (.docx, editable)" if job.format == "docx" else "PDF"
    s = sessions.get(job)
    s.emit({"type": "user", "text": text.strip(), "photos": saved})
    intro = (
        f"New document. Template: {job.template} (its files are in the current folder; read GUIDE.md first). "
        f"Output: {fmt_name}. Today is {time.strftime('%-d %b %Y')}.\n\n" + _compose(text, saved)
    )
    s.start_turn(intro)
    return job.public()


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    j = _job_or_404(job_id)
    _catch_up_sync(j)
    s = sessions.by_job.get(j.id)
    return {**j.public(), "busy": bool(s and s.busy), "question_live": bool(s and s.question_live),
            "events": j.events()}


@app.post("/api/jobs/{job_id}/message")
async def api_message(job_id: str, text: str = Form(""), photos: list[UploadFile] = File(default=[])):
    j = _job_or_404(job_id)
    s = sessions.get(j)
    if s.busy:
        raise HTTPException(409, "busy")
    saved = await _save_photos(j, photos)
    s.emit({"type": "user", "text": text.strip(), "photos": saved})
    s.start_turn(_compose(text, saved))
    return {"ok": True}


@app.post("/api/jobs/{job_id}/answer")
async def api_answer(job_id: str, request: Request):
    j = _job_or_404(job_id)
    body = await request.json()
    ans = str(body.get("answer", "")).strip()
    if not ans:
        raise HTTPException(400)
    s = sessions.get(j)
    if s.give_answer(ans):
        return {"ok": True}
    # The question's tool call is gone (e.g. server restarted): resume the saved conversation.
    if s.busy:
        raise HTTPException(409, "busy")
    q = (j.pending_question or {}).get("question")
    j.pending_question = None
    j.save()
    s.emit({"type": "user", "text": ans, "answer": True})
    s.start_turn(
        "(The app restarted while you were waiting for his answer, so that question's tool call was "
        f"interrupted. Do not ask it again.) "
        + (f'You asked: "{q}". ' if q else "") + f"His answer: {ans}. Continue from there."
    )
    return {"ok": True}


@app.get("/api/jobs/{job_id}/stream")
async def api_stream(job_id: str, request: Request, after: int = 0):
    j = _job_or_404(job_id)
    s = sessions.get(j)
    q: asyncio.Queue = asyncio.Queue()
    s.subscribers.add(q)

    async def gen():
        try:
            last = after
            for ev in j.events(after):  # catch up on anything missed
                last = ev["seq"]
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), 20)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if ev["seq"] > last:
                    last = ev["seq"]
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            s.subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/jobs/{job_id}/file/{name}")
async def api_file(job_id: str, name: str, download: int = 0):
    j = _job_or_404(job_id)
    if name not in ("document.pdf", "document.docx", "preview.pdf"):
        raise HTTPException(404)
    f = j.out / name
    if not f.exists():
        raise HTTPException(404)
    ext = name.split(".")[1]
    nice = "".join(c for c in j.title if c.isalnum() or c in " -_–").strip() or "document"
    return FileResponse(f, filename=f"{nice}.{ext}" if download else None,
                        content_disposition_type="attachment" if download else "inline",
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/jobs/{job_id}/upload/{name}")
async def api_upload(job_id: str, name: str):
    j = _job_or_404(job_id)
    f = (j.work / "uploads" / name).resolve()
    if not f.is_relative_to((j.work / "uploads").resolve()) or not f.exists():
        raise HTTPException(404)
    return FileResponse(f)


@app.post("/api/jobs/{job_id}/sync")
async def api_sync(job_id: str):
    """Retry a failed Nextcloud save (the normal save happens automatically after each build)."""
    j = _job_or_404(job_id)
    if not nextcloud.configured():
        return {"ok": False, "message": "Nextcloud is not set up yet. Please download the file for now."}
    if not j.outputs().get(j.format):
        raise HTTPException(400, "nothing to save yet")
    sessions.get(j).request_sync()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/sync/resolve")
async def api_sync_resolve(job_id: str, request: Request):
    """His choice after 'this document was changed in Nextcloud': merge | overwrite | keep."""
    j = _job_or_404(job_id)
    choice = (await request.json()).get("choice")
    if choice not in ("merge", "overwrite", "keep"):
        raise HTTPException(400)
    try:
        await sessions.get(j).resolve_conflict(choice)
    except Exception:
        logging.getLogger("gcmv").exception("resolve failed for %s", j.id)
        return {"ok": False, "message": "Could not reach Nextcloud. Please try again."}
    return {"ok": True}


@app.get("/api/jobs/{job_id}/nextcloud")
async def api_nextcloud_link(job_id: str):
    """Redirect to the file in his Nextcloud web UI."""
    j = _job_or_404(job_id)
    fid = (j.exported or {}).get("fileid")
    if not fid:
        raise HTTPException(404)
    base = (config.NEXTCLOUD_PUBLIC_URL or config.NEXTCLOUD_URL).rstrip("/")
    return RedirectResponse(f"{base}/f/{fid}", status_code=302)
