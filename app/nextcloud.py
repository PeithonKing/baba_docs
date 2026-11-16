"""His Nextcloud, over WebDAV. Used by the agent's nc_* tools, the file picker and the signature.

Paths are relative to his files root, e.g. "School Documents/Letterhead/Notice_2026-11.pdf".

Nothing is saved automatically: the agent decides when and where to save (following the
guidelines in its prompt). The one hard rule kept in code: before replacing a file, its ETag
is compared with the one we last saw. If it changed, someone edited it in Nextcloud, and the
save stops with a Conflict so the agent can ask him what to do.
"""
import html
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote, unquote

import httpx

from . import config

BAD = '\\/:*?"<>|#%\n\r\t'
NS = {"d": "DAV:", "oc": "http://owncloud.org/ns"}
PROPS = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:prop>'
         "<d:getetag/><d:getlastmodified/><d:getcontentlength/><d:getcontenttype/><d:resourcetype/>"
         "<oc:fileid/></d:prop></d:propfind>")


class Conflict(Exception):
    """The file in Nextcloud was changed by someone else since we last saw it."""

    def __init__(self, path: str, remote: dict):
        super().__init__(path)
        self.path, self.remote = path, remote


def configured() -> bool:
    return bool(config.NEXTCLOUD_URL and config.NEXTCLOUD_USER and config.NEXTCLOUD_APP_PASSWORD)


def _client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        auth=(config.NEXTCLOUD_USER, config.NEXTCLOUD_APP_PASSWORD), timeout=120, transport=transport,
        headers={"User-Agent": "baba-docs"},
    )


def _root() -> str:
    return f"/remote.php/dav/files/{quote(config.NEXTCLOUD_USER)}/"


def _dav(path: str) -> str:
    """WebDAV URL for a path inside his files ("a/b c.pdf" → .../files/asish/a/b%20c.pdf)."""
    return config.NEXTCLOUD_URL.rstrip("/") + _root() + quote(norm(path), safe="/")


def norm(path: str) -> str:
    parts = [p for p in (path or "").replace("\\", "/").split("/") if p not in ("", ".")]
    if ".." in parts:
        raise ValueError("bad path")
    return "/".join(parts)


def clean_name(name: str) -> str:
    s = "".join(" " if c in BAD else c for c in name).strip(" .")
    return " ".join(s.split())[:120] or "Document"


def web_link(fileid: str | None, path: str | None = None) -> str:
    base = (config.NEXTCLOUD_PUBLIC_URL or config.NEXTCLOUD_URL).rstrip("/")
    if fileid:
        return f"{base}/f/{fileid}"
    return f"{base}/apps/files/?dir=/" + quote(norm(path or "").rsplit("/", 1)[0])


def _parse(xml_text: str) -> list[dict]:
    out = []
    root_href = _root()
    for r in ET.fromstring(xml_text).findall("d:response", NS):
        href = unquote(r.findtext("d:href", "", NS))
        rel = href.split(root_href, 1)[-1] if root_href in href else href
        p = r.find("d:propstat/d:prop", NS)
        if p is None:
            continue
        is_dir = p.find("d:resourcetype/d:collection", NS) is not None
        mod = p.findtext("d:getlastmodified", None, NS)
        try:
            mod = parsedate_to_datetime(mod).timestamp() if mod else None
        except (TypeError, ValueError):
            mod = None
        rel = rel.strip("/")
        out.append({
            "path": rel,
            "name": rel.rsplit("/", 1)[-1],
            "dir": is_dir,
            "size": int(p.findtext("d:getcontentlength", "0", NS) or 0),
            "type": p.findtext("d:getcontenttype", "", NS) or ("folder" if is_dir else ""),
            "modified": mod,
            "etag": html.unescape(p.findtext("d:getetag", "", NS) or "").strip('"'),
            "fileid": p.findtext("oc:fileid", None, NS),
        })
    return out


async def stat(path: str, transport=None) -> dict | None:
    """Info about one file or folder, or None if it does not exist."""
    async with _client(transport) as c:
        r = await c.request("PROPFIND", _dav(path), headers={"Depth": "0"}, content=PROPS)
    if r.status_code != 207:
        return None
    items = _parse(r.text)
    return items[0] if items else None


async def listdir(path: str = "", transport=None) -> list[dict]:
    """Folder contents: folders first, then files newest first."""
    async with _client(transport) as c:
        r = await c.request("PROPFIND", _dav(path), headers={"Depth": "1"}, content=PROPS)
    if r.status_code == 404:
        raise FileNotFoundError(path)
    r.raise_for_status()
    me = norm(path)
    items = [i for i in _parse(r.text) if i["path"] != me]
    return sorted(items, key=lambda i: (not i["dir"], i["name"].lower() if i["dir"] else -(i["modified"] or 0)))


async def search(term: str, transport=None, limit: int = 40) -> list[dict]:
    """Find files by name anywhere in his Nextcloud (WebDAV SEARCH)."""
    user = config.NEXTCLOUD_USER
    like = "%" + term.replace("%", "").replace("_", "") + "%"
    body = f"""<?xml version="1.0"?><d:searchrequest xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
<d:basicsearch><d:select><d:prop><d:getetag/><d:getlastmodified/><d:getcontentlength/><d:getcontenttype/>
<d:resourcetype/><oc:fileid/></d:prop></d:select>
<d:from><d:scope><d:href>/files/{html.escape(user)}</d:href><d:depth>infinity</d:depth></d:scope></d:from>
<d:where><d:like><d:prop><d:displayname/></d:prop><d:literal>{html.escape(like)}</d:literal></d:like></d:where>
<d:orderby><d:order><d:prop><d:getlastmodified/></d:prop><d:descending/></d:order></d:orderby>
<d:limit><d:nresults>{limit}</d:nresults></d:limit></d:basicsearch></d:searchrequest>"""
    async with _client(transport) as c:
        r = await c.request("SEARCH", config.NEXTCLOUD_URL.rstrip("/") + "/remote.php/dav/",
                            headers={"Content-Type": "text/xml"}, content=body)
    r.raise_for_status()
    return [i for i in _parse(r.text) if not i["path"].startswith(config.NEXTCLOUD_SOURCES)]


async def download(path: str, transport=None) -> tuple[bytes, dict]:
    async with _client(transport) as c:
        r = await c.get(_dav(path))
        if r.status_code == 404:
            raise FileNotFoundError(path)
        r.raise_for_status()
    return r.content, (await stat(path, transport) or {})


async def mkdirs(folder: str, transport=None):
    built = ""
    async with _client(transport) as c:
        for part in norm(folder).split("/"):
            if not part:
                continue
            built = f"{built}/{part}" if built else part
            r = await c.request("MKCOL", _dav(built))
            if r.status_code not in (201, 405):  # 405 = already exists
                r.raise_for_status()


async def upload(path: str, data: bytes, *, expect_etag: str | None = None, force: bool = False,
                 keep_both: bool = False, transport=None) -> dict:
    """Write a file. If it exists:
      keep_both  → save as "name (2).ext" instead
      expect_etag given and different (someone edited it) → Conflict, unless force
    Returns the new file's info (path, etag, fileid...)."""
    path = norm(path)
    folder, _, name = path.rpartition("/")
    remote = await stat(path, transport)
    if remote and keep_both:
        stem, dot, ext = name.rpartition(".")
        stem, ext = (stem, "." + ext) if dot else (name, "")
        n = 2
        while remote:
            path = f"{folder}/{stem} ({n}){ext}".lstrip("/")
            remote = await stat(path, transport)
            n += 1
    elif remote and expect_etag and remote["etag"] != expect_etag and not force:
        raise Conflict(path, remote)
    if folder:
        await mkdirs(folder, transport)
    async with _client(transport) as c:
        r = await c.put(_dav(path), content=data)
        r.raise_for_status()
    return await stat(path, transport) or {"path": path}


async def move(src: str, dst: str, transport=None) -> dict:
    dst = norm(dst)
    if dst.rpartition("/")[0]:
        await mkdirs(dst.rpartition("/")[0], transport)
    async with _client(transport) as c:
        r = await c.request("MOVE", _dav(src), headers={"Destination": _dav(dst), "Overwrite": "F"})
        r.raise_for_status()
    return await stat(dst, transport) or {"path": dst}


async def delete(path: str, transport=None):
    """Moves it to his Nextcloud trash bin (Nextcloud keeps deleted files for a while)."""
    async with _client(transport) as c:
        r = await c.request("DELETE", _dav(path))
        if r.status_code != 404:
            r.raise_for_status()


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
    raw, _ = await download(path, transport)
    img = ImageOps.exif_transpose(Image.open(BytesIO(raw))).convert("RGBA")
    img.thumbnail((1600, 1600))
    tmp = cache.with_suffix(".tmp.png")
    img.save(tmp)
    tmp.replace(cache)
    tag_file.write_text(remote["etag"])
    return "updated"


async def migrate_folders(transport=None) -> list[str]:
    """One-time renames of his folders (done once per server, see main.py). Returns what moved."""
    moved = []
    base = config.NEXTCLOUD_FOLDER
    for old, new in [("Notices", "Letterhead")]:
        src, dst = f"{base}/{old}", f"{base}/{new}"
        if await stat(src, transport) and not await stat(dst, transport):
            await move(src, dst, transport)
            moved.append(f"{src} → {dst}")
    return moved


def stamp() -> str:
    return time.strftime("%Y-%m")
