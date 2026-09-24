const state = {
  me: null,
  profile: null,
  application: null,
  draft: null,
  zeroOverlapPending: false,
};

const $ = (id) => document.getElementById(id);

function addMessage(text, kind = "app", payload = null) {
  const message = document.createElement("div");
  message.className = `message ${kind}`;
  const body = document.createElement("div");
  body.textContent = text;
  message.appendChild(body);
  if (payload) {
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(payload, null, 2);
    message.appendChild(pre);
  }
  $("messages").appendChild(message);
  $("messages").scrollTop = $("messages").scrollHeight;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    addMessage(`HTTP ${response.status}`, "error", data);
    throw data;
  }
  return data;
}

function parseJsonField(id) {
  const raw = $(id).value.trim();
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    throw new Error(`${id} must be a JSON array`);
  }
  return parsed;
}

function splitEmails(value) {
  return value
    .split(",")
    .map((email) => email.trim())
    .filter(Boolean);
}

function profilePayload() {
  return {
    name: $("profile-name").value.trim(),
    email: $("profile-email").value.trim() || null,
    phone: $("profile-phone").value.trim() || null,
    location: $("profile-location").value.trim() || null,
    headline: $("profile-headline").value.trim() || null,
    summary: $("profile-summary").value.trim() || null,
    skills: $("profile-skills").value.split(",").map((skill) => skill.trim()).filter(Boolean),
    experience: parseJsonField("profile-experience"),
    projects: parseJsonField("profile-projects"),
    education: parseJsonField("profile-education"),
    resume_text: $("profile-resume").value.trim() || null,
    resume_file_path: state.profile?.resume_file_path || null,
  };
}

function fillProfile(profile) {
  $("profile-name").value = profile.name || "";
  $("profile-email").value = profile.email || "";
  $("profile-phone").value = profile.phone || "";
  $("profile-location").value = profile.location || "";
  $("profile-headline").value = profile.headline || "";
  $("profile-summary").value = profile.summary || "";
  $("profile-skills").value = (profile.skills || []).join(", ");
  $("profile-experience").value = JSON.stringify(profile.experience || [], null, 2);
  $("profile-projects").value = JSON.stringify(profile.projects || [], null, 2);
  $("profile-education").value = JSON.stringify(profile.education || [], null, 2);
  $("profile-resume").value = profile.resume_text || "";
  $("resume-status").textContent = profile.resume_file_path
    ? `Resume saved: ${profile.resume_file_path.split(/[\\/]/).pop()}`
    : "No resume uploaded yet.";
}

async function loadMe() {
  try {
    state.me = await api("/me");
    $("account-status").textContent = `Logged in as ${state.me.email}`;
    $("login-screen").classList.add("hidden");
    $("workspace").classList.remove("hidden");
  } catch {
    state.me = null;
    $("login-screen").classList.remove("hidden");
    $("workspace").classList.add("hidden");
  }
}

async function loadProfile() {
  try {
    state.profile = await api("/candidate-profile/me");
    fillProfile(state.profile);
  } catch {
    $("profile-experience").value = "[]";
    $("profile-projects").value = "[]";
    $("profile-education").value = "[]";
  }
}

async function saveProfile(event) {
  event.preventDefault();
  try {
    const method = state.profile ? "PUT" : "POST";
    const path = state.profile ? "/candidate-profile/me" : "/candidate-profile";
    state.profile = await api(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profilePayload()),
    });
    fillProfile(state.profile);
    addMessage("Profile saved.", "success");
  } catch (error) {
    if (error instanceof Error) {
      addMessage(error.message, "error");
    }
  }
}

async function uploadResume(event) {
  event.preventDefault();
  const file = $("resume-file").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  state.profile = await api("/profile/resume", { method: "POST", body: form });
  fillProfile(state.profile);
  addMessage(`Resume uploaded: ${file.name}`, "success");
}

function renderDraft(draft) {
  if (!draft || draft.status === "blocked_zero_skill_overlap") {
    return;
  }
  state.draft = draft;
  $("draft-panel").classList.remove("hidden");
  $("draft-recipient").value = draft.recipient_email || "";
  $("draft-cc").value = (draft.cc || []).join(", ");
  $("draft-bcc").value = (draft.bcc || []).join(", ");
  $("draft-subject").value = draft.subject || "";
  $("draft-body").value = draft.body || "";
  $("claim-evidence").textContent = JSON.stringify(draft.claim_evidence_map || {}, null, 2);
  $("draft-attachments").textContent = (draft.attachments || []).length
    ? `Attachments: ${(draft.attachments || []).map((item) => item.filename).join(", ")}`
    : "Attachments: none";

  const approved = Boolean(draft.approved_at);
  $("draft-state").textContent = approved ? "Approved and frozen" : "Editable";
  ["draft-recipient", "draft-cc", "draft-bcc", "draft-subject", "draft-body"].forEach((id) => {
    $(id).disabled = approved;
  });
  $("save-draft").disabled = approved;
  $("approve-draft").disabled = approved;
  $("send-draft").disabled = !approved;
}

async function sendChat(confirmZeroOverlap = false) {
  if (!state.profile) {
    addMessage("Save your profile first.", "error");
    return;
  }
  const text = $("chat-input").value.trim();
  const files = Array.from($("chat-files").files);
  if (!text && files.length === 0) {
    addMessage("Type a JD or attach a file.", "error");
    return;
  }

  addMessage(text || `Attached ${files.length} file(s)`, "user");
  const form = new FormData();
  form.append("message", text);
  form.append("confirm_zero_overlap", confirmZeroOverlap ? "true" : "false");
  if (state.draft && text) {
    form.append("draft_id", state.draft.id);
  }
  files.forEach((file) => form.append("files", file));

  const result = await api("/chat/messages", { method: "POST", body: form });
  if (result.application) {
    state.application = result.application;
  }
  if (result.draft?.status === "blocked_zero_skill_overlap") {
    state.zeroOverlapPending = true;
    $("confirm-zero-overlap").classList.remove("hidden");
    addMessage(result.draft.message, "error", result.draft);
  } else {
    state.zeroOverlapPending = false;
    $("confirm-zero-overlap").classList.add("hidden");
    renderDraft(result.draft);
    addMessage(`${result.message}${result.model_used ? ` Model: ${result.model_used}` : ""}`, "app");
  }
  $("chat-input").value = "";
  $("chat-files").value = "";
  await renderHistory();
}

async function saveDraft() {
  if (!state.draft) return;
  state.draft = await api(`/email-drafts/${state.draft.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      recipient_email: $("draft-recipient").value.trim() || null,
      cc: splitEmails($("draft-cc").value),
      bcc: splitEmails($("draft-bcc").value),
      subject: $("draft-subject").value.trim(),
      body: $("draft-body").value,
    }),
  });
  renderDraft(state.draft);
  addMessage("Draft saved.", "success");
}

async function approveDraft() {
  if (!state.draft) return;
  await saveDraft();
  state.draft = await api(`/email-drafts/${state.draft.id}/approve`, { method: "POST" });
  renderDraft(state.draft);
  addMessage("Draft approved and frozen.", "success");
}

async function sendDraft() {
  if (!state.draft) return;
  const result = await api(`/email-drafts/${state.draft.id}/send`, { method: "POST" });
  $("send-draft").disabled = true;
  addMessage(`Email sent with Gmail. Message id: ${result.provider_message_id}`, "success", result);
  await renderHistory();
}

async function renderHistory() {
  try {
    const applications = await api("/applications");
    const list = $("history-list");
    list.innerHTML = "";
    if (!applications.length) {
      list.textContent = "No applications yet.";
      return;
    }
    applications.slice(0, 10).forEach((application) => {
      const item = document.createElement("div");
      item.className = "history-item";
      item.textContent = `#${application.id} - ${application.status}`;
      item.addEventListener("click", async () => {
        const logs = await api(`/applications/${application.id}/send-log`);
        addMessage(`Send log for application #${application.id}`, "app", logs);
      });
      list.appendChild(item);
    });
  } catch {
    $("history-list").textContent = "History unavailable.";
  }
}

function bindEvents() {
  $("theme-toggle").addEventListener("click", () => {
    document.body.classList.toggle("light");
    $("theme-toggle").textContent = document.body.classList.contains("light") ? "Dark" : "Light";
  });
  $("logout").addEventListener("click", async () => {
    await fetch("/auth/logout", { method: "POST" });
    window.location.href = "/";
  });
  $("profile-form").addEventListener("submit", saveProfile);
  $("resume-form").addEventListener("submit", uploadResume);
  $("chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendChat(false);
  });
  $("confirm-zero-overlap").addEventListener("click", async () => {
    await sendChat(true);
  });
  $("save-draft").addEventListener("click", saveDraft);
  $("approve-draft").addEventListener("click", approveDraft);
  $("send-draft").addEventListener("click", sendDraft);
}

bindEvents();
loadMe().then(() => {
  if (state.me) {
    loadProfile();
    renderHistory();
  }
});
