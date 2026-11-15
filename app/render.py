"""Turn the agent's source files into documents: typst → PDF, content.json → DOCX (+ PDF preview)."""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import httpx

from . import config, docx_fill
from .jobs import Job, sync_template


async def _run(*cmd: str, cwd: Path | None = None, timeout: float = 120) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return 124, "timed out"
    return proc.returncode, out.decode(errors="replace")


def _inside(job: Job, rel: str) -> Path:
    p = (job.work / rel).resolve()
    if not p.is_relative_to(job.work.resolve()):
        raise ValueError("path outside the job folder")
    return p


async def compile_pdf(job: Job, rel: str = "main.typ") -> tuple[bool, str]:
    src = _inside(job, rel)
    if not src.exists():
        return False, f"{rel} does not exist"
    await asyncio.to_thread(sync_template, job)  # always build with the latest layout files
    out = job.out / "document.pdf"
    code, log = await _run(
        config.TYPST, "compile", "--root", str(job.work), "--font-path", str(config.FONTS),
        "--ignore-system-fonts", str(src), str(out), cwd=job.work,
    )
    if code != 0:
        return False, log[-4000:]
    (job.out / "preview.pdf").unlink(missing_ok=True)
    pages = await _page_count(out)
    return True, f"PDF compiled ({pages} page{'s' if pages != 1 else ''}).\n{log[-1500:]}".strip()


async def _page_count(pdf: Path) -> int:
    try:
        code, out = await _run("pdfinfo", str(pdf), timeout=20)
        for line in out.splitlines():
            if line.startswith("Pages:"):
                return int(line.split()[1])
    except FileNotFoundError:
        pass
    return 0


async def render_docx(job: Job, rel: str = "content.json") -> tuple[bool, str]:
    src = _inside(job, rel)
    try:
        content = json.loads(src.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return False, f"could not read {rel}: {e}"
    await asyncio.to_thread(sync_template, job)
    tpl = job.work / f"{job.template}.docx"
    if not tpl.exists():
        return False, "this template has no Word version"
    out = job.out / "document.docx"
    try:
        await asyncio.to_thread(docx_fill.render, tpl, content, out, job.id)
    except Exception as e:  # report template/content errors back to the agent
        return False, f"docx render failed: {e!r}"
    ok, msg = await docx_to_pdf(out, job.out / "preview.pdf")
    note = "" if ok else f" (preview not available: {msg})"
    return True, f"Word document created{note}."


async def docx_to_pdf(docx: Path, pdf: Path) -> tuple[bool, str]:
    """Preview only. soffice if installed, else Collabora's convert-to endpoint."""
    if shutil.which(config.SOFFICE):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            code, log = await _run(
                config.SOFFICE, f"-env:UserInstallation=file://{profile}", "--headless",
                "--convert-to", "pdf", "--outdir", tmp, str(docx), timeout=120,
            )
            made = Path(tmp) / (docx.stem + ".pdf")
            if code == 0 and made.exists():
                shutil.move(made, pdf)
                return True, ""
            return False, log[-500:]
    if config.COLLABORA_URL:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{config.COLLABORA_URL}/cool/convert-to/pdf",
                             files={"data": (docx.name, docx.read_bytes())})
            if r.status_code == 200:
                pdf.write_bytes(r.content)
                return True, ""
            return False, f"collabora {r.status_code}"
    return False, "no converter configured"
