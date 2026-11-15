// Single-page app: #/ home · #/new/<tpl> format · #/new/<tpl>/<fmt> content · #/job/<id>
const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const icon = (name, cls) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  if (cls) s.setAttribute("class", cls);
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", `#i-${name}`); s.append(u); return s;
};
pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

let templates = [];
let photos = [];          // files picked on the content screen
let chatPhotos = [];      // files picked in chat
let job = null;           // current job object
let stream = null;        // EventSource
let lastSeq = 0;
let status = null;        // the single "working…" line
let busy = false;

function toast(msg, ms = 3500) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), ms);
}
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.text()) || r.status);
  return r.json();
}
function show(id, title) {
  for (const s of document.querySelectorAll(".screen")) s.hidden = s.id !== id;
  $("#top").hidden = id === "home";
  $("#top").classList.toggle("wide", id === "job");
  $("#top-title").textContent = title || "";
  if (id !== "job") $("#doc-actions").hidden = true;
  for (const m of document.querySelectorAll(".menu")) m.hidden = true;
}
function fmtDate(t) {
  return new Date(t * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
function row({ ico, title, sub, right, onClick }) {
  const li = el("li"), b = el("button", "row");
  if (ico) b.append(icon(ico, "ico"));
  const t = el("span", "t"); t.append(el("b", null, title));
  if (sub) t.append(el("span", null, sub));
  b.append(t);
  b.append(right || icon("chev", "chev"));
  b.onclick = onClick; li.append(b); return li;
}

// ---------------- routing ----------------
window.addEventListener("hashchange", route);
$("#back").onclick = () => (history.length > 1 ? history.back() : (location.hash = "#/"));

async function route() {
  if (stream) { stream.close(); stream = null; }
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (!templates.length) templates = await api("/api/templates");
  if (parts[0] === "new" && parts[1]) {
    const tpl = templates.find((t) => t.id === parts[1]);
    if (!tpl) return (location.hash = "#/");
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
    b.onclick = () => (location.hash = `#/new/${t.id}`);
    box.append(b);
  }
  const list = await api("/api/jobs");
  $("#recent-h").hidden = !list.length;
  const ul = $("#recent"); ul.innerHTML = "";
  for (const j of list) {
    const tname = (templates.find((t) => t.id === j.template) || {}).name || j.template;
    const st = (j.sync || {}).state;
    const saved = st === "saved";
    ul.append(row({
      title: j.title,
      sub: `${tname} · ${j.format === "docx" ? "Word" : "PDF"} · ${fmtDate(j.updated)}`,
      right: el("span", saved ? "state saved" : st === "conflict" || st === "kept" ? "state warn" : "state",
        saved ? "Saved" : st === "conflict" || st === "kept" ? "Needs attention" : "Draft"),
      onClick: () => (location.hash = `#/job/${j.id}`),
    }));
  }
}

// ---------------- format ----------------
for (const b of document.querySelectorAll("[data-format]"))
  b.onclick = () => (location.hash = location.hash.replace(/\/$/, "") + "/" + b.dataset.format);

// ---------------- content ----------------
function showContent(tpl, fmt) {
  show("content", tpl.name);
  photos = []; renderThumbs($("#thumbs"), photos);
  $("#content-text").value = "";
  $("#start").onclick = async () => {
    const text = $("#content-text").value.trim();
    if (!text && !photos.length) return toast("Please add a photo or some text.");
    $("#start").disabled = true; $("#start").textContent = "Starting…";
    const fd = new FormData();
    fd.append("template", tpl.id); fd.append("format", fmt); fd.append("text", text);
    for (const p of photos) fd.append("photos", p);
    try {
      const j = await api("/api/jobs", { method: "POST", body: fd });
      location.replace(`#/job/${j.id}`);
    } catch { toast("Could not start. Please try again."); }
    finally { $("#start").disabled = false; $("#start").textContent = "Make the document"; }
  };
}
for (const inp of document.querySelectorAll("[data-photos]"))
  inp.onchange = () => { photos.push(...inp.files); inp.value = ""; renderThumbs($("#thumbs"), photos); };

function renderThumbs(box, files) {
  box.innerHTML = "";
  files.forEach((f, i) => {
    const img = el("img"); img.src = URL.createObjectURL(f); img.alt = "Photo, tap to remove";
    img.onclick = () => { files.splice(i, 1); renderThumbs(box, files); };
    box.append(img);
  });
}

// ---------------- job ----------------
async function openJob(id) {
  show("job", "");
  setTab("chat");
  $("#messages").innerHTML = ""; $("#pages").innerHTML = ""; $("#doc-empty").hidden = false;
  $("#doc-actions").hidden = true; $("#doc-dot").hidden = true;
  status = null; lastSeq = 0;
  try { job = await api(`/api/jobs/${id}`); } catch { return (location.hash = "#/"); }
  $("#top-title").textContent = job.title;
  for (const ev of job.events) handleEvent(ev, true);
  setBusy(job.busy);
  if (job.busy) setStatus("Working…");
  if (job.outputs.preview) loadPreview(job.outputs);
  renderSync();
  if (job.pending_question && !document.querySelector(".q:not(.done)"))
    handleEvent({ type: "question", ...job.pending_question }, true);
  // question survived a server restart: still answerable, just say so quietly
  const openQ = [...document.querySelectorAll(".q:not(.done)")].pop();
  if (openQ && job.pending_question && !job.question_live && !job.busy)
    openQ.append(el("p", "note", "Tap an answer to continue."));
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

function handleEvent(ev, replay) {
  if (ev.seq) { if (ev.seq <= lastSeq) return; lastSeq = ev.seq; }
  const box = $("#messages");
  const add = (node) => { status ? box.insertBefore(node, status) : box.append(node); };
  switch (ev.type) {
    case "user": {
      if (ev.answer) { markAnswered(ev.text); break; }
      if (!ev.text && !(ev.photos || []).length) break;
      const m = el("div", "msg me", ev.text || "");
      for (const p of ev.photos || []) {
        const img = el("img"); img.src = `/api/jobs/${job.id}/upload/${p.split("/").pop()}`; img.alt = "Photo";
        img.onerror = () => img.remove(); m.append(img);
      }
      add(m); break;
    }
    case "assistant": add(el("div", "msg bot", ev.text)); break;
    case "activity": if (!replay) setStatus(ev.text); break;
    case "question": setStatus(null); box.append(questionBlock(ev)); break;
    case "error": setStatus(null); add(el("div", "msg err", ev.text)); break;
    case "interrupted": setStatus(null); add(el("div", "msg note", ev.text)); break;
    case "title": job.title = ev.title; $("#top-title").textContent = ev.title; break;
    case "preview":
      if (!replay) {
        loadPreview(ev.outputs);
        if (!$("#job").classList.contains("show-doc")) $("#doc-dot").hidden = false;
      }
      break;
    case "busy":
      if (!replay) { setBusy(ev.busy); setStatus(ev.busy ? (status ? status.lastChild.textContent : "Working…") : null); }
      break;
    case "sync": job.sync = ev; renderSync(); break;
    case "sync_conflict": add(conflictBlock(ev)); break;
    case "sync_resolved": {
      const c = [...document.querySelectorAll(".conflict:not(.done)")].pop();
      if (c) { c.classList.add("done"); c.querySelector(".chips").replaceChildren(el("span", "chip on", ev.text)); }
      break;
    }
  }
  scrollChat();
}

function markAnswered(text) {
  const q = [...document.querySelectorAll(".q:not(.done)")].pop();
  if (!q) return;
  q.classList.add("done");
  q.querySelector(".note")?.remove();
  const hit = [...q.querySelectorAll(".chip")].find((c) => c.textContent === text);
  if (hit) hit.classList.add("on");
  else { const c = el("span", "chip on", text); q.querySelector(".chips").append(c); }
}

async function sendAnswer(text) {
  markAnswered(text);
  try {
    await api(`/api/jobs/${job.id}/answer`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer: text }) });
  } catch { toast("Could not send. Please try again."); }
}

function questionBlock(q) {
  const wrap = el("div", "q");
  wrap.append(el("b", null, q.question));
  const chips = el("div", "chips");
  for (const o of q.options || []) {
    const c = el("button", "chip", o);
    c.onclick = () => { if (!wrap.classList.contains("done")) sendAnswer(o); };
    chips.append(c);
  }
  wrap.append(chips);
  if (q.allow_text && !(q.options || []).length) {
    const f = el("form"), ta = el("textarea"); ta.rows = 1; ta.placeholder = "Your answer";
    const s = el("button", "btn primary", "OK");
    f.onsubmit = (e) => { e.preventDefault(); if (ta.value.trim()) sendAnswer(ta.value.trim()); };
    f.append(ta, s); wrap.append(f);
  }
  return wrap;
}

function setBusy(b) {
  busy = b;
  $("#send").disabled = b;
}

// composer
$("#chat-photos").onchange = (e) => { chatPhotos.push(...e.target.files); e.target.value = ""; renderThumbs($("#chat-thumbs"), chatPhotos); };
$("#chat-text").addEventListener("input", (e) => { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + "px"; });
$("#composer").onsubmit = async (e) => {
  e.preventDefault();
  const ta = $("#chat-text");
  const text = ta.value.trim();
  if (!text && !chatPhotos.length) return;
  // while a question is open, typing answers it (works even while busy)
  const open = document.querySelector(".q:not(.done)");
  if (open && !chatPhotos.length) { ta.value = ""; ta.style.height = ""; return sendAnswer(text); }
  if (busy) return toast("Please wait a moment.");
  const fd = new FormData(); fd.append("text", text);
  for (const p of chatPhotos) fd.append("photos", p);
  ta.value = ""; ta.style.height = ""; chatPhotos = []; renderThumbs($("#chat-thumbs"), chatPhotos);
  setBusy(true);
  try { await api(`/api/jobs/${job.id}/message`, { method: "POST", body: fd }); }
  catch { setBusy(false); toast("Could not send. Please try again."); }
};

// tabs
function setTab(t) {
  $("#job").classList.toggle("show-doc", t === "doc");
  for (const b of document.querySelectorAll(".seg button")) b.classList.toggle("on", b.dataset.tab === t);
  if (t === "doc") $("#doc-dot").hidden = true;
}
for (const b of document.querySelectorAll(".seg button")) b.onclick = () => setTab(b.dataset.tab);

// ---------------- preview ----------------
async function loadPreview(outputs) {
  if (!outputs || !outputs.preview) return;
  const url = `/api/jobs/${job.id}/file/${outputs.preview}?v=${Date.now()}`;
  const pages = $("#pages");
  try {
    const pdf = await pdfjsLib.getDocument(url).promise;
    const frag = document.createDocumentFragment();
    const width = Math.min(pages.clientWidth || window.innerWidth, 820);
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const vp1 = page.getViewport({ scale: 1 });
      const vp = page.getViewport({ scale: (width / vp1.width) * Math.min(window.devicePixelRatio || 1, 2.5) });
      const c = document.createElement("canvas"); c.width = vp.width; c.height = vp.height;
      await page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise;
      frag.append(c);
    }
    pages.innerHTML = ""; pages.append(frag);
    $("#doc-empty").hidden = true;
  } catch (e) { console.error(e); }
  // PDF: the real PDF, or for Word jobs the PDF preview of the Word file. Word: only for Word jobs.
  const pdfFile = outputs.pdf || outputs.preview;
  setMenuItem($("#dl-pdf"), pdfFile);
  setMenuItem($("#dl-docx"), outputs.docx);
  for (const [id, f] of [["#share-pdf", pdfFile], ["#share-docx", outputs.docx]]) {
    const a = $(id); a.dataset.file = f || ""; a.classList.toggle("disabled", !f); a.setAttribute("aria-disabled", String(!f));
    a.title = f ? "" : "Only for Word documents";
  }
  $("#doc-actions").hidden = false;
}

function setMenuItem(a, file) {
  a.classList.toggle("disabled", !file);
  a.setAttribute("aria-disabled", String(!file));
  if (file) { a.href = `/api/jobs/${job.id}/file/${file}?download=1`; a.title = ""; }
  else { a.removeAttribute("href"); a.title = "Only for Word documents"; }
}

// dropdown menus (Download, Share)
const closeMenus = () => {
  for (const m of document.querySelectorAll(".menu")) m.hidden = true;
  for (const b of document.querySelectorAll("[data-menu]")) b.setAttribute("aria-expanded", "false");
};
for (const b of document.querySelectorAll("[data-menu]")) {
  const m = $("#" + b.dataset.menu);
  b.onclick = (e) => { e.stopPropagation(); const open = m.hidden; closeMenus(); m.hidden = !open; b.setAttribute("aria-expanded", String(open)); };
  m.onclick = (e) => { if (e.target.closest(".disabled")) { e.preventDefault(); e.stopPropagation(); return; } closeMenus(); };
}
document.addEventListener("click", closeMenus);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });

// ---------------- share (real file, via the phone's share sheet → WhatsApp etc.) ----------------
async function shareFile(name) {
  const ext = name.split(".").pop();
  const url = `/api/jobs/${job.id}/file/${name}`;
  const fname = `${(job.title || "document").replace(/[\\/:*?"<>|]+/g, " ").trim()}.${ext === "docx" ? "docx" : "pdf"}`;
  const type = ext === "docx" ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document" : "application/pdf";
  try {
    const blob = await (await fetch(url)).blob();
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

// ---------------- Nextcloud sync status ----------------
const SYNC = {
  saving: { icon: "cloud", text: "Saving…", cls: "busy" },
  saved: { icon: "cloud-ok", text: "Saved", cls: "ok", title: "Open in Nextcloud" },
  error: { icon: "cloud-off", text: "Not saved", cls: "bad", title: "Tap to try again" },
  conflict: { icon: "cloud-off", text: "Needs your choice", cls: "warn" },
  kept: { icon: "cloud-off", text: "Not saved", cls: "warn", title: "Nextcloud has newer edits" },
};
function renderSync() {
  const a = $("#sync"), st = job && job.sync && SYNC[job.sync.state];
  a.hidden = !st;
  if (!st) return;
  a.className = `sync ${st.cls}`;
  a.replaceChildren(icon(st.icon), el("span", null, st.text));
  a.title = st.title || "";
  if (job.sync.state === "saved") { a.href = `/api/jobs/${job.id}/nextcloud`; a.target = "_blank"; a.rel = "noopener"; }
  else { a.removeAttribute("href"); a.removeAttribute("target"); }
}
$("#sync").onclick = async (e) => {
  const state = job.sync && job.sync.state;
  if (state === "saved") return; // the link opens Nextcloud
  e.preventDefault();
  if (state === "error") { try { await api(`/api/jobs/${job.id}/sync`, { method: "POST" }); } catch { toast("Could not reach Nextcloud."); } }
  if (state === "conflict" || state === "kept") {
    setTab("chat");
    let c = [...document.querySelectorAll(".conflict")].pop();
    if (!c || c.classList.contains("done")) { c = conflictBlock({ path: job.sync.path }); $("#messages").append(c); }
    c.scrollIntoView({ behavior: "smooth", block: "center" });
  }
};

function conflictBlock(ev) {
  const wrap = el("div", "q conflict");
  wrap.append(el("b", null, "This document was changed in Nextcloud after the app last saved it."));
  wrap.append(el("p", "note", "What should I do?"));
  const chips = el("div", "chips");
  const opts = [["merge", "Bring those changes in"], ["overwrite", "Replace with this version"], ["keep", "Leave Nextcloud as it is"]];
  for (const [choice, label] of opts) {
    const c = el("button", "chip", label);
    c.onclick = async () => {
      if (wrap.classList.contains("done")) return;
      wrap.classList.add("done"); c.classList.add("on");
      try { const r = await api(`/api/jobs/${job.id}/sync/resolve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ choice }) });
        if (!r.ok) { wrap.classList.remove("done"); c.classList.remove("on"); toast(r.message); } }
      catch { wrap.classList.remove("done"); c.classList.remove("on"); toast("Could not send. Please try again."); }
    };
    chips.append(c);
  }
  wrap.append(chips);
  return wrap;
}



if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
route();
