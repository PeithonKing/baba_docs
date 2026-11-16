# Planned changes (next batch)

Collected here, then built and deployed in one go.

Status: 1–6 done and deployed (build f0f6d538eb).

## 1. Faster loading (cache fingerprinted files)
- Files requested with `?v=<hash>` (app.js, style.css, icons, logos) → `Cache-Control: public,
  max-age=31536000, immutable`, so the browser loads them from its own cache with no round trip.
  A deploy changes the hash, hence the address, so a stale copy can't be used.
- `/`, `/api/*`, `/sw.js`, `/manifest.webmanifest` stay `no-cache` / `no-store` (the page is what
  brings in new versions).
- Where: the `no_edge_cache` middleware + `busted_asset` route in `app/main.py`.
- No offline cache in the service worker (decided: not worth it).

## 2. Home tiles: order and names
- Order: **Letterhead**, **Edit existing file**, **Question paper**, **New document**.
- "Other document" → **New document**; description → "Other kinds of documents"
  (wording to settle when building).
- Where: `order` / `name` / `description` in `templates/*/meta.json`.

## 3. Nextcloud picker: Back goes up a folder
- Now: the phone's Back (gesture/button) leaves the picker and lands on the home page, because the
  picker is an overlay that isn't part of the browser history.
- Want: Back goes to the parent folder; at the top level it closes the picker (back to where he was).
- How: push a history entry each time the picker opens or enters a folder (e.g. `history.pushState`
  with the folder path), and handle `popstate` to go up / close, instead of re-routing.

## 5. Layout modes, like Overleaf (tablet / computer)
- Top-bar switch: **Chat · Side by side · Document**. Phone keeps its two tabs.
- **Document** = full-screen reading on the tab, with pinch-zoom (shared with #6).
- Remember the choice per device (localStorage).
- In Document mode nothing may get lost: a small bottom pill "1 question waiting" (gentle pulse; tap →
  Side by side), and "Making your draft…" while the agent works.

## 6. Pen marking: full screen + zoom
- "Mark with pen" opens the document-only full-screen view (= Document mode + pen layer).
- Two-finger pinch zooms / pans; the pen draws (touch and pen are separate pointer types).
- Ink stored in page coordinates, so it stays put at any zoom; pages re-rendered sharper when zoomed in.
- Bar: Undo · Cancel · Send marks.

## 4. Nextcloud picker always starts at the top
- Every time the Nextcloud button is tapped, open at his Nextcloud root, not the last folder used.
- Where: `openPicker` in `web/app.js` (stop reusing `picker.path`).

# Batch 2 (built and tested locally, not deployed)

## 7. Send button stays usable while a question card is open
- It was disabled whenever the agent was busy, and the agent counts as busy while waiting for answers.
  Now it is disabled only when busy *and* no card is open (the message goes with his answers).

## 8. Date / time questions + Indian time everywhere
- `ask_user` question `type: "date" | "time"`: a calendar / clock instead of options (quick picks
  optional). Answers come back like "Thursday, 19 November 2026" and "3:00 PM".
- Server, agent shell and file times forced to Asia/Kolkata; prompt says all times are IST and to
  never mention time zones; "today" in the first message includes the weekday.

## 9. Pen marking: pen only writes, fingers only move/zoom; pen-button eraser
- While marking, fingers are handled with pointer events (pointerType "touch") so the pen can
  never pan or zoom; the pen never reaches that code.
- Holding the pen's side button (or using its eraser end) erases any line it touches.
