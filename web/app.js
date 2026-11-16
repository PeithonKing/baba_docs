// Single-page app: #/ home · #/new/<tpl> format · #/new/<tpl>/<fmt> content · #/open · #/job/<id>
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const icon = (name, cls) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  if (cls) s.setAttribute("class", cls);
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", `#i-${name}`); s.append(u); return s;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

// What he is holding. The pen is offered only on a tablet (touch screen, large).
const DEVICE = (() => {
  const touch = navigator.maxTouchPoints > 0;
  const short = Math.min(screen.width, screen.height);
  if (!touch) return "computer";
  return short >= 600 ? "tablet" : "phone";
})();
const PEN_OK = DEVICE === "tablet" || new URLSearchParams(location.search).has("pen");

let templates = [];
let job = null;           // current job object
let stream = null;        // EventSource
let lastSeq = 0;
let status = null;        // the single "working…" line
let busy = false;
let view = "new";         // document side: "new" | "original"
const attach = { content: { files: [], nc: [] }, chat: { files: [], nc: [] } };
let attachTarget = "content";

function toast(msg, ms = 3500) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), ms);
}
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.text()) || r.status);
  return r.json();
}
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
function show(id, title) {
  for (const s of $$(".screen")) s.hidden = s.id !== id;
  $("#top").hidden = id === "home";
  $("#top").classList.toggle("wide", id === "job");
  $("#top-title").textContent = title || "";
  if (id !== "job") $("#doc-actions").hidden = true;
  closeMenus();
}
function fmtDate(t) {
  return new Date(t * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
function row({ ico, img, title, sub, right, onClick, cls }) {
  const li = el("li"), b = el("button", "row" + (cls ? " " + cls : ""));
  if (img) b.append(img);
  else if (ico) b.append(icon(ico, "ico"));
  const t = el("span", "t"); t.append(el("b", null, title));
  if (sub) t.append(el("span", null, sub));
  b.append(t);
  if (right !== null) b.append(right || icon("chev", "chev"));
  b.onclick = onClick; li.append(b); return li;
}

// ---------------- routing ----------------
window.addEventListener("hashchange", route);
$("#back").onclick = () => (history.length > 1 ? history.back() : (location.hash = "#/"));

async function route() {
  if (stream) { stream.close(); stream = null; }
  closePicker();
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (!templates.length) templates = await api("/api/templates");
  if (parts[0] === "open") return showOpen();
  if (parts[0] === "new" && parts[1]) {
    const tpl = templates.find((t) => t.id === parts[1]);
    if (!tpl) return (location.hash = "#/");
    if (tpl.picker) return (location.hash = "#/open");
    if (!parts[2] && tpl.formats.length > 1) return show("format", tpl.name);
    return showContent(tpl, parts[2] || tpl.formats[0]);
  }
  if (parts[0] === "job" && parts[1]) return openJob(parts[1]);
  return showHome();
}

// ---------------- home ----------------
async function showHome() {
  show("home");
  const box = $("#templates"); box.innerHTML = "";
  for (const t of templates) {
    const b = el("button", "tile");
    b.append(icon(t.icon), el("b", null, t.name), el("span", null, t.description));
    b.onclick = () => (location.hash = t.picker ? "#/open" : `#/new/${t.id}`);
    box.append(b);
  }
  const list = await api("/api/jobs");
  $("#recent-h").hidden = !list.length;
  const ul = $("#recent"); ul.innerHTML = "";
  for (const j of list) {
    const tname = (templates.find((t) => t.id === j.template) || {}).name || j.template;
    const st = j.save_state;
    ul.append(row({
      title: j.title,
      sub: `${tname} · ${j.format === "docx" ? "Word" : "PDF"} · ${fmtDate(j.updated)}`,
      right: el("span", st === "saved" ? "state saved" : st === "changed" ? "state warn" : "state",
        st === "saved" ? "Saved" : st === "changed" ? "Not saved" : "Draft"),
      onClick: () => (location.hash = `#/job/${j.id}`),
    }));
  }
}

// ---------------- format ----------------
for (const b of $$("[data-format]"))
  b.onclick = () => (location.hash = location.hash.replace(/\/$/, "") + "/" + b.dataset.format);

// ---------------- attachments (camera, gallery, files, Nextcloud) ----------------
function pickSource(target, src) {
  attachTarget = target;
  closeMenus();
  if (src === "nextcloud") return openPicker({ mode: "attach" });
  $(`#in-${src}`).click();
}
for (const box of $$("[data-attach]"))
  for (const b of box.querySelectorAll("[data-src]"))
    b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); pickSource(box.dataset.attach, b.dataset.src); };
for (const id of ["camera", "gallery", "files"]) {
  const inp = $(`#in-${id}`);
  inp.onchange = () => { attach[attachTarget].files.push(...inp.files); inp.value = ""; renderAttach(attachTarget); };
}
function renderAttach(target) {
  const box = target === "content" ? $("#content-att") : $("#chat-att");
  const a = attach[target];
  box.innerHTML = "";
  a.files.forEach((f, i) => {
    const rm = () => { a.files.splice(i, 1); renderAttach(target); };
    if (f.type.startsWith("image/")) {
      const img = el("img"); img.src = URL.createObjectURL(f); img.alt = "Photo, tap to remove"; img.onclick = rm;
      box.append(img);
    } else box.append(fileChip(f.name, rm));
  });
  a.nc.forEach((f, i) => box.append(fileChip(f.name, () => { a.nc.splice(i, 1); renderAttach(target); }, true)));
}
function fileChip(name, onRemove, nc) {
  const c = el("button", "fchip");
  if (nc) { const i = el("img", "nc"); i.src = "/static/nextcloud.svg"; i.alt = ""; c.append(i); }
  else c.append(icon("file"));
  c.append(el("span", null, name), icon("x", "x"));
  c.type = "button"; c.title = "Tap to remove"; c.onclick = onRemove;
  return c;
}
function attachForm(fd, target) {
  for (const f of attach[target].files) fd.append("photos", f);
  for (const f of attach[target].nc) fd.append("nc_paths", f.path);
  attach[target] = { files: [], nc: [] }; renderAttach(target);
}

// ---------------- content ----------------
function showContent(tpl, fmt) {
  show("content", tpl.name);
  attach.content = { files: [], nc: [] }; renderAttach("content");
  $("#content-text").value = "";
  $("#start").onclick = async () => {
    const text = $("#content-text").value.trim();
    $("#start").disabled = true; $("#start").textContent = "Starting…";
    const fd = new FormData();
    fd.append("template", tpl.id); fd.append("format", fmt); fd.append("text", text); fd.append("device", DEVICE);
    attachForm(fd, "content");
    try {
      const j = await api("/api/jobs", { method: "POST", body: fd });
      location.replace(`#/job/${j.id}`);
    } catch { toast("Could not start. Please try again."); }
    finally { $("#start").disabled = false; $("#start").textContent = "Start"; }
  };
}

// ---------------- edit existing file ----------------
function showOpen() {
  show("open", "Edit existing file");
  $("#open-busy").hidden = true;
}
$("#open-nc").onclick = () => openPicker({ mode: "open" });
$("#open-device").onclick = () => $("#in-open").click();
$("#in-open").onchange = () => { const f = $("#in-open").files[0]; $("#in-open").value = ""; if (f) startOpen({ file: f }); };
async function startOpen({ file, path }) {
  closePicker();
  $("#open-busy").hidden = false;
  const fd = new FormData(); fd.append("device", DEVICE);
  if (file) fd.append("file", file); else fd.append("nc_path", path);
  try {
    const r = await api("/api/open", { method: "POST", body: fd });
    if (r.reopened) toast("This document was made here. Opening it.", 4000);
    location.replace(`#/job/${r.id}`);
  } catch { $("#open-busy").hidden = true; toast("Could not open the file. Please try again."); }
}

// ---------------- Nextcloud picker ----------------
const picker = { mode: "attach", path: "", chosen: new Map(), q: "" };
const EXT_ICON = { pdf: "pdf", docx: "edit", doc: "edit", odt: "edit" };
function openPicker({ mode }) {
  picker.mode = mode; picker.chosen = new Map(); picker.q = "";
  $("#picker-q").value = "";
  $("#picker-title").textContent = mode === "open" ? "Choose the file to edit" : "Add from Nextcloud";
  $("#picker").hidden = false; document.body.classList.add("noscroll");
  updatePickerFoot();
  loadFolder(picker.path || "");
}
function closePicker() { $("#picker").hidden = true; document.body.classList.remove("noscroll"); }
$("#picker-close").onclick = closePicker;
async function loadFolder(path) {
  picker.path = path;
  renderCrumbs(path);
  const ul = $("#picker-list"); ul.innerHTML = ""; ul.append(el("li", "loading", "Loading…"));
  try { const r = await api(`/api/nc/list?path=${encodeURIComponent(path)}`); renderItems(r.items, false); }
  catch { ul.innerHTML = ""; ul.append(el("li", "loading", "Could not reach Nextcloud.")); }
}
function renderCrumbs(path) {
  const nav = $("#crumbs"); nav.innerHTML = "";
  const parts = path ? path.split("/") : [];
  const home = el("button", null, "Home"); home.onclick = () => loadFolder(""); nav.append(home);
  parts.forEach((p, i) => {
    nav.append(el("span", "sep", "›"));
    const b = el("button", null, p); b.onclick = () => loadFolder(parts.slice(0, i + 1).join("/")); nav.append(b);
  });
  nav.hidden = !!picker.q;
}
function itemIcon(it) {
  if (it.dir) return icon("folder", "ico folder");
  const ext = it.name.split(".").pop().toLowerCase();
  if ((it.type || "").startsWith("image/") || ext === "pdf") {
    const img = el("img", "thumb"); img.loading = "lazy"; img.alt = "";
    img.src = `/api/nc/thumb/${it.fileid}`;
    img.onerror = () => img.replaceWith(icon(EXT_ICON[ext] || "file", "ico"));
    return img;
  }
  return icon(EXT_ICON[ext] || "file", "ico");
}
const OPENABLE = /\.(pdf|docx?|odt|rtf|jpe?g|png|webp|heic)$/i;
function renderItems(items, searching) {
  if (picker.mode === "open") items = items.filter((it) => it.dir || OPENABLE.test(it.name));
  const ul = $("#picker-list"); ul.innerHTML = "";
  if (!items.length) ul.append(el("li", "loading", searching ? "Nothing found." : "This folder is empty."));
  for (const it of items) {
    const when = it.modified ? fmtDate(it.modified) : "";
    const size = it.dir ? "" : it.size > 1048576 ? `${(it.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(it.size / 1024))} KB`;
    const where = searching ? it.path.split("/").slice(0, -1).join(" › ") || "Home" : "";
    const sub = [where, when, size].filter(Boolean).join(" · ");
    const check = el("span", "pick"); check.append(icon("check"));
    const li = row({
      img: itemIcon(it), title: it.name, sub,
      right: it.dir ? null : picker.mode === "attach" ? check : null,
      cls: picker.chosen.has(it.path) ? "chosen" : "",
      onClick: () => {
        if (it.dir) return (picker.q = "", $("#picker-q").value = "", loadFolder(it.path));
        if (picker.mode === "open") return startOpen({ path: it.path });
        if (picker.chosen.has(it.path)) picker.chosen.delete(it.path); else picker.chosen.set(it.path, it);
        li.firstChild.classList.toggle("chosen", picker.chosen.has(it.path));
        updatePickerFoot();
      },
    });
    if (it.dir) li.firstChild.append(icon("chev", "chev"));
    ul.append(li);
  }
}
function updatePickerFoot() {
  const n = picker.chosen.size;
  $("#picker-foot").hidden = picker.mode !== "attach" || !n;
  $("#picker-ok").textContent = n === 1 ? "Add this file" : `Add ${n} files`;
}
$("#picker-ok").onclick = () => {
  attach[attachTarget].nc.push(...[...picker.chosen.values()].map((i) => ({ path: i.path, name: i.name })));
  renderAttach(attachTarget); closePicker();
};
let searchT;
$("#picker-q").oninput = () => {
  clearTimeout(searchT);
  searchT = setTimeout(async () => {
    picker.q = $("#picker-q").value.trim();
    if (picker.q.length < 2) { picker.q = ""; return loadFolder(picker.path); }
    renderCrumbs(picker.path);
    try { renderItems((await api(`/api/nc/search?q=${encodeURIComponent(picker.q)}`)).items, true); } catch { }
  }, 350);
};

// ---------------- job ----------------
async function openJob(id) {
  const run = (openJob.run = (openJob.run || 0) + 1); // a newer call wins if two overlap
  show("job", "");
  setTab("chat");
  $("#messages").innerHTML = ""; $("#pages").innerHTML = ""; $("#pages-orig").innerHTML = "";
  $("#doc-actions").hidden = true; $("#doc-dot").hidden = true; $("#doc-bar").hidden = true;
  stopMarking(); pageInfo.new = []; pageInfo.original = [];
  status = null; lastSeq = 0; hasPreview = false;
  let j;
  try { j = await api(`/api/jobs/${id}`); } catch { return (location.hash = "#/"); }
  if (run !== openJob.run) return;
  job = j;
  $("#top-title").textContent = job.title;
  for (const ev of job.events) handleEvent(ev, true);
  setBusy(job.busy);
  if (job.busy && !openCard()) setStatus("Working…");
  if (job.original) await loadOriginal();
  if (job.outputs.preview) await loadPreview(job.outputs, true);
  if (run !== openJob.run) return;
  setView(job.outputs.preview || !job.original ? "new" : "original");
  renderSave();
  if (job.pending_question && !openCard())
    handleEvent({ type: "question", ...job.pending_question }, true);
  // question survived a server restart: still answerable
  connect();
}

function connect() {
  stream = new EventSource(`/api/jobs/${job.id}/stream?after=${lastSeq}`);
  stream.onmessage = (m) => handleEvent(JSON.parse(m.data), false);
}

function scrollChat() { const m = $("#messages"); m.scrollTop = m.scrollHeight; }

function setStatus(text) {
  if (!text) { status?.remove(); status = null; return; }
  if (!status) { status = el("div", "status"); status.append(el("span", "spin"), el("span")); }
  status.lastChild.textContent = text;
  $("#messages").append(status); // keep it last
}

function userBubble(ev) {
  const m = el("div", "msg me", ev.text || "");
  for (const p of ev.photos || []) {
    const img = el("img"); img.src = `/api/jobs/${job.id}/upload/${p.split("/").pop()}`; img.alt = "Photo";
    img.onerror = () => img.remove(); m.append(img);
  }
  for (const f of ev.files || []) { const c = el("span", "fchip static"); c.append(icon("file"), el("span", null, f)); m.append(c); }
  return m;
}

function handleEvent(ev, replay) {
  if (ev.seq) { if (ev.seq <= lastSeq) return; lastSeq = ev.seq; }
  const box = $("#messages");
  const add = (node) => { status ? box.insertBefore(node, status) : box.append(node); };
  switch (ev.type) {
    case "user": {
      if (ev.answer) { cardDone(openCard(), [ev.text]); break; } // old single-question answers
      if (ev.opened) { add(el("div", "msg note", `Opened ${(ev.files || [])[0] || "the file"}`)); break; }
      if (!ev.text && !(ev.photos || []).length && !(ev.files || []).length) break;
      add(userBubble(ev)); break;
    }
    case "assistant": add(el("div", "msg bot", ev.text)); break;
    case "activity":
      if (!replay) { setStatus(ev.text); if (/PDF|Word|document/.test(ev.text)) setUpdating(true); }
      break;
    case "question": setStatus(null); box.append(questionCard(normalizeCard(ev), replay)); renderDrafting(); break;
    case "answered": cardDone(openCard(), ev.answers || [], ev.message); renderDrafting(); break;
    case "error": setStatus(null); add(el("div", "msg err", ev.text)); break;
    case "interrupted": setStatus(null); add(el("div", "msg note", ev.text)); break;
    case "title": job.title = ev.title; $("#top-title").textContent = ev.title; break;
    case "preview":
      if (!replay && "save_state" in ev) job.save_state = ev.save_state; // replay: the job's own state is newer
      if (ev.format) job.format = ev.format;
      if (!replay) {
        loadPreview(ev.outputs);
        setView("new");
        if (!$("#job").classList.contains("show-doc")) $("#doc-dot").hidden = false;
      }
      renderSave();
      break;
    case "saved":
      if (ev.doc && !replay) { job.save_state = ev.save_state; job.last_saved = { path: ev.path, fileid: ev.fileid }; }
      if (!replay) renderSave(true);
      break;
    case "busy":
      if (!replay) {
        setBusy(ev.busy); setStatus(ev.busy ? (status ? status.lastChild.textContent : "Working…") : null);
        if (!ev.busy) setUpdating(false);
        renderDrafting();
      }
      break;
  }
  scrollChat();
}

// ---------------- question cards ----------------
// A card holds 1–12 questions; he answers them one at a time; all answers go back together.
function normalizeCard(ev) {
  if (ev.questions) return ev;
  return { questions: [{ question: ev.question, options: ev.options || [], other: !!ev.allow_text || !(ev.options || []).length }], intro: "" };
}
const openCard = () => $$(".q:not(.done)").pop();

function questionCard(card, replay) {
  const qs = card.questions;
  const wrap = el("div", "q");
  wrap.card = card;
  wrap.answers = qs.map((q) => (q.multiple ? [] : null));
  wrap.others = qs.map(() => "");
  if (card.intro) wrap.append(el("p", "intro", card.intro));
  const body = el("div", "q-body"); wrap.append(body);
  wrap.step = 0;
  wrap.render = () => renderStep(wrap);
  if (!replay && !REDUCED) wrap.classList.add("enter");
  wrap.render();
  return wrap;
}

function answerText(wrap, i) {
  const a = wrap.answers[i], other = wrap.others[i].trim();
  const parts = Array.isArray(a) ? a.filter((x) => x !== OTHER) : a && a !== OTHER ? [a] : [];
  if (other) parts.push(other);
  return Array.isArray(a) ? parts : parts.join(", ");
}
const OTHER = "Other (write below)";

function renderStep(wrap) {
  const { questions: qs } = wrap.card;
  const i = wrap.step, q = qs[i];
  const body = wrap.querySelector(".q-body");
  body.innerHTML = "";
  clearPointer();
  if (qs.length > 1) {
    const dots = el("div", "q-dots");
    qs.forEach((_, k) => dots.append(el("i", k < i ? "done" : k === i ? "on" : "")));
    dots.append(el("span", null, `${i + 1} of ${qs.length}`));
    body.append(dots);
  }
  body.append(el("b", "q-text", q.question));
  if (q.why) body.append(el("p", "why", q.why));
  const opts = [...(q.options || [])];
  if (q.other && opts.length) opts.push(OTHER);
  const chips = el("div", "chips");
  const otherBox = el("div", "other");
  const ta = el("textarea"); ta.rows = 2; ta.placeholder = opts.length ? "Write your answer" : "Your answer";
  ta.value = wrap.others[i];
  ta.oninput = () => { wrap.others[i] = ta.value; nextBtn.disabled = !canGo(); };
  otherBox.append(ta);
  const isOtherOn = () => (q.multiple ? wrap.answers[i].includes(OTHER) : wrap.answers[i] === OTHER) || !opts.length;
  const canGo = () => {
    const a = wrap.answers[i];
    if (isOtherOn()) return !!wrap.others[i].trim() || (q.multiple && a.filter((x) => x !== OTHER).length > 0);
    return q.multiple ? a.length > 0 : a != null;
  };
  opts.forEach((o, k) => {
    const c = el("button", "chip", o); c.type = "button";
    if (!REDUCED) c.style.animationDelay = `${k * 60}ms`;
    const on = q.multiple ? wrap.answers[i].includes(o) : wrap.answers[i] === o;
    if (on) c.classList.add("on");
    c.onclick = async () => {
      if (wrap.classList.contains("done") || wrap.sending) return;
      if (q.multiple) {
        const a = wrap.answers[i]; const at = a.indexOf(o);
        at >= 0 ? a.splice(at, 1) : a.push(o);
        c.classList.toggle("on", at < 0);
        otherBox.hidden = !isOtherOn(); nextBtn.disabled = !canGo();
        if (o === OTHER && at < 0) ta.focus();
        return;
      }
      wrap.answers[i] = o;
      for (const x of chips.children) x.classList.toggle("on", x === c);
      if (o === OTHER) { otherBox.hidden = false; nextBtn.disabled = !canGo(); ta.focus(); return; }
      otherBox.hidden = true;
      c.classList.add("tick");  // short ✓ so he sees the tap registered
      await sleep(REDUCED ? 120 : 380);
      next();
    };
    chips.append(c);
  });
  body.append(chips);
  otherBox.hidden = !isOtherOn();
  body.append(otherBox);
  const nav = el("div", "q-nav");
  const back = el("button", "link", "Back"); back.type = "button";
  back.onclick = () => { wrap.step--; wrap.render(); };
  const last = i === qs.length - 1;
  const nextBtn = el("button", "btn primary small", last ? "Send" : "Next"); nextBtn.type = "button";
  nextBtn.disabled = !canGo();
  nextBtn.onclick = () => next();
  if (i > 0) nav.append(back);
  nav.append(el("span", "grow"), nextBtn);
  // single-choice questions advance on tap; Next shows for multi-choice, typed answers and "Other"
  const syncNext = () => { nextBtn.hidden = !(q.multiple || !opts.length || isOtherOn()); };
  syncNext();
  for (const c of chips.children) c.addEventListener("click", syncNext);
  body.append(nav);

  function next() {
    if (!canGo()) return;
    if (wrap.step < qs.length - 1) { wrap.step++; wrap.render(); if (!REDUCED) wrap.querySelector(".q-body").classList.add("slide"); }
    else sendCard(wrap);
  }
  if (q.point_at) pointAt(q.point_at, q.on || "new");
  nudgeLater(wrap);
}

function nudgeLater(wrap) {
  clearTimeout(wrap.nudge);
  wrap.nudge = setTimeout(() => {
    if (wrap.classList.contains("done") || !wrap.isConnected) return;
    wrap.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" });
    wrap.classList.remove("nudge"); void wrap.offsetWidth; wrap.classList.add("nudge");
  }, 30000);
}

async function sendCard(wrap, message = "") {
  if (wrap.sending) return;
  wrap.sending = true;
  const answers = wrap.card.questions.map((_, i) => answerText(wrap, i));
  try {
    await postJSON(`/api/jobs/${job.id}/answer`, { answers, message });
    cardDone(wrap, answers, message);
  } catch { toast("Could not send. Please try again."); }
  finally { wrap.sending = false; }
}

function cardDone(wrap, answers, message) {
  if (!wrap || wrap.classList.contains("done")) return;
  clearTimeout(wrap.nudge); clearPointer();
  wrap.classList.add("done"); wrap.classList.remove("nudge");
  const body = wrap.querySelector(".q-body"); body.innerHTML = "";
  const qs = wrap.card.questions;
  const list = el("dl", "q-sum");
  qs.forEach((q, i) => {
    let a = answers[i];
    if (Array.isArray(a)) a = a.join(", ");
    if (a) list.append(el("dt", null, q.question), el("dd", null, a));
  });
  body.append(list);
  if (message) body.append(el("p", "note", "You wrote a message instead."));
}

// ---------------- composer ----------------
$("#chat-text").addEventListener("input", (e) => { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + "px"; });
$("#composer").onsubmit = async (e) => {
  e.preventDefault();
  const ta = $("#chat-text");
  const text = ta.value.trim();
  const a = attach.chat;
  if (!text && !a.files.length && !a.nc.length) return;
  // a question card is open: send what he answered so far plus his message
  const card = openCard();
  if (card && !a.files.length && !a.nc.length) { ta.value = ""; ta.style.height = ""; return sendCard(card, text); }
  if (busy) return toast("Please wait a moment.");
  const fd = new FormData(); fd.append("text", text);
  attachForm(fd, "chat");
  ta.value = ""; ta.style.height = "";
  await sendMessage(fd);
};
async function sendMessage(fd) {
  setBusy(true);
  try { await api(`/api/jobs/${job.id}/message`, { method: "POST", body: fd }); }
  catch { setBusy(false); toast("Could not send. Please try again."); }
}
async function sendText(text) {
  const card = openCard();
  if (card) return sendCard(card, text);
  if (busy) return toast("Please wait a moment.");
  const fd = new FormData(); fd.append("text", text);
  await sendMessage(fd);
}
function setBusy(b) { busy = b; $("#send").disabled = b; }

// tabs (phone)
function setTab(t) {
  $("#job").classList.toggle("show-doc", t === "doc");
  for (const b of $$(".seg:not(.mini) button")) b.classList.toggle("on", b.dataset.tab === t);
  if (t === "doc") $("#doc-dot").hidden = true;
}
for (const b of $$(".seg:not(.mini) button")) b.onclick = () => setTab(b.dataset.tab);

// ---------------- document side ----------------
let hasPreview = false;
const pageInfo = { new: [], original: [] };   // per page: { box, canvas, page (pdf.js), vp1 }

function setView(v) {
  if (v === "original" && !job.original) v = "new";
  view = v;
  $("#pages").hidden = v !== "new";
  $("#pages-orig").hidden = v !== "original";
  for (const b of $$("#view-seg button")) b.classList.toggle("on", b.dataset.view === v);
  $("#view-seg").hidden = !job.original;
  $("#pen").hidden = !PEN_OK || !(v === "new" ? hasPreview : pageInfo.original.length);
  $("#doc-bar").hidden = $("#view-seg").hidden && $("#pen").hidden && $("#pen-bar").hidden;
  renderDrafting();
  penHintOnce();
}
for (const b of $$("#view-seg button")) b.onclick = () => { stopMarking(); setView(b.dataset.view); };

function renderDrafting() {
  const showing = view === "new" ? hasPreview : true;
  $("#drafting").hidden = showing || !busy || !!openCard();
  $("#doc-empty").hidden = showing || busy;
}
function setUpdating(on) { $("#updating").hidden = !(on && hasPreview && view === "new"); }

async function renderPdf(url, container, key) {
  const pdf = await pdfjsLib.getDocument(url).promise;
  const frag = document.createDocumentFragment();
  const info = [];
  const width = Math.min($("#desk").clientWidth - 32 || window.innerWidth, 820);
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const vp1 = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: (width / vp1.width) * Math.min(window.devicePixelRatio || 1, 2.5) });
    const c = document.createElement("canvas"); c.width = vp.width; c.height = vp.height;
    await page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise;
    const box = el("div", "page"); box.style.aspectRatio = `${vp1.width} / ${vp1.height}`;
    box.append(c, el("div", "marks"));
    frag.append(box);
    info.push({ box, canvas: c, page, vp1 });
  }
  container.innerHTML = ""; container.append(frag);
  pageInfo[key] = info;
}

async function loadOriginal() {
  const o = job.original;
  if (!o || !o.preview) return;
  const url = `/api/jobs/${job.id}/original?v=${job.id}`;
  const box = $("#pages-orig");
  try {
    if (o.kind === "image") {
      const img = el("img"); img.src = url; img.alt = "Original";
      await img.decode();
      const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight;
      c.getContext("2d").drawImage(img, 0, 0);
      const page = el("div", "page"); page.style.aspectRatio = `${c.width} / ${c.height}`;
      page.append(c, el("div", "marks"));
      box.innerHTML = ""; box.append(page);
      pageInfo.original = [{ box: page, canvas: c }];
    } else await renderPdf(url, box, "original");
  } catch (e) { console.error(e); }
}

async function loadPreview(outputs, first) {
  if (!outputs || !outputs.preview) return;
  const url = `/api/jobs/${job.id}/file/${outputs.preview}?v=${Date.now()}`;
  const before = first ? null : snapshot(pageInfo.new);
  try {
    await renderPdf(url, $("#pages"), "new");
    hasPreview = true;
  } catch (e) { console.error(e); }
  setUpdating(false);
  renderDrafting();
  if (before && !REDUCED) highlightChanges(before, pageInfo.new);
  // PDF: the real PDF, or for Word jobs the PDF preview of the Word file. Word: only for Word jobs.
  const pdfFile = outputs.pdf || outputs.preview;
  setMenuItem($("#dl-pdf"), pdfFile);
  setMenuItem($("#dl-docx"), outputs.docx);
  for (const [id, f] of [["#share-pdf", pdfFile], ["#share-docx", outputs.docx]]) {
    const a = $(id); a.dataset.file = f || ""; a.classList.toggle("disabled", !f); a.setAttribute("aria-disabled", String(!f));
    a.title = f ? "" : "Only for Word documents";
  }
  $("#doc-actions").hidden = false;
  if (view === "new") setView("new");
  renderSave();
}

// --- "what changed": compare the old and new pages, sweep a highlighter over the differences ---
const GRID = 6; // px cells on a 150-px-wide thumbnail
function thumbData(canvas) {
  const w = 150, h = Math.round((canvas.height / canvas.width) * w);
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  const g = c.getContext("2d", { willReadFrequently: true }); g.drawImage(canvas, 0, 0, w, h);
  return g.getImageData(0, 0, w, h);
}
function snapshot(pages) { return pages.map((p) => thumbData(p.canvas)); }
function highlightChanges(before, pages) {
  if (before.length !== pages.length) return;
  pages.forEach((p, n) => {
    const a = before[n], b = thumbData(p.canvas);
    if (a.width !== b.width || a.height !== b.height) return;
    const cols = Math.ceil(a.width / GRID), rows = Math.ceil(a.height / GRID);
    const hit = new Uint8Array(cols * rows);
    let count = 0;
    for (let y = 0; y < a.height; y++) for (let x = 0; x < a.width; x++) {
      const k = (y * a.width + x) * 4;
      const d = Math.abs(a.data[k] - b.data[k]) + Math.abs(a.data[k + 1] - b.data[k + 1]) + Math.abs(a.data[k + 2] - b.data[k + 2]);
      if (d > 90) { const ci = Math.floor(y / GRID) * cols + Math.floor(x / GRID); if (!hit[ci]) { hit[ci] = 1; count++; } }
    }
    if (!count || count > cols * rows * 0.35) return; // nothing, or the whole page moved: skip
    // group touching cells into boxes
    const seen = new Uint8Array(cols * rows), boxes = [];
    for (let i = 0; i < hit.length; i++) {
      if (!hit[i] || seen[i]) continue;
      let x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1; const st = [i]; seen[i] = 1;
      while (st.length) {
        const c = st.pop(), cx = c % cols, cy = Math.floor(c / cols);
        x0 = Math.min(x0, cx); y0 = Math.min(y0, cy); x1 = Math.max(x1, cx); y1 = Math.max(y1, cy);
        for (let dy = -1; dy <= 1; dy++) for (let dx = -2; dx <= 2; dx++) {
          const nx = cx + dx, ny = cy + dy, ni = ny * cols + nx;
          if (nx >= 0 && ny >= 0 && nx < cols && ny < rows && hit[ni] && !seen[ni]) { seen[ni] = 1; st.push(ni); }
        }
      }
      boxes.push([x0, y0, x1 + 1, y1 + 1]);
    }
    const layer = p.box.querySelector(".marks");
    boxes.slice(0, 12).forEach(([x0, y0, x1, y1], k) => {
      const h = el("i", "hl");
      Object.assign(h.style, { left: `${(x0 / cols) * 100 - 0.6}%`, top: `${(y0 / rows) * 100 - 0.3}%`,
        width: `${((x1 - x0) / cols) * 100 + 1.2}%`, height: `${((y1 - y0) / rows) * 100 + 0.6}%`,
        animationDelay: `${k * 120}ms` });
      layer.append(h);
      setTimeout(() => h.remove(), 4200 + k * 120);
    });
    if (n === 0 || boxes.length) setTimeout(() => layer.querySelector(".hl")?.scrollIntoView({ behavior: "smooth", block: "center" }), 150);
  });
}

// --- point at text on the page: a red circle draws itself around it ---
async function pointAt(text, which) {
  const key = which === "original" ? "original" : "new";
  if (!pageInfo[key].length) return;
  if (key !== view) setView(key);
  const want = text.replace(/\s+/g, " ").trim().toLowerCase();
  if (!want) return;
  for (const p of pageInfo[key]) {
    if (!p.page) continue;
    const tc = await p.page.getTextContent();
    let joined = "", spans = [];
    for (const it of tc.items) {
      if (!it.str) continue;
      const s = (joined && !joined.endsWith(" ") ? " " : "") + it.str;
      spans.push({ from: joined.length, to: joined.length + s.length, it });
      joined += s;
    }
    const norm = joined.replace(/\s+/g, " ").toLowerCase();
    // map collapsed-space index back roughly: search in a version with single spaces
    const at = norm.indexOf(want);
    if (at < 0) continue;
    const ratio = joined.length / Math.max(norm.length, 1);
    const a0 = at * ratio, a1 = (at + want.length) * ratio;
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const s of spans) {
      if (s.to <= a0 || s.from >= a1) continue;
      const [, , , , e, f] = s.it.transform;
      // a text item is often a whole line: take just the matching part, by character position
      const len = Math.max(s.to - s.from, 1);
      const f0 = (Math.max(a0, s.from) - s.from) / len, f1 = (Math.min(a1, s.to) - s.from) / len;
      const xa = e + s.it.width * f0, xb = e + s.it.width * f1;
      const r = p.vp1.convertToViewportRectangle([xa, f - 2, xb, f + (s.it.height || 10)]);
      x0 = Math.min(x0, r[0], r[2]); x1 = Math.max(x1, r[0], r[2]);
      y0 = Math.min(y0, r[1], r[3]); y1 = Math.max(y1, r[1], r[3]);
    }
    if (x1 < 0) continue;
    drawCircle(p, x0, y0, x1, y1);
    return;
  }
}
function drawCircle(p, x0, y0, x1, y1) {
  clearPointer();
  const W = p.vp1.width, H = p.vp1.height, pad = 7;
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, rx = (x1 - x0) / 2 + pad + 4, ry = (y1 - y0) / 2 + pad;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "pointer");
  // a slightly hand-drawn loop: an ellipse path that overshoots its start
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  const pts = [];
  for (let t = -0.15; t <= Math.PI * 2 + 0.35; t += 0.12) {
    const wob = 1 + 0.04 * Math.sin(t * 3);
    pts.push(`${(cx + rx * wob * Math.cos(t)).toFixed(1)},${(cy + ry * wob * Math.sin(t) - (t > Math.PI * 2 ? 3 : 0)).toFixed(1)}`);
  }
  path.setAttribute("d", "M" + pts.join(" L"));
  svg.append(path);
  p.box.querySelector(".marks").append(svg);
  const len = path.getTotalLength(); path.style.strokeDasharray = len; path.style.strokeDashoffset = REDUCED ? 0 : len;
  requestAnimationFrame(() => (path.style.strokeDashoffset = 0));
  setTimeout(() => svg.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "center" }), 60);
}
function clearPointer() { for (const s of $$(".pointer")) s.remove(); }

// ---------------- pen marking (tablet) ----------------
let marking = null; // { key, strokes: Map(pageIdx → [[{x,y,p}]]), layers: [] }
function penHintOnce() {
  if ($("#pen").hidden) return;
  let seen = false; try { seen = localStorage.getItem("penHint") === "1"; } catch { }
  if (seen) return;
  $("#pen").classList.add("glow");
  $("#pen").addEventListener("animationend", () => $("#pen").classList.remove("glow"), { once: true });
  try { localStorage.setItem("penHint", "1"); } catch { }
}
$("#pen").onclick = () => startMarking();
$("#pen-cancel").onclick = () => stopMarking();
$("#pen-undo").onclick = () => {
  if (!marking) return;
  for (let i = marking.order.length - 1; i >= 0; i--) {
    const n = marking.order.pop(); const s = marking.strokes.get(n);
    if (s && s.length) { s.pop(); redrawInk(n); break; }
  }
};
$("#pen-send").onclick = () => sendMarks();

function startMarking() {
  const pages = pageInfo[view];
  if (!pages.length) return;
  marking = { key: view, strokes: new Map(), order: [], layers: [] };
  $("#pen").hidden = true; $("#pen-bar").hidden = false; $("#pen-hint").hidden = false; $("#view-seg").classList.add("locked");
  $("#desk").classList.add("marking");
  pages.forEach((p, n) => {
    const ink = document.createElement("canvas"); ink.className = "ink";
    const r = p.box.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2.5);
    ink.width = Math.round(r.width * dpr); ink.height = Math.round(r.height * dpr);
    p.box.append(ink); marking.layers[n] = ink;
    let cur = null, lastY = 0;
    ink.addEventListener("pointerdown", (e) => {
      const penLike = e.pointerType === "pen" || (e.pointerType === "mouse" && new URLSearchParams(location.search).has("pen"));
      if (!penLike) { lastY = e.clientY; cur = "scroll"; ink.setPointerCapture(e.pointerId); return; }
      e.preventDefault(); ink.setPointerCapture(e.pointerId);
      cur = [];
      if (!marking.strokes.has(n)) marking.strokes.set(n, []);
      marking.strokes.get(n).push(cur); marking.order.push(n);
      addPoint(e);
    });
    ink.addEventListener("pointermove", (e) => {
      if (cur === "scroll") { $("#desk").scrollTop -= e.clientY - lastY; lastY = e.clientY; return; }
      if (!cur) return;
      for (const ce of e.getCoalescedEvents ? e.getCoalescedEvents() : [e]) addPoint(ce);
    });
    const end = () => { cur = null; };
    ink.addEventListener("pointerup", end); ink.addEventListener("pointercancel", end);
    function addPoint(e) {
      const rr = ink.getBoundingClientRect();
      cur.push({ x: (e.clientX - rr.left) / rr.width, y: (e.clientY - rr.top) / rr.height, p: e.pressure || 0.5 });
      drawLast(ink, cur);
    }
  });
}
function drawLast(ink, s) {
  const g = ink.getContext("2d"); const n = s.length; if (n < 2) return;
  const a = s[n - 2], b = s[n - 1];
  g.strokeStyle = "#d4241b"; g.lineCap = "round"; g.lineJoin = "round";
  g.lineWidth = (1.4 + 3.2 * b.p) * (ink.width / 800);
  g.beginPath(); g.moveTo(a.x * ink.width, a.y * ink.height); g.lineTo(b.x * ink.width, b.y * ink.height); g.stroke();
}
function redrawInk(n) {
  const ink = marking.layers[n]; ink.getContext("2d").clearRect(0, 0, ink.width, ink.height);
  for (const s of marking.strokes.get(n) || []) for (let i = 2; i <= s.length; i++) drawLast(ink, s.slice(0, i));
}
function stopMarking() {
  if (!marking) return;
  for (const l of marking.layers) l?.remove();
  marking = null;
  $("#pen-bar").hidden = true; $("#pen-hint").hidden = true; $("#view-seg").classList.remove("locked");
  $("#desk").classList.remove("marking");
  setView(view);
}
async function sendMarks() {
  if (!marking) return;
  const pages = pageInfo[marking.key];
  const fd = new FormData();
  let any = false;
  for (const [n, strokes] of marking.strokes) {
    if (!strokes.length) continue;
    any = true;
    const src = pages[n].canvas, ink = marking.layers[n];
    const c = document.createElement("canvas"); c.width = src.width; c.height = src.height;
    const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
    g.drawImage(src, 0, 0); g.drawImage(ink, 0, 0, c.width, c.height);
    const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.88));
    fd.append("marks", new File([blob], `page-${n + 1}.jpg`, { type: "image/jpeg" }));
  }
  if (!any) return toast("Mark something on the page first.");
  if (busy) return toast("Please wait a moment.");
  const text = $("#chat-text").value.trim(); $("#chat-text").value = "";
  fd.append("text", text); fd.append("marks_on", marking.key);
  stopMarking();
  await sendMessage(fd);
}

function setMenuItem(a, file) {
  a.classList.toggle("disabled", !file);
  a.setAttribute("aria-disabled", String(!file));
  if (file) { a.href = `/api/jobs/${job.id}/file/${file}?download=1`; a.title = ""; }
  else { a.removeAttribute("href"); a.title = "Only for Word documents"; }
}

// dropdown menus (Download, Share, +)
function closeMenus() {
  for (const m of $$(".menu")) m.hidden = true;
  for (const b of $$("[data-menu]")) b.setAttribute("aria-expanded", "false");
}
for (const b of $$("[data-menu]")) {
  const m = $("#" + b.dataset.menu);
  b.onclick = (e) => { e.stopPropagation(); const open = m.hidden; closeMenus(); m.hidden = !open; b.setAttribute("aria-expanded", String(open)); };
  m.addEventListener("click", (e) => { if (e.target.closest(".disabled")) { e.preventDefault(); e.stopPropagation(); return; } closeMenus(); });
}
document.addEventListener("click", closeMenus);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeMenus(); if (!$("#picker").hidden) closePicker(); } });

// ---------------- share (real file, via the phone's share sheet → WhatsApp etc.) ----------------
async function shareFile(name) {
  const ext = name.split(".").pop();
  const url = `/api/jobs/${job.id}/file/${name}`;
  const fname = `${(job.title || "document").replace(/[\\/:*?"<>|]+/g, " ").trim()}.${ext === "docx" ? "docx" : "pdf"}`;
  const type = ext === "docx" ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document" : "application/pdf";
  try {
    const blob = await (await fetch(`${url}?share=1`)).blob();
    const file = new File([blob], fname, { type });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file], title: job.title });
      return;
    }
  } catch (e) {
    if (e.name === "AbortError") return; // he closed the share sheet
    console.error(e);
  }
  // sharing files needs https (the installed app / the internet address); on the home network just download
  location.href = `${url}?download=1`;
  toast("Downloaded. Sharing directly works from the installed app.", 5000);
}
$("#share-pdf").onclick = () => { const f = $("#share-pdf").dataset.file; if (f) shareFile(f); };
$("#share-docx").onclick = () => { const f = $("#share-docx").dataset.file; if (f) shareFile(f); };

// ---------------- saved-in-Nextcloud status ----------------
function renderSave(justSaved) {
  const a = $("#sync");
  const st = job && job.save_state;
  const built = hasPreview || (job && job.outputs && job.outputs.preview) || (job && job.preview_version);
  a.hidden = !built;
  if (!built) return;
  a.removeAttribute("href"); a.removeAttribute("target");
  if (st === "saved") {
    a.className = "sync ok" + (justSaved && !REDUCED ? " just" : "");
    a.replaceChildren(icon("cloud-ok"), el("span", null, "Saved"));
    a.title = "Open in Nextcloud"; a.href = `/api/jobs/${job.id}/nextcloud`; a.target = "_blank"; a.rel = "noopener";
  } else {
    a.className = st === "changed" ? "sync warn" : "sync";
    a.replaceChildren(icon("cloud-off"), el("span", null, st === "changed" ? "Changes not saved" : "Not saved"));
    a.title = "Tap to save it in Nextcloud";
  }
}
$("#sync").onclick = (e) => {
  if (job.save_state === "saved") return; // the link opens Nextcloud
  e.preventDefault();
  sendText(job.save_state === "changed" ? "Please save the changes in Nextcloud." : "Please save this in my Nextcloud.");
};

// ---------------- updates: a new deploy reaches the installed app by itself ----------------
// The page knows its build id; when the server has a newer one, reload at a moment when nothing
// he is doing would be lost (he stays on the same screen: the address keeps the document).
const BUILD = document.querySelector('meta[name="build"]')?.content;
let updateReady = false;
function safeToReload() {
  if (marking || !$("#picker").hidden) return false;
  const a = attach;
  if (a.content.files.length || a.content.nc.length || a.chat.files.length || a.chat.nc.length) return false;
  if ($$("textarea").some((t) => t.value.trim())) return false;
  const card = openCard();
  if (card && (card.step > 0 || card.answers.some((x) => (Array.isArray(x) ? x.length : x != null)))) return false;
  return true;
}
function maybeReload() { if (updateReady && safeToReload()) location.reload(); }
async function checkUpdate() {
  if (!BUILD || updateReady) return maybeReload();
  try {
    const r = await fetch("/api/version", { cache: "no-store" });
    if (r.ok && (await r.json()).build !== BUILD) updateReady = true;
  } catch { }
  maybeReload();
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") checkUpdate(); });
window.addEventListener("focus", checkUpdate);
window.addEventListener("hashchange", maybeReload);
setInterval(checkUpdate, 5 * 60 * 1000);

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
route();
