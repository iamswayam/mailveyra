const S = { me: null, profile: null, draft: null, dirty: false, busy: false, sent: false, revising: true, pending: null, ctrl: null };
const $ = (id) => document.getElementById(id);
const show = (id, on = true) => $(id).classList.toggle("hidden", !on);
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

function errText(status, d) {
  const det = d && d.detail !== undefined ? d.detail : d;
  if (typeof det === "string" && det) return det;
  if (Array.isArray(det)) return det.map((x) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("; ");
  return { 401: "Please sign in again.", 404: "Not found.", 409: "That conflicts with the current state.", 502: "Gmail rejected the request." }[status] || "Something went wrong.";
}
async function api(path, o = {}) {
  let r;
  try { r = await fetch(path, o); }
  catch (e) { throw Object.assign(new Error(e.name === "AbortError" ? "Cancelled." : "Cannot reach the server."), { status: 0, aborted: e.name === "AbortError" }); }
  const t = await r.text();
  let d = null;
  try { d = t ? JSON.parse(t) : null; } catch { d = t; }
  if (!r.ok) throw Object.assign(new Error(errText(r.status, d)), { status: r.status, raw: d });
  return d;
}
function details(raw) {
  const d = el("details"); d.append(el("summary", null, "Details"), el("pre", null, typeof raw === "string" ? raw : JSON.stringify(raw, null, 2)));
  return d;
}
function toast(e) {
  const t = el("div", "toast", e.message || String(e));
  if (e.raw) t.append(details(e.raw));
  $("toasts").append(t); setTimeout(() => t.remove(), 8000);
}
function msg(kind, text, ...extra) {
  const m = el("div", `msg ${kind}`, text); extra.forEach((x) => x && m.append(x));
  $("messages").append(m); $("messages").scrollTop = $("messages").scrollHeight; return m;
}
const chips = (list, cls) => { const w = el("div", "skills"); list.forEach((s) => w.append(el("span", `chip ${cls}`, (cls === "ok" ? "✓ " : "○ ") + s))); return w; };

/* ---------- session ---------- */
async function boot() {
  show("boot", true); show("boot-retry", false); $("boot-text").textContent = "Checking session…";
  try {
    S.me = await api("/me");
  } catch (e) {
    if (e.status === 401) { show("boot", false); show("login"); return; }
    $("boot-text").textContent = "Can't reach the server."; show("boot-retry"); return;
  }
  show("boot", false); show("login", false); show("app");
  $("account").textContent = S.me.email;
  const g = $("gmail-chip"); g.textContent = S.me.gmail_connected ? "Gmail connected" : "Gmail not connected";
  g.className = "chip " + (S.me.gmail_connected ? "ok" : "warn");
  await loadProfile(); renderHistory(); updateMode();
}

/* ---------- profile ---------- */
async function loadProfile() {
  try { S.profile = await api("/candidate-profile/me"); }
  catch (e) { if (e.status !== 404) toast(e); S.profile = null; }
  paintProfile();
  if (!S.profile) {
    msg("app", "Welcome. Set up your profile first. Drafts only claim what is in your profile and resume.", (() => { const b = el("button", "btn primary", "Set up profile"); b.onclick = openProfile; const r = el("div", "row"); r.append(b); return r; })());
    openProfile();
  }
}
function paintProfile() {
  const p = S.profile;
  $("profile-line").textContent = p ? `${p.name} · ${(p.skills || []).length} skills` : "Not set up";
  $("resume-line").textContent = p && p.resume_file_path ? `✓ ${p.resume_file_path.split(/[\\/]/).pop()}` : "No resume uploaded";
  updateMode();
}
function openProfile() {
  const p = S.profile || {};
  const set = (id, v) => { $(id).value = v || ""; };
  set("p-name", p.name || (S.me && S.me.name)); set("p-email", p.email || (S.me && S.me.email)); set("p-phone", p.phone);
  set("p-location", p.location); set("p-headline", p.headline); set("p-summary", p.summary); set("p-resume", p.resume_text);
  set("p-skills", (p.skills || []).join(", "));
  ["experience", "projects", "education"].forEach((k) => set("p-" + k, JSON.stringify(p[k] || [], null, 2)));
  $("p-error").textContent = ""; $("profile-dlg").showModal();
}
function jsonList(id, label) {
  const raw = $(id).value.trim(); if (!raw) return [];
  let v; try { v = JSON.parse(raw); } catch { throw new Error(`${label} is not valid JSON.`); }
  if (!Array.isArray(v)) throw new Error(`${label} must be a JSON array.`);
  return v;
}
async function saveProfile(ev) {
  ev.preventDefault(); $("p-error").textContent = "";
  try {
    const skills = $("p-skills").value.split(",").map((s) => s.trim()).filter(Boolean);
    if (!skills.length) throw new Error("Add at least one skill.");
    const v = (id) => $(id).value.trim() || null;
    const body = { name: $("p-name").value.trim(), email: v("p-email"), phone: v("p-phone"), location: v("p-location"), headline: v("p-headline"), summary: v("p-summary"), skills,
      experience: jsonList("p-experience", "Experience"), projects: jsonList("p-projects", "Projects"), education: jsonList("p-education", "Education"),
      resume_text: v("p-resume"), resume_file_path: (S.profile && S.profile.resume_file_path) || null };
    $("p-save").disabled = true;
    S.profile = await api(S.profile ? "/candidate-profile/me" : "/candidate-profile", { method: S.profile ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    $("profile-dlg").close(); paintProfile(); msg("ok", "Profile saved. Paste a job description to start.");
  } catch (e) { $("p-error").textContent = e.message; }
  finally { $("p-save").disabled = false; }
}
async function uploadResume(ev) {
  const f = ev.target.files[0]; if (!f) return;
  if (!S.profile) { toast(new Error("Save your profile before uploading a resume.")); ev.target.value = ""; return; }
  if (f.size > 10 * 1024 * 1024) { toast(new Error("Resume must be under 10 MB.")); ev.target.value = ""; return; }
  const form = new FormData(); form.append("file", f);
  try { S.profile = await api("/profile/resume", { method: "POST", body: form }); paintProfile(); msg("ok", `Resume uploaded: ${f.name}`); }
  catch (e) { toast(e); }
  ev.target.value = "";
}

/* ---------- chat ---------- */
function updateMode() {
  const ready = !!S.profile, revising = S.draft && !S.draft.approved_at && S.revising;
  const m = $("mode"); m.textContent = "";
  if (!ready) m.textContent = "Set up your profile to start.";
  else if (revising) {
    const x = el("button", "ghost", "✕"); x.type = "button"; x.title = "Stop revising and start a new job"; x.onclick = () => { S.revising = false; updateMode(); };
    m.append("Revising this draft — ", el("b", null, S.draft.subject || "current draft"), " ", x);
  } else m.append(el("b", null, "New job"), " — paste a job description or attach a file.");
  $("chat-input").placeholder = revising ? "Ask for changes, e.g. make it shorter…" : "Paste a job description…";
  $("chat-submit").textContent = revising ? "Update draft" : "Generate draft";
  show("chips", !!revising);
  ["chat-input", "chat-submit"].forEach((id) => { $(id).disabled = !ready || S.busy; });
  show("cancel", S.busy);
}
function setBusy(b) { S.busy = b; updateMode(); setDraftLock(); }
async function sendChat(text, files, confirm = false) {
  if (S.busy) return;
  if (!S.profile) return toast(new Error("Save your profile first."));
  if (!text && !files.length) return toast(new Error("Type a job description or attach a file."));
  const revising = S.draft && !S.draft.approved_at && S.revising;
  msg("user", text || `Attached ${files.length} file(s)`);
  setBusy(true); S.ctrl = new AbortController();
  const wait = msg("app", "Reading the job and drafting… this can take up to a minute.");
  try {
    if (revising && S.dirty) await saveDraft(true);
    const f = new FormData(); f.append("message", text); f.append("confirm_zero_overlap", confirm ? "true" : "false");
    if (revising && text) f.append("draft_id", S.draft.id);
    files.forEach((x) => f.append("files", x));
    const r = await api("/chat/messages", { method: "POST", body: f, signal: S.ctrl.signal });
    wait.remove(); handleResult(r);
  } catch (e) {
    wait.remove();
    if (e.aborted) msg("app", "Cancelled.");
    else { S.pending = { text, files }; const b = el("button", "btn", "Try again"); b.onclick = () => sendChat(text, files, confirm); const r = el("div", "row"); r.append(b); msg("err", e.message, e.raw && details(e.raw), r); }
  } finally { setBusy(false); }
}
function handleResult(r) {
  const d = r.draft;
  if (d && d.status === "blocked_zero_skill_overlap") {
    const p = S.pending; const row = el("div", "row");
    const go = el("button", "btn", "Generate anyway"); go.onclick = () => { row.remove(); sendChat(p.text, p.files, true); };
    const up = el("button", "btn", "Update skills"); up.onclick = openProfile;
    const no = el("button", "btn", "Discard"); no.onclick = () => { S.pending = null; row.remove(); msg("app", "Discarded."); };
    row.append(go, up, no);
    msg("warn", d.message || "None of your skills match this job.", el("div", "muted small", "Skills this job needs that you don't have:"), chips(d.gap_skills || [], "warn"), row);
    return;
  }
  S.pending = null;
  if (r.job) {
    const mr = (r.application && r.application.match_result) || {};
    msg("app", `${r.job.role_title || "Job"}${r.job.company ? " at " + r.job.company : ""}`, chips(mr.matched_skills || [], "ok"), chips(mr.gap_skills || [], "warn"));
  }
  if (d) { S.draft = d; S.revising = true; S.dirty = false; S.sent = false; renderDraft(); }
  msg("app", `${r.message || "Draft ready."}${r.model_used ? " (" + r.model_used + ")" : ""}`);
  document.getElementById("chat-input").value = ""; $("chat-files").value = ""; $("file-names").textContent = "";
  renderHistory();
}

/* ---------- draft ---------- */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const csv = (v) => v.split(",").map((s) => s.trim()).filter(Boolean);
function renderDraft() {
  const d = S.draft;
  show("draft-pane"); $("body").classList.add("has-draft"); show("tabs", true);
  $("d-to").value = d.recipient_email || ""; $("d-cc").value = (d.cc || []).join(", "); $("d-bcc").value = (d.bcc || []).join(", ");
  $("d-subject").value = d.subject || ""; $("d-body").value = d.body || "";
  show("row-cc", !!(d.cc || []).length); show("row-bcc", !!(d.bcc || []).length);
  const at = d.attachments || []; $("d-attach").textContent = at.length ? "Attachments: " + at.map((a) => a.filename).join(", ") : "Attachments: none";
  const ev = $("d-evidence"); ev.textContent = "";
  Object.entries(d.claim_evidence_map || {}).forEach(([k, v]) => { const p = el("div", "ev"); p.append(el("b", null, k), " → " + v); ev.append(p); });
  if (!ev.children.length) ev.textContent = "No claims recorded.";
  show("d-banner", false); setDraftLock(); validate(); updateMode();
  document.querySelector('[data-tab="draft"]').classList.add("on"); setTab("draft");
}
function setDraftLock() {
  const d = S.draft; if (!d) return;
  const ap = !!d.approved_at, lock = ap || S.busy;
  ["d-to", "d-cc", "d-bcc", "d-subject", "d-body"].forEach((id) => { $(id).disabled = lock; });
  const st = $("d-state"); st.textContent = S.sent ? "Sent" : ap ? "🔒 Approved" : S.busy ? "Updating…" : "Editable";
  st.className = "chip " + (S.sent ? "ok" : ap ? "ok" : "");
  $("s1").className = ap ? "done" : "on"; $("s2").className = S.sent || ap ? "done" : ""; $("s3").className = S.sent ? "done" : ap ? "on" : "";
  show("d-save", !ap); show("d-approve", !ap); show("d-send", ap && !S.sent);
  $("d-send").disabled = S.busy || !(S.me && S.me.gmail_connected);
  if (ap && !S.sent && !(S.me && S.me.gmail_connected)) banner("bad", "Gmail is not connected. ", "Reconnect Gmail", "/auth/google/login");
  validate();
}
function validate() {
  const d = S.draft; if (!d) return;
  const ok = { To: EMAIL.test($("d-to").value.trim()), Subject: !!$("d-subject").value.trim(), Body: !!$("d-body").value.trim() };
  const c = $("d-check"); c.textContent = "";
  Object.entries(ok).forEach(([k, v]) => c.append(el("span", "ck " + (v ? "ok" : "no"), (v ? "✓ " : "○ ") + k)));
  $("d-to").closest(".drow").classList.toggle("bad", !ok.To);
  const all = ok.To && ok.Subject && ok.Body;
  $("d-approve").disabled = !all || S.busy; $("d-approve").title = all ? "" : "Fill in To, Subject and Body first.";
  $("d-save").disabled = S.busy || !S.dirty;
  $("d-dirty").textContent = S.dirty ? "● Unsaved changes" : "";
}
function banner(kind, text, linkText, href) {
  const b = $("d-banner"); b.className = "banner " + kind; b.textContent = text;
  if (linkText) { const a = el("a", null, linkText); a.href = href; b.append(a); }
  return b;
}
async function saveDraft(quiet) {
  const body = { recipient_email: $("d-to").value.trim() || null, cc: csv($("d-cc").value), bcc: csv($("d-bcc").value), subject: $("d-subject").value.trim(), body: $("d-body").value };
  try {
    S.draft = await api(`/email-drafts/${S.draft.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    S.dirty = false; renderDraft(); if (!quiet) toastOk("Draft saved.");
  } catch (e) { toast(e); throw e; }
}
function toastOk(t) { const b = banner("ok", t); show("d-banner"); setTimeout(() => b.classList.add("hidden"), 2500); }
async function approveDraft() {
  try { if (S.dirty) await saveDraft(true); S.draft = await api(`/email-drafts/${S.draft.id}/approve`, { method: "POST" }); renderDraft(); banner("info", "Approved and frozen. Review it once more, then send."); show("d-banner"); msg("ok", "Draft approved and locked."); }
  catch (e) { if (!e.raw) toast(e); else toast(e); }
}
function confirmSend() {
  const d = S.draft, dl = $("send-summary"); dl.textContent = "";
  [["From", S.me.email], ["To", d.recipient_email], ["Subject", d.subject], ["Attachments", (d.attachments || []).map((a) => a.filename).join(", ") || "none"]].forEach(([k, v]) => { dl.append(el("dt", null, k), el("dd", null, v || "—")); });
  $("send-dlg").showModal();
}
async function doSend() {
  $("send-dlg").close(); setBusy(true);
  try {
    const r = await api(`/email-drafts/${S.draft.id}/send`, { method: "POST" });
    S.sent = true; setDraftLock(); const b = banner("ok", `Sent to ${S.draft.recipient_email}.`); b.append(details(r)); show("d-banner");
    msg("ok", `Email sent to ${S.draft.recipient_email}.`); renderHistory();
  } catch (e) {
    const auth = e.status === 401;
    if (e.status === 409) { S.sent = true; setDraftLock(); }
    const b = banner("bad", e.status === 409 ? "This email was already sent. " : auth ? "Gmail needs you to sign in again. " : `Send failed: ${e.message} `, auth ? "Reconnect Gmail" : null, "/auth/google/login");
    if (e.raw) b.append(details(e.raw)); show("d-banner");
  } finally { setBusy(false); }
}
function newApp() {
  S.draft = null; S.dirty = false; S.sent = false; S.revising = true; S.pending = null;
  show("draft-pane", false); $("body").classList.remove("has-draft"); show("tabs", false); setTab("chat");
  $("chat-input").value = ""; updateMode(); $("chat-input").focus();
}
function setTab(t) { $("body").dataset.tab = t; document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t)); }

/* ---------- history ---------- */
async function renderHistory() {
  const h = $("history");
  try {
    const apps = await api("/applications"); h.textContent = "";
    if (!apps.length) { h.textContent = "No applications yet."; h.className = "history muted small"; return; }
    apps.slice(0, 10).forEach((a) => {
      const m = a.match_result || {}; const b = el("button", "history-item", `#${a.id} · ${a.status} · ${(m.matched_skills || []).length} matched, ${(m.gap_skills || []).length} gaps`);
      b.onclick = async () => { try { msg("app", `Send log for application #${a.id}`, details(await api(`/applications/${a.id}/send-log`))); } catch (e) { toast(e); } };
      h.append(b);
    });
  } catch { h.textContent = "History unavailable."; }
}

/* ---------- wiring ---------- */
const savedTheme = localStorage.getItem("mv-theme"); if (savedTheme) document.documentElement.dataset.theme = savedTheme;
function themeLabel() { $("theme").textContent = document.documentElement.dataset.theme === "dark" ? "Light" : "Dark"; }
themeLabel();
$("theme").onclick = () => { const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = t; localStorage.setItem("mv-theme", t); themeLabel(); };
$("logout").onclick = async () => { await fetch("/auth/logout", { method: "POST" }); location.href = "/"; };
$("boot-retry").onclick = boot;
$("menu").onclick = () => $("side").classList.toggle("open");
$("open-profile").onclick = openProfile; $("p-cancel").onclick = () => $("profile-dlg").close();
$("profile-form").addEventListener("submit", saveProfile);
$("resume-file").onchange = uploadResume;
$("new-app").onclick = newApp;
$("chat-files").onchange = () => { $("file-names").textContent = Array.from($("chat-files").files).map((f) => f.name).join(", "); };
$("chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("chat-input").value.trim(), Array.from($("chat-files").files)); });
$("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("chat-form").requestSubmit(); });
$("cancel").onclick = () => S.ctrl && S.ctrl.abort();
document.querySelectorAll("#chips button").forEach((b) => { b.onclick = () => sendChat(b.dataset.q, []); });
["d-to", "d-cc", "d-bcc", "d-subject", "d-body"].forEach((id) => $(id).addEventListener("input", () => { S.dirty = true; validate(); }));
$("show-cc").onclick = (e) => { e.preventDefault(); show("row-cc"); }; $("show-bcc").onclick = (e) => { e.preventDefault(); show("row-bcc"); };
$("d-save").onclick = () => saveDraft().catch(() => {}); $("d-approve").onclick = approveDraft;
$("d-send").onclick = confirmSend; $("send-no").onclick = () => $("send-dlg").close(); $("send-yes").onclick = doSend;
document.querySelectorAll("#tabs button").forEach((b) => { b.onclick = () => setTab(b.dataset.tab); });
boot();
