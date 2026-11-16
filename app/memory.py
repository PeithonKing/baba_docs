"""What the agent learns about him over time: its own terse, private notes.

- A day after he last worked on a document, a separate one-shot Claude call reads that
  document's chat and writes a short note (≤ ~100 words) about him: preferences, habits,
  school facts, what he finds hard. The document's chat itself is not touched.
- When 5 notes have piled up, they are folded into one summary (≤ ~200 words).
- Every new chat gets the summary + the unfolded notes in its system prompt.

Files (data/memory/): summary.md · notes.jsonl (all notes ever; "folded" once in the summary)
· archive/summary-<time>.md (earlier summaries). Edit summary.md by hand if it gets something wrong.
"""
import asyncio
import json
import logging
import time

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from . import config, jobs

log = logging.getLogger("gcmv.memory")
SUMMARY = config.MEMORY / "summary.md"
NOTES = config.MEMORY / "notes.jsonl"
ARCHIVE = config.MEMORY / "archive"
QUIET_HOURS = float(__import__("os").environ.get("GCMV_REFLECT_AFTER_HOURS", "24"))
FOLD_AT = 5

STYLE = """Write in terse note form: keywords, `key: value` lines, abbreviations; no full sentences, no
pleasantries. Facts and observed behaviour, not judgements ("skipped save-location q 2x", not
"careless"). Add counts like (3/4) when something repeats. Only things useful for helping him next
time: his preferences (language, signature, folders, wording, layout), how he works (types little,
voice, patience, what confused him, what he skips), what he decided himself, school facts (names,
classes, exam dates, recurring notices). Do not record document contents beyond such facts."""


def _notes() -> list[dict]:
    if not NOTES.exists():
        return []
    return [json.loads(l) for l in NOTES.read_text().splitlines() if l.strip()]


def _write_notes(notes: list[dict]):
    NOTES.write_text("".join(json.dumps(n, ensure_ascii=False) + "\n" for n in notes))


def context() -> str:
    """Block appended to the agent's system prompt."""
    summary = SUMMARY.read_text().strip() if SUMMARY.exists() else ""
    recent = [n for n in _notes() if not n.get("folded")]
    if not summary and not recent:
        return ""
    parts = ["\n\n# Your private notes about him (from earlier documents; terse; may be imperfect)"]
    if summary:
        parts.append(summary)
    for n in recent:
        parts.append(f"- [{time.strftime('%d %b', time.localtime(n['at']))}] {n['text']}")
    parts.append("Use these quietly to ask better questions. Still ask; don't assume he has learned something.")
    return "\n".join(parts)


def transcript(job: jobs.Job, after: int = 0, limit: int = 9000) -> str:
    lines = []
    for e in job.events(after):
        t = e.get("type")
        if t == "user" and (e.get("text") or e.get("photos")):
            att = f" [+{len(e.get('photos') or [])} file(s)]" if e.get("photos") else ""
            lines.append(f"HE: {e.get('text', '')}{att}")
        elif t == "assistant":
            lines.append(f"AGENT: {e['text']}")
        elif t == "question":
            for q in e.get("questions") or [{"question": e.get("question"), "options": e.get("options")}]:
                lines.append(f"AGENT ASKS: {q.get('question')} {q.get('options') or ''}")
        elif t == "answered":
            lines.append(f"HE ANSWERS: {e.get('answers')}" + (f" / wrote: {e['message']}" if e.get("message") else ""))
        elif t == "user" and e.get("answer"):
            lines.append(f"HE ANSWERS: {e.get('text')}")
        elif t == "saved":
            lines.append(f"(saved to Nextcloud: {e.get('path')})")
        elif t == "preview":
            lines.append("(document built)")
    text = "\n".join(lines)
    return text[-limit:]


async def _ask(prompt: str) -> str:
    opts = ClaudeAgentOptions(model=config.MODEL, tools=[], setting_sources=[], max_turns=1,
                              cli_path=config.CLAUDE_CLI, system_prompt="You keep concise private notes.")
    out = []
    async for m in query(prompt=prompt, options=opts):
        if isinstance(m, AssistantMessage):
            out += [b.text for b in m.content if isinstance(b, TextBlock)]
    return "\n".join(out).strip()


async def reflect(job: jobs.Job) -> str | None:
    """Write one note about this document's session. Returns the note (or None if nothing new)."""
    events = job.events(job.reflected_seq)
    if not any(e.get("type") in ("user", "answered") for e in events):
        return None
    meta = f"Document: {job.title} · template {job.template} · {job.format}"
    note = await _ask(
        f"You are the assistant that helped an elderly school headmaster (new to computers) make a document "
        f"in a document app. Here is what happened (his words, your questions, his answers):\n\n{meta}\n\n"
        f"{transcript(job, job.reflected_seq)}\n\n"
        f"What you already remember about him:\n{context() or '(nothing yet)'}\n\n"
        f"Write a NEW note of at most 100 words with what you learned today that is not already remembered. "
        f"{STYLE}\nIf nothing new, reply exactly: nothing new"
    )
    job.reflected_seq = events[-1]["seq"] if events else job.reflected_seq
    job.save(touch=False)
    if not note or note.lower().startswith("nothing new"):
        return None
    notes = _notes()
    notes.append({"job": job.id, "at": time.time(), "text": " ".join(note.split())[:900]})
    _write_notes(notes)
    return note


async def fold() -> bool:
    """Fold the unfolded notes into the summary once there are enough of them."""
    notes = _notes()
    fresh = [n for n in notes if not n.get("folded")]
    if len(fresh) < FOLD_AT:
        return False
    old = SUMMARY.read_text().strip() if SUMMARY.exists() else ""
    new = await _ask(
        "Merge these private notes about a school headmaster into ONE updated summary of at most 200 words.\n\n"
        f"Current summary:\n{old or '(none)'}\n\nNew notes:\n" + "\n".join(f"- {n['text']}" for n in fresh) +
        f"\n\n{STYLE}\nUse short sections: prefs · how he works · school facts · still unclear. Keep counts and "
        "update them. Drop anything newer notes contradict; drop one-off events unless they matter. "
        "Reply with the summary only."
    )
    if not new:
        return False
    ARCHIVE.mkdir(exist_ok=True)
    if old:
        (ARCHIVE / f"summary-{time.strftime('%Y%m%d-%H%M%S')}.md").write_text(old)
    SUMMARY.write_text(new.strip() + "\n")
    for n in notes:
        n["folded"] = True
    _write_notes(notes)
    return True


async def run_once() -> list[str]:
    done = []
    cutoff = time.time() - QUIET_HOURS * 3600
    for job in jobs.all_jobs():
        if job.updated > cutoff:
            continue
        evs = job.events(job.reflected_seq)
        if not evs:
            continue
        try:
            if await reflect(job):
                done.append(job.id)
        except Exception as e:
            log.warning("reflection on %s failed: %r", job.id, e)
    try:
        await fold()
    except Exception as e:
        log.warning("folding notes failed: %r", e)
    return done


async def loop():
    while True:
        await asyncio.sleep(10 * 60)
        try:
            done = await run_once()
            if done:
                log.info("reflected on %s", ", ".join(done))
        except Exception as e:
            log.warning("memory loop: %r", e)
        await asyncio.sleep(50 * 60)
