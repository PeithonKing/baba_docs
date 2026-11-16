"""Web server. Run: .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765"""
import asyncio
import contextlib
import hashlib
import json
import logging
import mimetypes
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

from . import config, guard, jobs, memory, nextcloud, render, sources
from .agent import Sessions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gcmv")
sessions = Sessions()
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp"}
OFFICE_EXT = {".doc", ".docx", ".odt", ".rtf"}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # A question left open by a previous run stays visible; answering it resumes the saved
    # Claude conversation (see api_answer).
    tasks = [asyncio.create_task(sessions.reap_idle()), asyncio.create_task(_signature_loop()),
             asyncio.create_task(memory.loop()), asyncio.create_task(_migrate_once())]
    yield
    for t in tasks:
        t.cancel()
    await sessions.close_all()


async def _signature_loop():
    """Keep the cached signature in step with his Nextcloud (every 30 min)."""
    while True:
        try:
            res = await nextcloud.pull_signature()
            if res in ("updated", "missing"):
                log.info("signature from Nextcloud: %s (%s)", res, config.NEXTCLOUD_SIGNATURE_PATH)
        except Exception as e:
            log.warning("signature refresh failed: %r", e)
        await asyncio.sleep(30 * 60)


async def _migrate_once():
    """One-time changes to his Nextcloud (e.g. Notices → Letterhead), recorded so they run once."""
    marker = config.DATA / "migrations.json"
    done = json.loads(marker.read_text()) if marker.exists() else []
    if "letterhead-folder" in done or not nextcloud.configured():
        return
    try:
        moved = await nextcloud.migrate_folders()
    except Exception as e:
        log.warning("folder migration failed (will retry next start): %r", e)
        return
    base = f"{config.NEXTCLOUD_FOLDER}/Notices/"
    for j in jobs.all_jobs():  # keep each document's record of where it was saved
        changed = False
        for rec in j.saved + ([j.exported] if j.exported else []):
            if rec and rec.get("path", "").startswith(base):
                rec["path"] = f"{config.NEXTCLOUD_FOLDER}/Letterhead/" + rec["path"][len(base):]
                changed = True
        if changed:
            j.save(touch=False)
    marker.write_text(json.dumps(done + ["letterhead-folder"]))
    if moved:
        log.info("moved in Nextcloud: %s", "; ".join(moved))


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(guard.DeviceGuard)


@app.middleware("http")
async def cache_rules(request: Request, call_next):
    """A file asked for by its current fingerprint (?v=<hash>, see _build) can never change, so the
    browser keeps it for good and skips the round trip. Everything else of ours is revalidated
    every time (Cloudflare would otherwise cache /static/*.js|css for hours)."""
    resp = await call_next(request)
    path = request.url.path
    if path.startswith("/static/"):
        name = path.removeprefix("/static/")
        fresh = resp.status_code == 200 and request.query_params.get("v") and VERS.get(name) == request.query_params["v"]
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if fresh else "no-cache"
    elif path in ("/", "/sw.js", "/manifest.webmanifest"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp

# ---- pages & app files ---------------------------------------------------------
# Every deploy must reach the installed app (PWA) without reinstalling it:
# - index.html is never cached, and names each file it uses with ?v=<content hash>;
# - app.js / style.css get the same treatment for files *they* reference;
# - the page carries a build id; the app compares it with /api/version when it comes back to the
#   foreground (or every few minutes) and reloads itself at a safe moment when it changed.
def _build() -> tuple[str, dict, str, dict]:
    import re

    files = {p.name: p.read_bytes() for p in config.WEB.iterdir() if p.is_file()}
    h = lambda b: hashlib.sha256(b).hexdigest()[:10]  # noqa: E731
    ver = {n: h(b) for n, b in files.items()}

    def bust(text: str) -> str:
        return re.sub(r"/static/([\w.-]+)(?![\w.?-])",
                      lambda m: f"/static/{m.group(1)}?v={ver[m.group(1)]}" if m.group(1) in ver else m.group(0), text)

    texts = {}
    for name in ("app.js", "style.css"):
        texts[name] = bust(files[name].decode())
        ver[name] = h(texts[name].encode())
    build = h("".join(f"{k}:{v}" for k, v in sorted(ver.items())).encode())
    index = bust(files["index.html"].decode()).replace(
        "</head>", f'<meta name="build" content="{build}">\n</head>', 1)
    return index, texts, build, ver


INDEX_HTML, BUSTED, BUILD, VERS = _build()  # VERS: file name → its current fingerprint


@app.get("/static/{name}.{ext}", include_in_schema=False)
async def busted_asset(name: str, ext: str):
    """app.js / style.css with their own references fingerprinted; anything else falls through."""
    text = BUSTED.get(f"{name}.{ext}")
    if text is None:
        return FileResponse(_static_file(f"{name}.{ext}"))
    kind = "text/javascript" if ext == "js" else "text/css"
    return Response(text, media_type=f"{kind}; charset=utf-8")


def _static_file(name: str):
    f = (config.WEB / name).resolve()
    if not f.is_relative_to(config.WEB.resolve()) or not f.is_file():
        raise HTTPException(404)
    return f


@app.get("/api/version")
async def api_version():
    return JSONResponse({"build": BUILD}, headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=config.WEB), name="static")


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


def _safe_name(name: str, fallback: str) -> str:
    n = nextcloud.clean_name(Path(name or "").name) if name else ""
    return n if n and n != "Document" else fallback


def _unique(folder: Path, name: str) -> Path:
    p = folder / name
    stem, suf, n = p.stem, p.suffix, 2
    while p.exists():
        p = folder / f"{stem} ({n}){suf}"
        n += 1
    return p


def _store(job: jobs.Job, name: str, data: bytes, prefix: str = "photo") -> tuple[str, str] | None:
    """Save one attached file into uploads/. Photos are straightened and resized; other files are
    kept as they are. Returns (path relative to work, kind)."""
    up = job.work / "uploads"
    up.mkdir(exist_ok=True)
    ext = Path(name or "").suffix.lower()
    if ext in IMAGE_EXT or (not ext and data[:3] == b"\xff\xd8\xff"):
        try:
            img = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
        except Exception:
            img = None
        if img is not None:
            img.thumbnail((2400, 2400))
            n = len(list(up.glob(f"{prefix}_*.jpg"))) + 1
            p = up / f"{prefix}_{n}.jpg"
            img.save(p, "JPEG", quality=90)
            return f"uploads/{p.name}", "mark" if prefix == "mark" else "photo"
    p = _unique(up, _safe_name(name, f"file{ext or ''}"))
    p.write_bytes(data)
    kind = {".pdf": "PDF", ".xlsx": "Excel file", ".xls": "Excel file", ".csv": "CSV list", ".txt": "text file"}.get(
        ext, "Word file" if ext in OFFICE_EXT else "file")
    return f"uploads/{p.name}", kind


async def _gather(job: jobs.Job, files: list[UploadFile], nc_paths: list[str], prefix: str = "photo") -> list[dict]:
    got = []
    for f in files:
        if not f.filename:
            continue
        r = _store(job, f.filename, await f.read(), prefix)
        if r:
            got.append({"path": r[0], "kind": r[1], "name": f.filename})
    for path in nc_paths:
        try:
            data, info = await nextcloud.download(path)
        except Exception as e:
            log.warning("attach %s failed: %r", path, e)
            continue
        r = _store(job, info.get("name") or Path(path).name, data)
        if r:
            job = jobs.load(job.id)
            job.nc_seen[info.get("path") or path] = info.get("etag")
            job.save()
            got.append({"path": r[0], "kind": r[1], "name": Path(path).name, "from": path})
    return got


def _compose(text: str, att: list[dict], marks_on: str = "") -> str:
    parts = []
    marks = [a for a in att if a["kind"] == "mark"]
    other = [a for a in att if a["kind"] != "mark"]
    if other:
        parts.append("He attached: " + "; ".join(
            f"{a['path']} ({a['kind']}" + (f", from his Nextcloud: {a['from']}" if a.get("from") else "") + ")"
            for a in other) + ". Read them.")
    if marks:
        which = "the original file" if marks_on == "original" else "the current document"
        parts.append(f"He marked {which} with his pen (red ink): " + ", ".join(a["path"] for a in marks) +
                     ". Look at the marks; confirm with him what he wants before changing anything.")
    if text.strip():
        parts.append(f"His message:\n<<<\n{text.strip()}\n>>>")
    return "\n\n".join(parts) or "(empty message)"


DEVICE = {"tablet": "a tablet with a pen", "phone": "a phone", "computer": "a computer"}


def _intro(job: jobs.Job, device: str) -> str:
    meta = next((t for t in jobs.templates() if t["id"] == job.template), {})
    fmt = {"docx": "Word document (.docx, editable)", "pdf": "PDF"}.get(job.format, job.format)
    return (f"New document. Kind: {meta.get('name', job.template)} (its files are in the current folder; read "
            f"GUIDE.md first). Output he chose: {fmt}. Today is {time.strftime('%A, %-d %B %Y')}. "
            f"He is using {DEVICE.get(device, 'a phone or tablet')}.")


@app.get("/api/templates")
async def api_templates():
    return jobs.templates()


@app.get("/api/jobs")
async def api_jobs():
    return [j.public() for j in jobs.all_jobs()[:50]]


@app.post("/api/jobs")
async def api_create(template: str = Form(...), format: str = Form("pdf"), text: str = Form(""),
                     device: str = Form(""), nc_paths: list[str] = Form(default=[]),
                     photos: list[UploadFile] = File(default=[])):
    try:
        job = jobs.create(template, format)
    except ValueError:
        raise HTTPException(400, "unknown template")
    att = await _gather(job, photos, nc_paths)
    s = sessions.get(job)
    s.emit({"type": "user", "text": text.strip(), "photos": [a["path"] for a in att if a["kind"] == "photo"],
            "files": [a["name"] for a in att if a["kind"] != "photo"]})
    body = _compose(text, att)
    if not text.strip() and not att:
        body = "He has not given any content yet. Start by asking him what this document is about."
    s.start_turn(_intro(job, device) + "\n\n" + body)
    return job.public()


@app.post("/api/open")
async def api_open(device: str = Form(""), nc_path: str = Form(""), file: UploadFile | None = File(default=None)):
    """'Edit existing file': reopen the document that made it, or start an edit job around it."""
    info = {}
    if nc_path:
        try:
            data, info = await nextcloud.download(nc_path)
        except FileNotFoundError:
            raise HTTPException(404, "not found")
        name = info.get("name") or Path(nc_path).name
    elif file is not None and file.filename:
        data, name = await file.read(), file.filename
    else:
        raise HTTPException(400)

    jid = sources.job_id_in(data, name)
    existing = jobs.load(jid) if jid else None
    if not existing and jid and nextcloud.configured():
        existing = await sources.restore(jid)
    if not existing and info.get("fileid"):
        existing = jobs.by_fileid(info["fileid"])
    if existing:
        if info.get("path"):
            existing.nc_seen[info["path"]] = info.get("etag")
            existing.save(touch=False)
        return {"id": existing.id, "reopened": True}

    job = jobs.create("edit", "pdf")
    orig_dir = job.work / "original"
    orig_dir.mkdir(exist_ok=True)
    fname = _safe_name(name, "file")
    (orig_dir / fname).write_bytes(data)
    ext = Path(fname).suffix.lower()
    kind = "pdf" if ext == ".pdf" else "docx" if ext in OFFICE_EXT else "image" if ext in IMAGE_EXT else "other"
    preview = None
    if kind == "pdf":
        preview = f"original/{fname}"
    elif kind == "docx":
        ok, _ = await render.convert(orig_dir / fname, orig_dir / "preview.pdf")
        preview = "original/preview.pdf" if ok else None
    elif kind == "image":
        preview = f"original/{fname}"
    job = jobs.load(job.id)
    job.original = {"name": f"original/{fname}", "source": info.get("path"), "kind": kind, "preview": preview}
    job.title = Path(fname).stem[:120]
    if info.get("path"):
        job.nc_seen[info["path"]] = info.get("etag")
    job.save()
    s = sessions.get(job)
    s.emit({"type": "user", "text": "", "files": [fname], "opened": True})
    where = f"from his Nextcloud: {info['path']}" if info.get("path") else "from his device"
    s.start_turn(
        _intro(job, device) + f"\n\nHe wants to change an existing file: original/{fname} ({where}). It was not "
        "made with this app (no record of it). Follow GUIDE.md: read it first, tell him briefly what you see, "
        "then ask him what he wants."
    )
    return {"id": job.id, "reopened": False}


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    j = _job_or_404(job_id)
    s = sessions.by_job.get(j.id)
    return {**j.public(), "busy": bool(s and s.busy), "waiting": bool(s and s.live_card),
            "events": j.events()}


@app.post("/api/jobs/{job_id}/message")
async def api_message(job_id: str, text: str = Form(""), marks_on: str = Form(""),
                      nc_paths: list[str] = Form(default=[]), photos: list[UploadFile] = File(default=[]),
                      marks: list[UploadFile] = File(default=[])):
    """A message, photos/files or pen marks. Accepted at any time (see AgentSession.deliver)."""
    j = _job_or_404(job_id)
    s = sessions.get(j)
    att = await _gather(j, photos, nc_paths) + await _gather(j, marks, [], prefix="mark")
    if not text.strip() and not att:
        raise HTTPException(400)
    s.emit({"type": "user", "text": text.strip(),
            "photos": [a["path"] for a in att if a["kind"] in ("photo", "mark")],
            "files": [a["name"] for a in att if a["kind"] not in ("photo", "mark")]})
    s.deliver(_compose(text, att, marks_on))
    return {"ok": True}


@app.post("/api/jobs/{job_id}/answer")
async def api_answer(job_id: str, request: Request):
    """His answers to one question card ({"id", "answers"}). Accepted at any time."""
    j = _job_or_404(job_id)
    body = await request.json()
    answers = body.get("answers")
    if answers is None and body.get("answer"):  # old single-answer form
        answers = [body["answer"]]
    answers = answers if isinstance(answers, list) else []
    message = str(body.get("message") or "").strip()
    if not answers and not message:
        raise HTTPException(400)
    if not sessions.get(j).answer_card(body.get("id"), answers, message):
        raise HTTPException(409, "already answered")
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
async def api_file(job_id: str, name: str, download: int = 0, share: int = 0):
    j = _job_or_404(job_id)
    if name not in ("document.pdf", "document.docx", "preview.pdf"):
        raise HTTPException(404)
    f = j.out / name
    if not f.exists():
        raise HTTPException(404)
    ext = name.split(".")[1]
    nice = "".join(c for c in j.title if c.isalnum() or c in " -_–").strip() or "document"
    # files leaving the app carry the document's id, so they can be reopened for editing later
    data = sources.stamped(j, f) if (download or share) and name.startswith("document.") else f.read_bytes()
    disp = f"attachment; filename*=UTF-8''{quote(nice + '.' + ext)}" if download else "inline"
    return Response(data, media_type=mimetypes.types_map.get("." + ext, "application/octet-stream")
                    if ext != "docx" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Cache-Control": "no-cache", "Content-Disposition": disp})


def _inside(base: Path, rel: str) -> Path:
    f = (base / rel).resolve()
    if not f.is_relative_to(base.resolve()) or not f.is_file():
        raise HTTPException(404)
    return f


@app.get("/api/jobs/{job_id}/upload/{name}")
async def api_upload(job_id: str, name: str):
    j = _job_or_404(job_id)
    return FileResponse(_inside(j.work / "uploads", name))


@app.get("/api/jobs/{job_id}/original")
async def api_original(job_id: str):
    """What to show as 'Original' (an edit job): the PDF / preview PDF / image."""
    j = _job_or_404(job_id)
    if not j.original or not j.original.get("preview"):
        raise HTTPException(404)
    return FileResponse(_inside(j.work, j.original["preview"]), headers={"Cache-Control": "no-cache"})


@app.get("/api/jobs/{job_id}/nextcloud")
async def api_nextcloud_link(job_id: str):
    """Open the document's saved file in his Nextcloud web UI."""
    j = _job_or_404(job_id)
    last = j.last_saved()
    if not last:
        raise HTTPException(404)
    return RedirectResponse(nextcloud.web_link(last.get("fileid"), last["path"]), status_code=302)


# ---- Nextcloud file picker ---------------------------------------------------
def _nc_item(i: dict) -> dict:
    return {k: i.get(k) for k in ("path", "name", "dir", "size", "modified", "type", "fileid")}


@app.get("/api/nc/list")
async def api_nc_list(path: str = ""):
    if not nextcloud.configured():
        raise HTTPException(503, "Nextcloud is not set up")
    try:
        items = await nextcloud.listdir(path)
    except FileNotFoundError:
        raise HTTPException(404)
    except ValueError:
        raise HTTPException(400)
    hide = config.NEXTCLOUD_SOURCES
    return {"path": nextcloud.norm(path), "items": [_nc_item(i) for i in items if not i["path"].startswith(hide)]}


@app.get("/api/nc/search")
async def api_nc_search(q: str):
    if not nextcloud.configured():
        raise HTTPException(503)
    if len(q.strip()) < 2:
        return {"items": []}
    return {"items": [_nc_item(i) for i in await nextcloud.search(q.strip())]}


@app.get("/api/nc/thumb/{fileid}")
async def api_nc_thumb(fileid: str):
    """Small preview image of a Nextcloud file (from Nextcloud's own preview service)."""
    if not fileid.isdigit() or not nextcloud.configured():
        raise HTTPException(404)
    url = config.NEXTCLOUD_URL.rstrip("/") + f"/index.php/core/preview?fileId={fileid}&x=160&y=160&a=1"
    async with httpx.AsyncClient(auth=(config.NEXTCLOUD_USER, config.NEXTCLOUD_APP_PASSWORD), timeout=30) as c:
        r = await c.get(url)
    if r.status_code != 200:
        raise HTTPException(404)
    return Response(r.content, media_type=r.headers.get("content-type", "image/png"),
                    headers={"Cache-Control": "private, max-age=86400"})
