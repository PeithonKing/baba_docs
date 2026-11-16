# baba_docs

A phone/tablet web app (PWA) for a school headmaster: send a photo, a file or a few words, and Claude
interviews him with tap-able question cards and turns it into a finished school document (letterhead
notice, question paper, invitation, anything else) as a PDF (typst) or an editable Word file. He can also
open an existing file from his Nextcloud or device and have it changed, mark changes on the page with
the tablet pen, and save to his Nextcloud where he chooses.

Built on the [Claude Agent SDK](https://docs.claude.com/en/docs/agent-sdk), FastAPI and typst.

## How it works
- **Templates** (`templates/<id>/`): `meta.json` (shown in the app), `GUIDE.md` (read by the agent),
  and the layout files. The letterhead has a typst version (`letterhead.typ`) and a Word version
  (`letterhead.docx`, **generated** by `build_docx.py` — never hand-edit it).
- **Agent** (`app/agent.py`, `app/prompt.md`): one Claude Code session per document, working in that
  document's folder, in **auto permission mode** (a classifier approves each action) with Read/Write/Edit/
  Bash. Behaviour is set by the prompt, not hard limits. Its own tools: `ask_user` (a card of several
  questions he answers one by one; options, "Other (write below)", `point_at` circles text on the page),
  `compile_pdf`, `render_docx`, `show_document`, `convert`, `set_title`, and `nc_list/search/download/
  save/move/delete` for his Nextcloud.
- **Nextcloud** (`app/nextcloud.py`): nothing is saved automatically; the agent asks him where and saves.
  Replacing a file that was edited in Nextcloud meanwhile is refused (ETag check) so the agent asks him.
- **Sources** (`app/sources.py`): every saved PDF/Word file is stamped `gcmv-job:<id>` (PDF keywords /
  Word identifier) and the document's sources are zipped to `.sources/<id>.zip` in his Nextcloud.
  "Edit existing file" uses the stamp to reopen (or restore) the document that made it; anything else
  becomes an edit job with the file in `original/` (`templates/edit/GUIDE.md`).
- **Memory** (`app/memory.py`): a day after he last touched a document, a one-shot Claude call writes a
  terse private note about him (prefs, habits, school facts); every 5 notes fold into a ~200-word
  summary that new chats get in their prompt. `./memory` shows / edits / resets it.
- **Device lock** (`app/guard.py`): requests from the internet (Cloudflare) need an enrolled device;
  LAN/Tailscale requests don't.
- **Signature**: not in this repo. It lives in his Nextcloud (`School Documents/Signature/signature.png`);
  the server pulls it on start and every 30 minutes into `data/assets/signature.png`. The agent asks
  him each time whether to sign.
- **One-time migration**: on first start the server renames `School Documents/Notices` →
  `School Documents/Letterhead` and updates saved paths (recorded in `data/migrations.json`).

## Run locally
```bash
virtualenv .venv && uv pip install -p .venv/bin/python -r requirements.txt
cp .env.example .env   # fill in
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765
```
Needs `typst`, `pdfinfo`/`pdftotext` (poppler) and a logged-in `claude` CLI.

## Deploy (Docker)
```bash
cp .env.example .env   # fill in
docker compose up -d --build
```
The container uses the **host's** Claude Code: `~/.local/share/claude` and `~/.local/bin` (binary,
read-only) and `~/.claude` (login) are bind-mounted at the same paths, and it runs as the host user.

## Devices and memory
```bash
./devices                 # list; ./devices add baba-tab (prints link + QR); remove NAME; reset
./memory                  # what it learned about him; ./memory edit | reflect-now | reset
```
Open the device link once on that device in Chrome, tap "Add this device", then Install app.

## License
MIT
