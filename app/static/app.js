const state = {
  profile: null,
  job: null,
  application: null,
  draft: null,
  sent: false,
};

const $ = (id) => document.getElementById(id);

function showMessage(title, payload, type = "info") {
  $("messages").textContent = `${title}\n${JSON.stringify(payload, null, 2)}`;
  $("messages").className = type;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    showMessage(`HTTP ${response.status}`, data, "error");
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

function profilePayload() {
  return {
    name: $("profile-name").value.trim(),
    headline: $("profile-headline").value.trim() || null,
    summary: $("profile-summary").value.trim() || null,
    skills: $("profile-skills").value.split(",").map((skill) => skill.trim()).filter(Boolean),
    experience: parseJsonField("profile-experience"),
    projects: parseJsonField("profile-projects"),
    education: parseJsonField("profile-education"),
    resume_text: $("profile-resume").value.trim() || null,
    resume_file_path: null,
  };
}

function fillProfile(profile) {
  $("profile-name").value = profile.name || "";
  $("profile-headline").value = profile.headline || "";
  $("profile-summary").value = profile.summary || "";
  $("profile-skills").value = (profile.skills || []).join(", ");
  $("profile-experience").value = JSON.stringify(profile.experience || [], null, 2);
  $("profile-projects").value = JSON.stringify(profile.projects || [], null, 2);
  $("profile-education").value = JSON.stringify(profile.education || [], null, 2);
  $("profile-resume").value = profile.resume_text || "";
}

function renderPills(id, skills, kind) {
  const container = $(id);
  container.innerHTML = "";
  if (!skills || skills.length === 0) {
    container.textContent = "None";
    return;
  }
  skills.forEach((skill) => {
    const span = document.createElement("span");
    span.className = `pill ${kind}`;
    span.textContent = skill;
    container.appendChild(span);
  });
}

function addHistory(applicationId) {
  const ids = JSON.parse(localStorage.getItem("emailAgentApplicationIds") || "[]");
  if (!ids.includes(applicationId)) {
    ids.unshift(applicationId);
    localStorage.setItem("emailAgentApplicationIds", JSON.stringify(ids.slice(0, 25)));
  }
}

async function renderHistory() {
  const ids = JSON.parse(localStorage.getItem("emailAgentApplicationIds") || "[]");
  const list = $("history-list");
  list.innerHTML = "";
  if (ids.length === 0) {
    list.textContent = "No applications created from this browser yet.";
    return;
  }

  for (const id of ids) {
    const row = document.createElement("div");
    row.className = "history-item";
    try {
      const app = await api(`/applications/${id}`);
      row.innerHTML = `<span>Application #${app.id} - ${app.status}</span>`;
      const button = document.createElement("button");
      button.textContent = "View Send Log";
      button.addEventListener("click", () => loadSendLog(app.id));
      row.appendChild(button);
    } catch {
      row.textContent = `Application #${id} - unavailable`;
    }
    list.appendChild(row);
  }
}

async function loadSendLog(applicationId) {
  const logs = await api(`/applications/${applicationId}/send-log`);
  $("history-log").textContent = JSON.stringify(logs, null, 2);
}

async function loadProfile() {
  try {
    const profile = await api("/candidate-profile/me");
    state.profile = profile;
    fillProfile(profile);
    showMessage("Loaded profile", profile);
  } catch (error) {
    $("profile-experience").value = "[]";
    $("profile-projects").value = "[]";
    $("profile-education").value = "[]";
  }
}

async function saveProfile(event) {
  event.preventDefault();
  try {
    const payload = profilePayload();
    const method = state.profile ? "PUT" : "POST";
    const path = state.profile ? "/candidate-profile/me" : "/candidate-profile";
    const profile = await api(path, { method, body: JSON.stringify(payload) });
    state.profile = profile;
    fillProfile(profile);
    showMessage("Saved profile", profile);
  } catch (error) {
    if (error instanceof Error) {
      showMessage("Profile form error", { detail: error.message }, "error");
    }
  }
}

async function createAndAnalyze(event) {
  event.preventDefault();
  if (!state.profile) {
    showMessage("Profile required", { detail: "Save a candidate profile before creating an application." }, "error");
    return;
  }

  const job = await api("/job-posts", {
    method: "POST",
    body: JSON.stringify({ raw_text: $("job-text").value, source_type: "text" }),
  });
  const application = await api("/applications", {
    method: "POST",
    body: JSON.stringify({ candidate_profile_id: state.profile.id, job_post_id: job.id }),
  });
  const analyzed = await api(`/applications/${application.id}/analyze`, { method: "POST" });
  const hydratedJob = await api(`/job-posts/${job.id}`);

  state.job = hydratedJob;
  state.application = analyzed;
  state.draft = null;
  state.sent = false;
  addHistory(analyzed.id);

  const extracted = hydratedJob.extracted || {};
  $("job-company").value = hydratedJob.company || extracted.company || "";
  $("job-role").value = hydratedJob.role_title || extracted.role_title || "";
  $("job-recipient").value = hydratedJob.recipient_email || extracted.recipient_email || "";
  $("job-skills").value = (extracted.required_skills || []).join(", ");
  renderPills("matched-skills", analyzed.match_result?.matched_skills || [], "match");
  renderPills("gap-skills", analyzed.match_result?.gap_skills || [], "gap");
  $("analysis-panel").classList.remove("hidden");
  $("generate-draft").disabled = false;
  $("confirm-zero-overlap").classList.add("hidden");
  $("zero-warning").classList.add("hidden");
  $("draft-panel").classList.add("hidden");
  $("approve-draft").disabled = true;
  $("send-draft").disabled = true;

  await renderHistory();
  showMessage("Analyzed application", analyzed);
}

function renderDraft(draft) {
  state.draft = draft;
  $("draft-recipient").value = draft.recipient_email || "";
  $("draft-subject").value = draft.subject || "";
  $("draft-body").value = draft.body || "";
  $("claim-evidence").textContent = JSON.stringify(draft.claim_evidence_map || {}, null, 2);
  $("draft-panel").classList.remove("hidden");
  $("approve-draft").disabled = Boolean(draft.approved_at);
  $("send-draft").disabled = !draft.approved_at || state.sent;
  $("save-draft-edits").disabled = Boolean(draft.approved_at);
  $("draft-recipient").disabled = Boolean(draft.approved_at);
  $("draft-subject").disabled = Boolean(draft.approved_at);
  $("draft-body").disabled = Boolean(draft.approved_at);
}

async function generateDraft(confirmZeroOverlap = false) {
  if (!state.application) return;
  const suffix = confirmZeroOverlap ? "?confirm_zero_overlap=true" : "";
  const result = await api(`/applications/${state.application.id}/draft-email${suffix}`, { method: "POST" });

  if (result.status === "blocked_zero_skill_overlap") {
    $("zero-warning").textContent = `${result.message}\nGaps: ${(result.gap_skills || []).join(", ")}`;
    $("zero-warning").classList.remove("hidden");
    $("confirm-zero-overlap").classList.remove("hidden");
    showMessage("Zero-overlap warning", result);
    return;
  }

  $("zero-warning").classList.add("hidden");
  $("confirm-zero-overlap").classList.add("hidden");
  renderDraft(result);
  showMessage("Generated draft", result);
}

async function saveDraftEdits() {
  if (!state.draft) return;
  const payload = {
    recipient_email: $("draft-recipient").value.trim() || null,
    subject: $("draft-subject").value.trim(),
    body: $("draft-body").value,
  };
  const draft = await api(`/email-drafts/${state.draft.id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  renderDraft(draft);
  showMessage("Saved draft edits", draft);
}

async function approveDraft() {
  if (!state.draft) return;
  const draft = await api(`/email-drafts/${state.draft.id}/approve`, { method: "POST" });
  renderDraft(draft);
  $("send-result").className = "success";
  $("send-result").textContent = "Draft approved and locked. Editing is disabled.";
  showMessage("Approved draft", draft);
  await renderHistory();
}

async function sendDraft() {
  if (!state.draft) return;
  const result = await api(`/email-drafts/${state.draft.id}/send`, { method: "POST" });
  state.sent = true;
  $("send-draft").disabled = true;
  $("send-result").className = "success";
  $("send-result").textContent = `Mock send succeeded. Provider message id: ${result.provider_message_id}`;
  showMessage("Send result", result);
  await loadSendLog(state.draft.application_id);
  await renderHistory();
}

function bindEvents() {
  $("profile-form").addEventListener("submit", saveProfile);
  $("application-form").addEventListener("submit", createAndAnalyze);
  $("generate-draft").addEventListener("click", () => generateDraft(false));
  $("confirm-zero-overlap").addEventListener("click", () => generateDraft(true));
  $("save-draft-edits").addEventListener("click", saveDraftEdits);
  $("approve-draft").addEventListener("click", approveDraft);
  $("send-draft").addEventListener("click", sendDraft);
}

bindEvents();
loadProfile();
renderHistory();
