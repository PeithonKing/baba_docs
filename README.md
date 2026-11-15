# baba_docs

A phone/tablet web app (PWA) for a school headmaster: send a photo or some text, and Claude turns it
into a finished school document (notice on the letterhead, question paper, or anything else) as a
PDF (typst) or an editable Word file. Every version is saved to his Nextcloud automatically.

Built on the [Claude Agent SDK](https://docs.claude.com/en/docs/agent-sdk), FastAPI and typst.

## How it works
- **Templates** (`templates/<id>/`): `meta.json` (shown in the app), `GUIDE.md` (read by the agent),
  and the layout files. The letterhead has a typst version (`letterhead.typ`) and a Word version
  (`letterhead.docx`, **generated** by `build_docx.py` — never hand-edit it).
- **Agent** (`app/agent.py`, `app/prompt.md`): one Claude session per document, sandboxed to that
  document's folder. Its own tools ask him questions (tap buttons), build the PDF/Word file and set the title.
- **Nextcloud** (`app/nextcloud.py`): after every build the server saves the file to
  `School Documents/<Notices|Question Papers|Other>/<title>_<YYYY-MM>.<ext>`. If the file was edited in
  Nextcloud since, it asks him: bring those changes in, replace, or leave it.
- **Device lock** (`app/guard.py`): requests from the internet (Cloudflare) need an enrolled device;
  LAN/Tailscale requests don't.
- **Signature**: not in this repo. It lives in his Nextcloud as a base64 text file
  (`School Documents/Signature/signature.b64.txt`; make one with `base64 -w0 signature.png > signature.b64.txt`).
  The server pulls it on start and every 30 minutes into `data/assets/signature.png`.

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

## Devices
```bash
docker compose exec baba-docs python manage.py add-device baba-phone --base https://docs.example.com
docker compose exec baba-docs python manage.py list
docker compose exec baba-docs python manage.py remove-device baba-phone
```
Open the printed link once on that device (Chrome), then "Add to Home screen".

## License
MIT
