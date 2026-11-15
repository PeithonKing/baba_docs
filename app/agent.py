"""One live Claude agent per job, driven by the Claude Agent SDK.

The SDK runs the Claude Code CLI (logged in on this machine) as a subprocess, sandboxed to
the job's work folder. Our own tools (ask_user, compile_pdf, render_docx, set_title) run
in-process via an SDK MCP server and talk to the web UI through the job's event stream.
"""
import asyncio
import contextlib
import logging
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

from . import config, nextcloud, render
from .jobs import Job, load

log = logging.getLogger("gcmv.agent")
PROMPT = (Path(__file__).parent / "prompt.md").read_text()
PROTECTED = {"letterhead.typ", "template.typ", "letterhead.docx", "blank.docx", "GUIDE.md", "WORD_BLOCKS.md"}
BUILTIN = ["Read", "Write", "Edit", "Glob", "Grep"]
IDLE_SECONDS = 30 * 60

# Friendly activity lines for the chat (what he sees while Claude works)
ACTIVITY = {
    "Read": "Reading…",
    "Write": "Writing the document…",
    "Edit": "Making changes…",
    "Glob": "Looking at the template…",
    "Grep": "Looking at the template…",
    "mcp__gcmv__compile_pdf": "Making the PDF…",
    "mcp__gcmv__render_docx": "Making the Word file…",
}


def _killed(e: BaseException) -> bool:
    """CLI subprocess ended by a signal (SIGTERM/SIGINT/SIGKILL), i.e. a server stop, not a real failure."""
    if isinstance(e, asyncio.CancelledError):
        return True
    code = getattr(e, "exit_code", None)
    return code in (130, 137, 143, -2, -9, -15)


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
        self.sync_task: asyncio.Task | None = None
        self.sync_again = False

    # ---- events -----------------------------------------------------------
    @property
    def job(self) -> Job:
        return load(self.job_id)

    def emit(self, ev: dict) -> dict:
        ev = self.job.append_event(ev)
        for q in list(self.subscribers):
            q.put_nowait(ev)
        return ev

    # ---- tools ------------------------------------------------------------
    def _tools(self):
        @tool(
            "ask_user",
            "Ask the headmaster ONE question and wait for his answer. Give 2-5 short tap-able options "
            "when possible. Returns his answer as text.",
            {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                    "allow_text": {"type": "boolean", "description": "Also let him type a free answer"},
                },
                "required": ["question"],
            },
        )
        async def ask_user(args: dict[str, Any]):
            q = {"question": args["question"], "options": args.get("options") or [],
                 "allow_text": args.get("allow_text", not args.get("options"))}
            job = self.job
            job.pending_question = q
            job.save()
            self.answer = asyncio.get_running_loop().create_future()
            self.emit({"type": "question", **q})
            ans = None
            try:
                ans = await self.answer
            finally:
                self.answer = None
                if ans is not None:  # only a real answer closes it; a restart keeps it open
                    job = self.job
                    job.pending_question = None
                    job.save()
            return {"content": [{"type": "text", "text": f"He answered: {ans}"}]}

        @tool("compile_pdf", "Build the PDF from a typst source file in the working folder (default main.typ). "
              "Returns errors to fix, or success. The new PDF is shown to him automatically.",
              {"type": "object", "properties": {"file": {"type": "string"}}})
        async def compile_pdf(args: dict[str, Any]):
            ok, msg = await render.compile_pdf(self.job, args.get("file") or "main.typ")
            if ok:
                self._preview()
            return {"content": [{"type": "text", "text": msg}], "is_error": not ok}

        @tool("render_docx", "Build the Word document from a content JSON file in the working folder "
              "(default content.json). A PDF preview is shown to him automatically.",
              {"type": "object", "properties": {"file": {"type": "string"}}})
        async def render_docx(args: dict[str, Any]):
            ok, msg = await render.render_docx(self.job, args.get("file") or "content.json")
            if ok:
                self._preview()
            return {"content": [{"type": "text", "text": msg}], "is_error": not ok}

        @tool("set_title", "Set the short human title of this document (shown in his document list).",
              {"title": str})
        async def set_title(args: dict[str, Any]):
            job = self.job
            job.title = args["title"].strip()[:120] or job.title
            job.save()
            self.emit({"type": "title", "title": job.title})
            if job.preview_version and not job.exported:
                self.request_sync()  # first save waits for a real title (it becomes the file name)
            return {"content": [{"type": "text", "text": "ok"}]}

        return [ask_user, compile_pdf, render_docx, set_title]

    def _preview(self):
        job = self.job
        job.preview_version += 1
        job.save()
        self.emit({"type": "preview", "version": job.preview_version, "outputs": job.outputs()})
        if job.title != "Untitled" or job.exported:
            self.request_sync()

    # ---- Nextcloud sync (server side; the agent never uploads) ---------------------
    def _set_sync(self, **state) -> dict:
        job = self.job
        job.sync = {**(job.sync or {}), **state}
        job.save()
        self.emit({"type": "sync", **job.sync})
        return job.sync

    def request_sync(self, force: bool = False):
        job = self.job
        if not nextcloud.configured():
            if (job.sync or {}).get("state") != "off":
                self._set_sync(state="off", message="Nextcloud is not set up")
            return
        if not force and (job.sync or {}).get("state") == "kept":
            return  # he chose to keep the Nextcloud copy; wait until he decides otherwise
        if self.sync_task and not self.sync_task.done():
            self.sync_again = True
            return
        self.sync_task = asyncio.create_task(self._sync_loop(force))

    async def _sync_loop(self, force: bool):
        while True:
            self.sync_again = False
            job = self.job
            target = job.preview_version
            if not target or not job.outputs().get(job.format):
                return
            if not force and (job.sync or {}).get("version") == target and job.sync.get("state") == "saved":
                return
            self._set_sync(state="saving", message="Saving to Nextcloud…")
            try:
                rec = await nextcloud.push(job, force=force)
            except nextcloud.Conflict as c:
                first = (job.sync or {}).get("state") != "conflict"
                self._set_sync(state="conflict", message="Changed in Nextcloud", path=c.path)
                if first:
                    self.emit({"type": "sync_conflict", "path": c.path})
                return
            except Exception as e:
                log.warning("nextcloud sync failed for %s: %r", self.job_id, e)
                self._set_sync(state="error", message="Could not reach Nextcloud")
                return
            job = self.job
            job.exported = rec
            job.status = "exported"
            job.save()
            self._set_sync(state="saved", message="Saved to Nextcloud", path=rec["path"], version=target)
            force = False
            if not self.sync_again:
                return

    async def resolve_conflict(self, choice: str) -> str:
        """His answer to 'this file was changed in Nextcloud'. Returns a short status line."""
        job = self.job
        if choice == "overwrite":
            self.emit({"type": "sync_resolved", "choice": choice, "text": "Replaced with the new version"})
            self.request_sync(force=True)
            return "ok"
        if choice == "keep":
            self.emit({"type": "sync_resolved", "choice": choice, "text": "Left the Nextcloud copy as it is"})
            self._set_sync(state="kept", message="Nextcloud has newer edits")
            return "ok"
        if choice == "merge":
            self.emit({"type": "sync_resolved", "choice": choice, "text": "Bringing those changes in"})
            txt, remote = await nextcloud.pull_copy(job)
            job = self.job
            job.exported = {**(job.exported or {}), **remote}  # their version is now the base
            job.save()
            self._set_sync(state="saving", message="Merging changes…")
            self.start_turn(
                "(Automatic message from the app, not typed by him.) This document was edited directly "
                f"in Nextcloud after your last version. The edited version's text is in {txt} "
                f"(the file itself is nextcloud_copy.{(job.exported or {}).get('ext', 'pdf')}). "
                "Bring those edits into your source so the document matches the edited version, while keeping "
                "any changes he asked you for in this chat after the last save. Rebuild, then tell him in one "
                "or two sentences what was changed in Nextcloud."
            )
            return "ok"
        raise ValueError(choice)

    # ---- permissions: stay inside the job folder ----------------------------
    async def _can_use_tool(self, name: str, inp: dict, ctx: ToolPermissionContext):
        if name.startswith("mcp__gcmv__"):
            return PermissionResultAllow()
        if name not in BUILTIN:
            return PermissionResultDeny(message="Not available here.")
        work = self.job.work.resolve()
        raw = inp.get("file_path") or inp.get("path") or "."
        p = (work / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        if not p.is_relative_to(work):
            return PermissionResultDeny(message="Stay inside the working folder.")
        if name in ("Write", "Edit") and (p.name in PROTECTED or p.is_relative_to(work / "assets")
                                          or p.is_relative_to(work / "uploads")):
            return PermissionResultDeny(message=f"{p.name} must not be changed.")
        return PermissionResultAllow()

    # ---- lifecycle -------------------------------------------------------------
    async def _ensure_client(self):
        if self.client:
            return
        job = self.job
        opts = ClaudeAgentOptions(
            model=config.MODEL,
            system_prompt=PROMPT,
            cwd=str(job.work),
            tools=BUILTIN,
            allowed_tools=[],
            mcp_servers={"gcmv": create_sdk_mcp_server("gcmv", tools=self._tools())},
            can_use_tool=self._can_use_tool,
            setting_sources=[],  # don't load ~/.claude settings / CLAUDE.md
            resume=job.session_id,
            cli_path=config.CLAUDE_CLI,
            env={"MCP_TOOL_TIMEOUT": str(7 * 24 * 3600 * 1000)},  # ask_user may wait for hours
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
                job = self.job
                if job.preview_version and (job.sync or {}).get("version") != job.preview_version:
                    self.request_sync()  # e.g. it never set a title
            except (Exception, asyncio.CancelledError) as e:
                if self.shutting_down or _killed(e):
                    # Server stopping (systemd/tmux/Ctrl-C signal the whole process group, so the
                    # CLI often dies before our shutdown hook runs). Nothing is lost: the session
                    # is saved and an open question stays answerable.
                    log.info("job %s paused (%r)", self.job_id, e)
                    await self.close()
                    if not self.job.pending_question:
                        self.emit({"type": "interrupted", "text": "Stopped before finishing. Send a message to continue."})
                    return
                log.exception("turn failed")
                self.emit({"type": "error", "text": "Something went wrong. Please try again in a moment."})
                await self.close()
                log.error("error detail: %r", e)
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
                    if b.name == "Read" and "uploads/" in str(b.input.get("file_path", "")):
                        label = "Reading your photo…"
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

    def give_answer(self, text: str) -> bool:
        if self.answer and not self.answer.done():
            self.emit({"type": "user", "text": text, "answer": True})
            self.answer.set_result(text)
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
