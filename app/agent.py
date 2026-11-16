"""One live Claude agent per job, driven by the Claude Agent SDK.

The SDK runs the Claude Code CLI (logged in on this machine) as a subprocess in the job's work
folder, in auto permission mode (a classifier approves each action) with Bash available. How it
should behave is set by the prompt (prompt.md + the template's GUIDE.md), not by hard limits.
Our own tools (questions, builds, Nextcloud) run in-process via an SDK MCP server and talk to
the web UI through the job's event stream.
"""
import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

from . import config, memory, nextcloud, render, sources
from .jobs import Job, load

log = logging.getLogger("gcmv.agent")
PROMPT = (Path(__file__).parent / "prompt.md").read_text()
BUILTIN = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
IDLE_SECONDS = 30 * 60
DOC_EXT = {".pdf", ".docx"}

# Friendly activity lines for the chat (what he sees while Claude works)
ACTIVITY = {
    "Read": "Reading…",
    "Write": "Writing…",
    "Edit": "Making changes…",
    "Bash": "Working on it…",
    "Glob": "Looking…",
    "Grep": "Looking…",
    "mcp__gcmv__compile_pdf": "Making the PDF…",
    "mcp__gcmv__render_docx": "Making the Word file…",
    "mcp__gcmv__show_document": "Getting the document ready…",
    "mcp__gcmv__convert": "Opening the file…",
    "mcp__gcmv__nc_list": "Looking in Nextcloud…",
    "mcp__gcmv__nc_search": "Looking in Nextcloud…",
    "mcp__gcmv__nc_download": "Opening from Nextcloud…",
    "mcp__gcmv__nc_save": "Saving to Nextcloud…",
    "mcp__gcmv__nc_move": "Moving in Nextcloud…",
    "mcp__gcmv__nc_delete": "Removing from Nextcloud…",
}


def _killed(e: BaseException) -> bool:
    """CLI subprocess ended by a signal (SIGTERM/SIGINT/SIGKILL), i.e. a server stop, not a real failure."""
    if isinstance(e, asyncio.CancelledError):
        return True
    code = getattr(e, "exit_code", None)
    return code in (130, 137, 143, -2, -9, -15)


def _text(s: str, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": s}], "is_error": error}


def format_answers(questions: list[dict], answers: list, message: str = "") -> str:
    """His answers to a question card, as text for the agent."""
    lines = []
    for i, q in enumerate(questions):
        a = answers[i] if i < len(answers) else None
        if isinstance(a, list):
            a = ", ".join(str(x) for x in a if str(x).strip())
        a = (str(a).strip() if a is not None else "") or "(not answered)"
        lines.append(f"{i + 1}. {q.get('question', '')}\n   → {a}")
    out = "His answers:\n" + "\n".join(lines)
    if message:
        out += f"\n\nInstead of finishing the questions he wrote this message:\n<<<\n{message}\n>>>"
    return out


class AgentSession:
    def __init__(self, job: Job):
        self.job_id = job.id
        self.client: ClaudeSDKClient | None = None
        self.subscribers: set[asyncio.Queue] = set()
        self.turn_lock = asyncio.Lock()
        self.busy = False
        self.answer: asyncio.Future | None = None
        self.last_used = time.time()
        self.task: asyncio.Task | None = None
        self.shutting_down = False  # server is stopping: not an error, keep the open question

    # ---- events -----------------------------------------------------------
    @property
    def job(self) -> Job:
        return load(self.job_id)

    def emit(self, ev: dict) -> dict:
        ev = self.job.append_event(ev)
        for q in list(self.subscribers):
            q.put_nowait(ev)
        return ev

    def _local(self, rel: str) -> Path:
        work = self.job.work.resolve()
        p = Path(rel)
        return (p if p.is_absolute() else work / p).resolve()

    # ---- tools ------------------------------------------------------------
    def _tools(self):
        Q = {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Short, plain question."},
                "type": {"type": "string", "enum": ["choice", "date", "time"],
                         "description": "choice (default): tap an option. date: he picks a day on a calendar; "
                         "the answer comes as e.g. 'Thursday, 19 November 2026'. time: a clock, answer like '3:00 PM'. "
                         "For date/time, options are optional quick picks shown above the picker."},
                "why": {"type": "string", "description": "Optional one short line under the question: why it matters."},
                "options": {"type": "array", "items": {"type": "string"}, "maxItems": 8,
                            "description": "Tap-able answers (short). Leave empty only if he must type."},
                "multiple": {"type": "boolean", "description": "He may pick several options."},
                "other": {"type": "boolean", "description": "Add 'Other (write below)' so he can type his own answer."},
                "point_at": {"type": "string", "description": "Exact text on the current document page to circle "
                             "in red while this question is shown (e.g. the date). Optional."},
                "on": {"type": "string", "enum": ["new", "original"],
                       "description": "Which document point_at refers to (default: new)."},
            },
            "required": ["question"],
        }

        @tool(
            "ask_user",
            "Ask the headmaster one or more questions on a tap-able card and wait for all his answers. "
            "He sees them one at a time and they come back together. Use for EVERY question to him.",
            {
                "type": "object",
                "properties": {
                    "questions": {"type": "array", "items": Q, "minItems": 1, "maxItems": 12},
                    "intro": {"type": "string", "description": "Optional one line shown above the card."},
                },
                "required": ["questions"],
            },
        )
        async def ask_user(args: dict[str, Any]):
            qs = args.get("questions") or ([{k: args[k] for k in ("question", "options") if k in args}]
                                           if args.get("question") else [])
            if not qs:
                return _text("Give at least one question.", True)
            for q in qs:
                q["options"] = [str(o) for o in (q.get("options") or [])]
                if q.get("type") in ("date", "time"):
                    q["other"] = False
                elif not q["options"]:
                    q["other"] = True
            card = {"questions": qs, "intro": args.get("intro") or ""}
            job = self.job
            job.pending_question = card
            job.save()
            self.answer = asyncio.get_running_loop().create_future()
            self.emit({"type": "question", **card})
            got = None
            try:
                got = await self.answer
            finally:
                self.answer = None
                if got is not None:  # only a real answer closes it; a restart keeps it open
                    job = self.job
                    job.pending_question = None
                    job.save()
            return _text(format_answers(qs, got.get("answers") or [], got.get("message") or ""))

        @tool("compile_pdf", "Build the PDF from a typst source file in the working folder (default main.typ). "
              "Returns errors to fix, or success. The new PDF is shown to him automatically.",
              {"type": "object", "properties": {"file": {"type": "string"}}})
        async def compile_pdf(args: dict[str, Any]):
            ok, msg = await render.compile_pdf(self.job, args.get("file") or "main.typ")
            if ok:
                self._preview("pdf")
            return _text(msg, not ok)

        @tool("render_docx", "Build the Word document from a content JSON file in the working folder "
              "(default content.json) using this template's Word layout (or `layout`: letterhead | blank, in an "
              "edit job). A preview is shown to him automatically.",
              {"type": "object", "properties": {"file": {"type": "string"},
                                                "layout": {"type": "string", "enum": ["letterhead", "blank"]}}})
        async def render_docx(args: dict[str, Any]):
            ok, msg = await render.render_docx(self.job, args.get("file") or "content.json", args.get("layout"))
            if ok:
                self._preview("docx")
            return _text(msg, not ok)

        @tool("show_document", "Make a PDF or Word file you produced yourself (e.g. a Word file edited with "
              "python-docx) the current document: it is shown to him and becomes what he downloads/shares. "
              "For a Word document give the .docx itself (the app makes its preview); do not convert it first.",
              {"file": str})
        async def show_document(args: dict[str, Any]):
            src = self._local(args["file"])
            if not src.exists() or src.suffix.lower() not in DOC_EXT:
                return _text("Give an existing .pdf or .docx file.", True)
            job = self.job
            ext = src.suffix.lower()[1:]
            data = src.read_bytes()  # read first: src may itself be one of the files cleared below
            job.out.mkdir(exist_ok=True)
            for old in ("document.pdf", "document.docx", "preview.pdf"):
                (job.out / old).unlink(missing_ok=True)
            dst = job.out / f"document.{ext}"
            dst.write_bytes(data)
            note = ""
            if ext == "docx":
                ok, msg = await render.docx_to_pdf(dst, job.out / "preview.pdf")
                note = "" if ok else f" (no preview: {msg})"
            self._preview(ext)
            return _text(f"Shown to him as the current document{note}.")

        @tool("convert", "Convert an office file in the working folder with LibreOffice/Collabora: "
              "e.g. .doc/.odt → docx, docx → pdf. Returns the new file's path.",
              {"type": "object", "properties": {"file": {"type": "string"}, "to": {"type": "string", "enum": ["docx", "pdf", "odt"]}},
               "required": ["file", "to"]})
        async def convert(args: dict[str, Any]):
            src = self._local(args["file"])
            if not src.exists():
                return _text("No such file.", True)
            dst = src.with_suffix("." + args["to"])
            ok, msg = await render.convert(src, dst)
            return _text(str(dst.relative_to(self.job.work.resolve())) if ok else f"failed: {msg}", not ok)

        @tool("set_title", "Set the short human title of this document (shown in his document list).", {"title": str})
        async def set_title(args: dict[str, Any]):
            job = self.job
            job.title = args["title"].strip()[:120] or job.title
            job.save()
            self.emit({"type": "title", "title": job.title})
            return _text("ok")

        # ---- Nextcloud --------------------------------------------------------
        def need_nc():
            return None if nextcloud.configured() else _text("Nextcloud is not set up on this server.", True)

        def brief(i: dict) -> str:
            when = time.strftime("%d %b %Y %H:%M", time.localtime(i["modified"])) if i.get("modified") else ""
            kind = "folder" if i["dir"] else f"{i['size'] // 1024} KB"
            return f"{'📁' if i['dir'] else '  '} {i['path']}   ({kind}, {when})"

        @tool("nc_list", "List a folder in his Nextcloud (path relative to his files root; '' = root).",
              {"type": "object", "properties": {"path": {"type": "string"}}})
        async def nc_list(args: dict[str, Any]):
            if e := need_nc():
                return e
            try:
                items = await nextcloud.listdir(args.get("path") or "")
            except FileNotFoundError:
                return _text("No such folder.", True)
            items = [i for i in items if not i["path"].startswith(config.NEXTCLOUD_SOURCES)]
            return _text("\n".join(brief(i) for i in items) or "(empty folder)")

        @tool("nc_search", "Find files or folders by name anywhere in his Nextcloud.", {"name": str})
        async def nc_search(args: dict[str, Any]):
            if e := need_nc():
                return e
            items = await nextcloud.search(args["name"])
            return _text("\n".join(brief(i) for i in items) or "Nothing found.")

        @tool("nc_download", "Copy a file from his Nextcloud into the working folder (nextcloud/<name>) so you "
              "can read or edit it. Remembers its version, so replacing it later can detect edits made meanwhile.",
              {"path": str})
        async def nc_download(args: dict[str, Any]):
            if e := need_nc():
                return e
            try:
                data, info = await nextcloud.download(args["path"])
            except FileNotFoundError:
                return _text("No such file.", True)
            job = self.job
            dest = job.work / "nextcloud" / info.get("name", Path(args["path"]).name)
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(data)
            job.nc_seen[info.get("path") or args["path"]] = info.get("etag")
            job.save()
            return _text(f"Saved as {dest.relative_to(job.work)} ({len(data) // 1024} KB).")

        @tool(
            "nc_save",
            "Save one or more files from the working folder to his Nextcloud. Folders are created as needed. "
            "Saving the current document (out/document.pdf or .docx) also keeps its sources so it can be edited "
            "again later. mode: 'new' = only if nothing is there yet; 'replace' = overwrite (refused if the file "
            "was changed in Nextcloud since you last saw it, unless force=true); 'keep_both' = save as 'name (2)'.",
            {
                "type": "object",
                "properties": {
                    "files": {"type": "array", "minItems": 1, "items": {
                        "type": "object",
                        "properties": {"file": {"type": "string", "description": "local file in the working folder"},
                                       "path": {"type": "string", "description": "full Nextcloud path incl. file name"}},
                        "required": ["file", "path"]}},
                    "mode": {"type": "string", "enum": ["new", "replace", "keep_both"]},
                    "force": {"type": "boolean"},
                },
                "required": ["files", "mode"],
            },
        )
        async def nc_save(args: dict[str, Any]):
            if e := need_nc():
                return e
            mode, force = args["mode"], bool(args.get("force"))
            results, saved_doc = [], False
            for item in args["files"]:
                job = self.job
                src = self._local(item["file"])
                path = nextcloud.norm(item["path"])
                if not src.is_file():
                    results.append(f"✗ {item['file']}: no such file")
                    continue
                is_doc = src.parent == job.out.resolve() and src.name.startswith("document.")
                data = sources.stamped(job, src) if src.suffix.lower() in DOC_EXT else src.read_bytes()
                known = job.nc_seen.get(path) or next((s.get("etag") for s in reversed(job.saved) if s["path"] == path), None)
                try:
                    if mode == "new" and await nextcloud.stat(path):
                        results.append(f"✗ {path}: a file with this name already exists there (not saved). "
                                       "Ask him: replace it, keep both, or another name.")
                        continue
                    # replace: if we never saw this file's version there is nothing to compare; it overwrites
                    info = await nextcloud.upload(path, data, expect_etag=known if mode == "replace" else None,
                                                  force=force, keep_both=mode == "keep_both")
                except nextcloud.Conflict as c:
                    when = time.strftime("%d %b %H:%M", time.localtime(c.remote.get("modified") or time.time()))
                    results.append(f"✗ {path}: CHANGED IN NEXTCLOUD since you last saw it (edited {when}); not saved. "
                                   "Ask him what to do: bring those changes in (nc_download it and merge), "
                                   "replace anyway (force=true), or save yours as a copy (keep_both).")
                    continue
                except Exception as e:
                    log.warning("nc_save %s failed: %r", path, e)
                    results.append(f"✗ {path}: could not reach Nextcloud ({e.__class__.__name__})")
                    continue
                job = self.job
                rec = {"path": info.get("path", path), "fileid": info.get("fileid"), "etag": info.get("etag"),
                       "at": time.time(), "version": job.preview_version if is_doc else None}
                job.saved.append(rec)
                job.nc_seen[rec["path"]] = rec["etag"]
                if is_doc:
                    job.status = "exported"
                    saved_doc = True
                job.save()
                self.emit({"type": "saved", "path": rec["path"], "fileid": rec["fileid"], "doc": is_doc,
                           "save_state": job.save_state()})
                results.append(f"✓ saved {rec['path']}")
            if saved_doc:
                try:
                    await sources.push(self.job)
                except Exception as e:
                    log.warning("sources zip for %s failed: %r", self.job_id, e)
            return _text("\n".join(results), all(r.startswith("✗") for r in results))

        @tool("nc_move", "Move or rename a file/folder in his Nextcloud (only when he asked for it).",
              {"from": str, "to": str})
        async def nc_move(args: dict[str, Any]):
            if e := need_nc():
                return e
            try:
                info = await nextcloud.move(args["from"], args["to"])
            except Exception as e:
                return _text(f"failed: {e!r}", True)
            return _text(f"moved to {info.get('path')}")

        @tool("nc_delete", "Delete a file/folder in his Nextcloud (goes to his Nextcloud trash). Only when he "
              "clearly asked for it.", {"path": str})
        async def nc_delete(args: dict[str, Any]):
            if e := need_nc():
                return e
            await nextcloud.delete(args["path"])
            return _text("deleted (it is in his Nextcloud trash for a while)")

        return [ask_user, compile_pdf, render_docx, show_document, convert, set_title,
                nc_list, nc_search, nc_download, nc_save, nc_move, nc_delete]

    def _preview(self, fmt: str | None = None):
        job = self.job
        job.preview_version += 1
        if fmt:
            job.format = fmt
        job.save()
        self.emit({"type": "preview", "version": job.preview_version, "outputs": job.outputs(),
                   "format": job.format, "save_state": job.save_state()})

    # ---- lifecycle -------------------------------------------------------------
    async def _ensure_client(self):
        if self.client:
            return
        job = self.job
        tools = self._tools()
        bin_dir = str(Path(sys.executable).parent)  # python3 with python-docx, openpyxl, pypdf, pillow
        opts = ClaudeAgentOptions(
            model=config.MODEL,
            effort=config.EFFORT,
            permission_mode=config.PERMISSION_MODE,
            system_prompt=PROMPT + memory.context(),
            cwd=str(job.work),
            tools=BUILTIN,
            allowed_tools=[f"mcp__gcmv__{t.name}" for t in tools],
            mcp_servers={"gcmv": create_sdk_mcp_server("gcmv", tools=tools)},
            setting_sources=[],  # don't load ~/.claude settings / CLAUDE.md
            resume=job.session_id,
            cli_path=config.CLAUDE_CLI,
            env={
                "MCP_TOOL_TIMEOUT": str(7 * 24 * 3600 * 1000),  # a question card may wait for hours
                "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
                "NEXTCLOUD_APP_PASSWORD": "",  # Nextcloud goes through our tools
                "TZ": "Asia/Kolkata",
            },
            stderr=lambda line: log.debug("cli: %s", line),
        )
        self.client = ClaudeSDKClient(opts)
        await self.client.connect()

    async def close(self):
        if self.answer and not self.answer.done():
            self.answer.cancel()
        if self.client:
            with contextlib.suppress(Exception):
                await self.client.disconnect()
        self.client = None

    def start_turn(self, text: str):
        """Run one user turn in the background; progress goes out as events."""
        self.task = asyncio.create_task(self._turn(text))

    async def _turn(self, text: str):
        async with self.turn_lock:
            self.busy, self.last_used = True, time.time()
            self.emit({"type": "busy", "busy": True})
            try:
                await self._ensure_client()
                await self.client.query(text)
                async for msg in self.client.receive_response():
                    self._handle(msg)
            except (Exception, asyncio.CancelledError) as e:
                if self.shutting_down or _killed(e):
                    # Server stopping (signals hit the whole process group, so the CLI often dies
                    # before our shutdown hook runs). Nothing is lost: the session is saved and an
                    # open question stays answerable.
                    log.info("job %s paused (%r)", self.job_id, e)
                    await self.close()
                    if not self.job.pending_question:
                        self.emit({"type": "interrupted", "text": "Stopped before finishing. Send a message to continue."})
                    return
                log.exception("turn failed")
                self.emit({"type": "error", "text": "Something went wrong. Please try again in a moment."})
                await self.close()
            finally:
                self.busy, self.last_used = False, time.time()
                self.emit({"type": "busy", "busy": False})

    def _handle(self, msg):
        if isinstance(msg, SystemMessage) and msg.subtype == "init":
            sid = msg.data.get("session_id")
            if sid:
                job = self.job
                job.session_id = sid
                job.save()
        elif isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock) and b.text.strip():
                    self.emit({"type": "assistant", "text": b.text.strip()})
                elif isinstance(b, ToolUseBlock):
                    label = ACTIVITY.get(b.name)
                    target = json.dumps(b.input, ensure_ascii=False)
                    if b.name in ("Read", "Bash") and ("uploads/" in target or "original/" in target):
                        label = "Reading your file…"
                    if label:
                        self.emit({"type": "activity", "text": label})
        elif isinstance(msg, ResultMessage):
            job = self.job
            if msg.session_id:
                job.session_id = msg.session_id
            job.save()
            log.info("turn done job=%s turns=%s cost=%s", job.id, msg.num_turns, msg.total_cost_usd)

    @property
    def question_live(self) -> bool:
        return bool(self.answer and not self.answer.done())

    def give_answer(self, answers: list, message: str = "") -> bool:
        if self.answer and not self.answer.done():
            self.emit({"type": "answered", "answers": answers, "message": message})
            self.answer.set_result({"answers": answers, "message": message})
            return True
        return False


class Sessions:
    def __init__(self):
        self.by_job: dict[str, AgentSession] = {}

    def get(self, job: Job) -> AgentSession:
        s = self.by_job.get(job.id)
        if not s:
            s = self.by_job[job.id] = AgentSession(job)
        return s

    async def reap_idle(self):
        while True:
            await asyncio.sleep(60)
            now = time.time()
            for jid, s in list(self.by_job.items()):
                if not s.busy and not s.subscribers and now - s.last_used > IDLE_SECONDS:
                    await s.close()
                    self.by_job.pop(jid, None)

    async def close_all(self):
        for s in self.by_job.values():
            s.shutting_down = True
        for s in self.by_job.values():
            await s.close()
            if s.task and not s.task.done():
                with contextlib.suppress(BaseException):
                    await asyncio.wait_for(s.task, 5)
