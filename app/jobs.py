"""Job = one document. Lives in data/jobs/<id>/:
    job.json      metadata (template, format, title, status, session id, pending question)
    events.jsonl  chat history shown in the UI (one JSON event per line, with seq numbers)
    work/         the agent's sandbox: template files, uploads/, main.typ or content.json, out/
"""
import json
import secrets
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config


@dataclass
class Job:
    id: str
    template: str
    format: str  # "pdf" | "docx"
    title: str = "Untitled"
    status: str = "draft"  # draft | exported
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    session_id: str | None = None
    pending_question: dict | None = None
    preview_version: int = 0
    exported: dict | None = None  # last file we wrote to Nextcloud: {"path", "ext", "etag", "fileid", "at"}
    # Nextcloud sync state: {"state": "saving|saved|conflict|error|off", "message", "version"}
    # "version" = preview_version that is in Nextcloud.
    sync: dict | None = None

    @property
    def dir(self) -> Path:
        return config.JOBS / self.id

    @property
    def work(self) -> Path:
        return self.dir / "work"

    @property
    def out(self) -> Path:
        return self.work / "out"

    def save(self):
        self.updated = time.time()
        (self.dir / "job.json").write_text(json.dumps(asdict(self), indent=2))

    # ---- events -----------------------------------------------------------
    def _events_file(self) -> Path:
        return self.dir / "events.jsonl"

    def events(self, after: int = 0) -> list[dict]:
        f = self._events_file()
        if not f.exists():
            return []
        out = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        return [e for e in out if e["seq"] > after]

    def append_event(self, ev: dict) -> dict:
        f = self._events_file()
        seq = sum(1 for _ in f.open()) + 1 if f.exists() else 1
        ev = {"seq": seq, "t": time.time(), **ev}
        with f.open("a") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    # ---- outputs ----------------------------------------------------------
    def outputs(self) -> dict:
        o = {}
        for name in ("document.pdf", "document.docx"):
            if (self.out / name).exists():
                o[name.split(".")[1]] = name
        if (self.out / "preview.pdf").exists():
            o["preview"] = "preview.pdf"
        elif "pdf" in o:
            o["preview"] = "document.pdf"
        return o

    def public(self) -> dict:
        d = asdict(self)
        d.pop("session_id")
        d["outputs"] = self.outputs()
        return d


def templates() -> list[dict]:
    out = []
    for meta in sorted(config.TEMPLATES.glob("*/meta.json")):
        out.append(json.loads(meta.read_text()))
    return sorted(out, key=lambda m: m.get("order", 50))


_TEMPLATE_SKIP = shutil.ignore_patterns("meta.json", "build_docx.py", "font_samples.typ", "__pycache__")


def sync_template(job: Job):
    """Copy the current template files and assets into the job folder.

    Called when a job is created AND before every build, so editing an old document always
    uses today's letterhead, crest and signature. Template folders never contain the
    agent's own files (main.typ, content.json), so those are never overwritten.
    """
    src = config.TEMPLATES / job.template
    shutil.copytree(src, job.work, ignore=_TEMPLATE_SKIP, dirs_exist_ok=True)
    meta = json.loads((src / "meta.json").read_text())
    if "docx" in meta["formats"]:
        shutil.copy(config.TEMPLATES / "WORD_BLOCKS.md", job.work / "WORD_BLOCKS.md")
    shutil.copytree(config.ASSETS, job.work / "assets", dirs_exist_ok=True)  # crest (+ signature on a dev box)
    shutil.copytree(config.ASSET_OVERRIDES, job.work / "assets", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("*.etag"))  # signature from Nextcloud
    sig = job.work / "assets" / "signature.png"
    if not sig.exists():  # no signature anywhere yet: a blank image keeps documents building
        from PIL import Image

        Image.new("RGBA", (10, 4), (0, 0, 0, 0)).save(sig)


def create(template: str, fmt: str) -> Job:
    meta = next((t for t in templates() if t["id"] == template), None)
    if meta is None:
        raise ValueError(f"unknown template {template}")
    if fmt not in meta["formats"]:
        fmt = meta["formats"][0]
    job = Job(id=time.strftime("%Y%m%d-") + secrets.token_hex(3), template=template, format=fmt)
    sync_template(job)
    (job.work / "uploads").mkdir(exist_ok=True)
    job.out.mkdir(exist_ok=True)
    job.save()
    return job


def load(job_id: str) -> Job | None:
    if not job_id.replace("-", "").isalnum():
        return None
    f = config.JOBS / job_id / "job.json"
    if not f.exists():
        return None
    return Job(**json.loads(f.read_text()))


def all_jobs() -> list[Job]:
    jobs = [load(p.name) for p in config.JOBS.iterdir() if (p / "job.json").exists()]
    return sorted([j for j in jobs if j], key=lambda j: j.updated, reverse=True)
