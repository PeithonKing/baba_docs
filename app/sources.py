"""Link a saved file back to the document (job) that made it, so it can be edited again later.

- Every PDF / Word file the agent saves to Nextcloud is stamped with "gcmv-job:<id>"
  (PDF Keywords, Word "identifier" property). The stamp survives copies and WhatsApp.
- The job itself (sources, photos, chat) is zipped to "<NEXTCLOUD_SOURCES>/<id>.zip" in his
  Nextcloud, so it can be restored even if this server lost it.
"""
import io
import json
import shutil
import zipfile
from pathlib import Path

from . import config, jobs, nextcloud

TAG = "gcmv-job:"
_SKIP_DIRS = {"lib", "__pycache__"}


def stamped(job: jobs.Job, f: Path) -> bytes:
    """File bytes with the job id written into its metadata (PDF / DOCX); other files as they are."""
    data = f.read_bytes()
    try:
        if f.suffix.lower() == ".pdf":
            from pypdf import PdfReader, PdfWriter

            w = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
            meta = dict(w.metadata or {})
            kw = str(meta.get("/Keywords") or "")
            kw = " ".join(k for k in kw.split() if not k.startswith(TAG))
            w.add_metadata({**meta, "/Keywords": f"{kw} {TAG}{job.id}".strip()})
            out = io.BytesIO()
            w.write(out)
            return out.getvalue()
        if f.suffix.lower() == ".docx":
            from docx import Document

            d = Document(io.BytesIO(data))
            d.core_properties.identifier = f"{TAG}{job.id}"
            out = io.BytesIO()
            d.save(out)
            return out.getvalue()
    except Exception:
        pass  # an odd file: save it unstamped rather than not at all
    return data


def job_id_in(data: bytes, name: str) -> str | None:
    """The job id stamped in a PDF / DOCX, if any."""
    try:
        if name.lower().endswith(".pdf"):
            from pypdf import PdfReader

            text = str((PdfReader(io.BytesIO(data)).metadata or {}).get("/Keywords") or "")
        elif name.lower().endswith(".docx"):
            from docx import Document

            text = Document(io.BytesIO(data)).core_properties.identifier or ""
        else:
            return None
    except Exception:
        return None
    for word in text.split():
        if word.startswith(TAG):
            return word[len(TAG):]
    return None


def zip_job(job: jobs.Job) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("job.json", "events.jsonl"):
            if (job.dir / name).exists():
                z.write(job.dir / name, f"_job/{name}")
        for p in sorted(job.work.rglob("*")):
            rel = p.relative_to(job.work)
            if p.is_file() and not (set(rel.parts) & _SKIP_DIRS):
                z.write(p, f"work/{rel}")
    return buf.getvalue()


def _sources_path(job_id: str) -> str:
    return f"{config.NEXTCLOUD_SOURCES}/{job_id}.zip"


async def push(job: jobs.Job):
    await nextcloud.upload(_sources_path(job.id), zip_job(job), force=True)


async def restore(job_id: str) -> jobs.Job | None:
    """Bring a job back from its zip in Nextcloud (when this server no longer has it)."""
    if not job_id.replace("-", "").isalnum():
        return None
    try:
        data, _ = await nextcloud.download(_sources_path(job_id))
    except FileNotFoundError:
        return None
    dest = config.JOBS / job_id
    tmp = config.JOBS / f".restore-{job_id}"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            target = (tmp / info.filename).resolve()
            if not target.is_relative_to(tmp.resolve()):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if not info.is_dir():
                target.write_bytes(z.read(info))
    (tmp / "work").mkdir(exist_ok=True)
    for name in ("job.json", "events.jsonl"):
        if (tmp / "_job" / name).exists():
            shutil.move(tmp / "_job" / name, tmp / name)
    shutil.rmtree(tmp / "_job", ignore_errors=True)
    meta = json.loads((tmp / "job.json").read_text())
    meta["session_id"] = None  # the Claude conversation lived on the other machine
    meta["pending_question"] = None
    (tmp / "job.json").write_text(json.dumps(meta, indent=2))
    if dest.exists():
        shutil.rmtree(tmp)
    else:
        tmp.rename(dest)
    job = jobs.load(job_id)
    if job:
        jobs.sync_template(job)
    return job
