"""Keep each document's latest version in his Nextcloud (WebDAV). Runs on the server, not the agent.

Layout: <NEXTCLOUD_FOLDER>/<template's nextcloud_folder>/<title>_<YYYY-MM>.<pdf|docx>
e.g.    School Documents/Notices/Notice – Staff meeting_2026-11.pdf

- Folders are created as needed (MKCOL).
- Each sync of the same document overwrites its own file (Nextcloud keeps old versions).
- A different document with the same name gets "<title>_<YYYY-MM> (2).pdf".
- Before overwriting, the file's ETag in Nextcloud is compared with the one we recorded
  after our last write. If it changed, someone edited it there: we stop and report a
  conflict instead of overwriting their work.
"""
import html
import json
import subprocess
import time
from urllib.parse import quote

import httpx

from . import config
from .jobs import Job

BAD = '\\/:*?"<>|#%\n\r\t'


class Conflict(Exception):
    """The file in Nextcloud was changed by someone else since our last sync."""

    def __init__(self, path: str, remote: dict):
        super().__init__(path)
        self.path, self.remote = path, remote


def configured() -> bool:
    return bool(config.NEXTCLOUD_URL and config.NEXTCLOUD_USER and config.NEXTCLOUD_APP_PASSWORD)


def _client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        auth=(config.NEXTCLOUD_USER, config.NEXTCLOUD_APP_PASSWORD), timeout=60, transport=transport
    )


def _dav(path: str) -> str:
    """WebDAV URL for a path inside his files ("a/b c.pdf" → .../files/asish/a/b%20c.pdf)."""
    base = config.NEXTCLOUD_URL.rstrip("/")
    return f"{base}/remote.php/dav/files/{quote(config.NEXTCLOUD_USER)}/" + quote(path, safe="/")


def _clean(name: str) -> str:
    s = "".join(" " if c in BAD else c for c in name).strip(" .")
    return " ".join(s.split())[:120] or "Document"


def _folder_for(job: Job) -> str:
    meta = json.loads((config.TEMPLATES / job.template / "meta.json").read_text())
    return "/".join(p for p in (config.NEXTCLOUD_FOLDER, meta.get("nextcloud_folder") or "Other") if p)


def _stem_for(job: Job) -> str:
    return f"{_clean(job.title)}_{time.strftime('%Y-%m', time.localtime(job.created))}"


async def _exists(c: httpx.AsyncClient, path: str) -> bool:
    r = await c.request("PROPFIND", _dav(path), headers={"Depth": "0"})
    return r.status_code == 207


async def _mkdirs(c: httpx.AsyncClient, folder: str):
    built = ""
    for part in folder.split("/"):
        built = f"{built}/{part}" if built else part
        r = await c.request("MKCOL", _dav(built))
        if r.status_code not in (201, 405):  # 405 = already exists
            r.raise_for_status()


async def stat(path: str, transport=None) -> dict | None:
    """etag + last-modified of a file in his Nextcloud, or None if it is gone."""
    body = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
            "<d:prop><d:getetag/><d:getlastmodified/><oc:fileid/></d:prop></d:propfind>")
    async with _client(transport) as c:
        r = await c.request("PROPFIND", _dav(path), headers={"Depth": "0"}, content=body)
    if r.status_code != 207:
        return None
    t = r.text

    def tag(name):
        i = t.find(name + ">")
        return t[i + len(name) + 1: t.find("<", i + len(name) + 1)] if i >= 0 else None

    etag = html.unescape(tag("getetag") or "").strip('"')
    return {"etag": etag, "modified": tag("getlastmodified"), "fileid": tag("fileid")}


async def push(job: Job, force: bool = False, transport=None) -> dict:
    """Upload the document's current file. Raises Conflict if it was edited in Nextcloud
    since our last write (unless force=True). Returns the new `exported` record."""
    ext = "docx" if job.format == "docx" else "pdf"
    src = job.out / f"document.{ext}"
    if not src.exists():
        raise FileNotFoundError(src)

    prev = job.exported or {}
    path = None
    if prev.get("path", "").endswith("." + ext):
        remote = await stat(prev["path"], transport)
        if remote is not None:
            if not force and prev.get("etag") and remote["etag"] != prev["etag"]:
                raise Conflict(prev["path"], remote)
            path = prev["path"]  # overwrite our own file
        # remote is None → it was deleted or moved in Nextcloud; save it afresh below

    async with _client(transport) as c:
        if path is None:
            folder = _folder_for(job)
            await _mkdirs(c, folder)
            stem = _stem_for(job)
            path, n = f"{folder}/{stem}.{ext}", 1
            while await _exists(c, path):
                n += 1
                path = f"{folder}/{stem} ({n}).{ext}"
        else:
            await _mkdirs(c, path.rsplit("/", 1)[0])
        r = await c.put(_dav(path), content=src.read_bytes())
        r.raise_for_status()
    info = await stat(path, transport) or {}
    return {"path": path, "ext": ext, "at": time.time(), **info}


async def pull_copy(job: Job, transport=None) -> tuple[str, dict]:
    """Download the Nextcloud version into the job folder as nextcloud_copy.<ext>, plus a
    plain-text extraction nextcloud_copy.txt the agent can read. Returns (txt name, remote stat)."""
    prev = job.exported or {}
    path, ext = prev["path"], prev.get("ext", "pdf")
    async with _client(transport) as c:
        r = await c.get(_dav(path))
        r.raise_for_status()
    raw = job.work / f"nextcloud_copy.{ext}"
    raw.write_bytes(r.content)
    txt = job.work / "nextcloud_copy.txt"
    txt.write_text(_extract_text(raw))
    remote = await stat(path, transport) or {}
    return txt.name, remote


def _extract_text(f) -> str:
    if f.suffix == ".docx":
        from docx import Document

        d = Document(str(f))
        lines = [p.text for p in d.paragraphs]
        for t in d.tables:
            lines.append("")
            for row in t.rows:
                lines.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n".join(lines)
    try:
        return subprocess.run(["pdftotext", "-layout", str(f), "-"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "(could not read the PDF text)"


async def pull_signature(transport=None) -> str:
    """Refresh the cached signature from his Nextcloud if it changed there.
    Returns "updated", "unchanged", "missing" (no file in Nextcloud) or "off"."""
    if not configured():
        return "off"
    from io import BytesIO

    from PIL import Image, ImageOps

    path = config.NEXTCLOUD_SIGNATURE_PATH
    cache = config.ASSET_OVERRIDES / "signature.png"
    tag_file = config.ASSET_OVERRIDES / "signature.etag"
    remote = await stat(path, transport)
    if remote is None:
        return "missing"
    if cache.exists() and tag_file.exists() and tag_file.read_text() == remote["etag"]:
        return "unchanged"
    async with _client(transport) as c:
        r = await c.get(_dav(path))
        r.raise_for_status()
    raw = r.content
    if not raw.startswith((b"\x89PNG", b"\xff\xd8")):  # base64 text (images are blocked for his group)
        import base64

        raw = base64.b64decode(b"".join(raw.split()))
    img = ImageOps.exif_transpose(Image.open(BytesIO(raw))).convert("RGBA")
    img.thumbnail((1600, 1600))
    tmp = cache.with_suffix(".tmp.png")
    img.save(tmp)
    tmp.replace(cache)
    tag_file.write_text(remote["etag"])
    return "updated"
