let csrfToken = "";
let setupRequired = false;
let events = [];
let currentEventFilter = "upcoming";
const toast = document.getElementById("toast");
const eventList = document.getElementById("eventList");
const API_BASE_URL = location.port === "5500" && ["127.0.0.1", "localhost"].includes(location.hostname)
  ? `${location.protocol}//${location.hostname}:8000`
  : "";

async function api(path, options) {
  const requestOptions = { credentials: "include", ...options };
  requestOptions.headers = { ...(requestOptions.headers || {}) };
  if (requestOptions.body && typeof requestOptions.body !== "string") {
    requestOptions.headers["Content-Type"] = "application/json";
    requestOptions.body = JSON.stringify(requestOptions.body);
  }
  if (["POST", "PATCH", "DELETE"].includes(requestOptions.method || "GET")) {
    requestOptions.headers["X-CSRF-Token"] = csrfToken;
  }
  const response = await fetch(`${API_BASE_URL}${path}`, requestOptions);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The request could not be completed.");
  return result;
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => toast.classList.remove("show"), 2800);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);
}

function setAuthMode(mode) {
  const registering = mode === "register";
  const adminLogin = mode === "admin-login";
  document.getElementById("loginForm").classList.toggle("hidden", registering || adminLogin);
  document.getElementById("adminLoginForm").classList.toggle("hidden", !adminLogin);
  document.getElementById("registerForm").classList.toggle("hidden", !registering);
  document.getElementById("authTitle").textContent = registering
    ? "Create your account"
    : adminLogin ? "Administrator sign in" : "Welcome back";
  document.getElementById("authDescription").textContent = registering
    ? "Join your campus community."
    : adminLogin ? "Sign in with your administrator account."
    : "Sign in to find events and connect with your campus.";
  document.getElementById("authToggle").textContent = registering
    ? "Already have an account? Sign in"
    : "New here? Create an account";
  document.getElementById("authToggle").dataset.mode = registering ? "login" : "register";
  document.getElementById("authToggle").classList.toggle("hidden", setupRequired || adminLogin);
  document.getElementById("adminLoginToggle").classList.toggle("hidden", setupRequired || mode !== "login");
  document.getElementById("adminLoginBack").classList.toggle("hidden", !adminLogin);
}

function setAuthenticated(user) {
  document.getElementById("authScreen").classList.toggle("hidden", Boolean(user));
  document.getElementById("appShell").classList.toggle("hidden", !user);
  if (!user) return;
  document.getElementById("greetingName").textContent = user.name.split(/\s+/)[0];
  document.getElementById("profileName").textContent = user.name;
  document.getElementById("profileEmail").textContent = user.email;
  document.getElementById("profileInitial").textContent = user.name.charAt(0).toUpperCase();
  document.getElementById("profileRole").textContent = user.role === "admin" ? "Administrator" : "Campus member";
  const isAdmin = user.role === "admin";
  document.getElementById("adminNav").classList.toggle("hidden", !isAdmin);
  document.getElementById("adminQuickLink").classList.toggle("hidden", !isAdmin);
}

async function refreshSession() {
  const status = await api("/api/status");
  csrfToken = status.csrf_token;
  setupRequired = status.setup_required;
  document.getElementById("setupNotice").classList.toggle("hidden", !status.setup_required);
  if (status.setup_required) setAuthMode("register");
  else setAuthMode("login");
  setAuthenticated(status.user);
  if (status.user) {
    await Promise.all([loadEvents(), loadGroups()]);
  }
}

async function handleAuthSubmit(form, path) {
  const values = Object.fromEntries(new FormData(form));
  await api(path, { method: "POST", body: values });
  form.reset();
  await refreshSession();
  showToast(path.endsWith("register") ? "Your account is ready." : "Welcome back.");
}

function showPage(pageName) {
  const target = document.getElementById(`${pageName}Page`);
  if (!target) return;
  document.querySelectorAll(".page").forEach((page) => page.classList.remove("active"));
  target.classList.add("active");
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.page === pageName));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderEvents() {
  const search = document.getElementById("searchInput").value.toLowerCase().trim();
  const category = document.getElementById("categoryFilter").value;
  const filtered = events.filter((item) => {
    const matchesText = `${item.title} ${item.category} ${item.location} ${item.description}`.toLowerCase().includes(search);
    const matchesCategory = category === "all" || item.category === category;
    const matchesTab = currentEventFilter === "upcoming" || item.attendee_count > 0;
    return matchesText && matchesCategory && matchesTab;
  });
  if (!filtered.length) {
    eventList.innerHTML = `<div class="empty-state">${events.length ? "No events match these filters." : "No events have been published yet. Host one to get started."}</div>`;
    renderCalendar();
    return;
  }
  eventList.innerHTML = filtered.map((item) => `
    <article class="event-card">
      <div class="event-top"><span class="tag">${escapeHtml(item.category)}</span><span class="event-status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></div>
      <h3>${escapeHtml(item.title)}</h3>
      <p class="event-meta">◷ <span>${escapeHtml(new Date(item.starts_at).toLocaleString())}</span></p>
      <p class="event-meta">⌖ <span>${escapeHtml(item.location)}</span></p>
      ${item.description ? `<p class="event-description">${escapeHtml(item.description)}</p>` : ""}
      <div class="event-bottom"><span class="attending">${item.attendee_count} attending</span>
        <div class="event-actions">
          ${item.status === "approved" ? `<button class="rsvp-button ${item.is_joined ? "joined" : ""}" type="button" data-rsvp="${item.id}">${item.is_joined ? "✓ Going" : "RSVP"}</button>` : ""}
          ${item.status === "approved" ? `<button class="report-button" type="button" data-report="${item.id}">Report</button>` : ""}
        </div>
      </div>
    </article>`).join("");
  renderCalendar();
}

function renderCalendar() {
  const joined = events.filter((item) => item.is_joined && item.status === "approved");
  const calendar = document.getElementById("calendarEvents");
  calendar.innerHTML = joined.length
    ? joined.map((item) => `<p><strong>${escapeHtml(item.title)}</strong><br><span class="muted">${escapeHtml(new Date(item.starts_at).toLocaleString())} · ${escapeHtml(item.location)}</span></p>`).join("")
    : "You haven't joined any events yet.";
}

async function loadEvents() {
  events = await api("/api/events");
  renderEvents();
}

async function loadGroups() {
  const groups = await api("/api/groups");
  const markup = groups.length ? groups.map((group) => `
    <article class="group-card">
      <div class="group-art purple-art" aria-hidden="true">✦</div><span class="tag">${escapeHtml(group.category)}</span>
      <h3>${escapeHtml(group.name)}</h3><p>${escapeHtml(group.description)}</p>
      <div class="card-footer"><span>Created by ${escapeHtml(group.creator_name)}</span></div>
    </article>`).join("") : '<div class="empty-state">No groups have been created yet.</div>';
  document.getElementById("groupList").innerHTML = markup;
}

document.getElementById("authToggle").addEventListener("click", (event) => setAuthMode(event.currentTarget.dataset.mode));
document.getElementById("adminLoginToggle").addEventListener("click", () => setAuthMode("admin-login"));
document.getElementById("adminLoginBack").addEventListener("click", () => setAuthMode("login"));
document.getElementById("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await handleAuthSubmit(event.currentTarget, "/api/auth/login"); }
  catch (error) { showToast(error.message); }
});
document.getElementById("registerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await handleAuthSubmit(event.currentTarget, "/api/auth/register"); }
  catch (error) { showToast(error.message); }
});
document.getElementById("adminLoginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await handleAuthSubmit(event.currentTarget, "/api/auth/admin-login"); }
  catch (error) { showToast(error.message); }
});

async function signOut() {
  try {
    await api("/api/auth/logout", { method: "POST" });
    csrfToken = "";
    setAuthenticated(null);
    await refreshSession();
    showToast("You have signed out.");
  } catch (error) { showToast(error.message); }
}
document.getElementById("logoutButton").addEventListener("click", signOut);
document.getElementById("settingsSignOut").addEventListener("click", signOut);

document.querySelectorAll(".nav-item[data-page], .quick-links button[data-page], .settings-list button[data-page]").forEach((button) => {
  button.addEventListener("click", () => showPage(button.dataset.page));
});
document.getElementById("filterButton").addEventListener("click", () => document.getElementById("filterPanel").classList.toggle("hidden"));
document.getElementById("searchInput").addEventListener("input", renderEvents);
document.getElementById("categoryFilter").addEventListener("change", renderEvents);
document.querySelectorAll("[data-event-filter]").forEach((button) => button.addEventListener("click", () => {
  currentEventFilter = button.dataset.eventFilter;
  document.querySelectorAll("[data-event-filter]").forEach((tab) => tab.classList.toggle("selected", tab === button));
  renderEvents();
}));

eventList.addEventListener("click", async (event) => {
  const rsvpButton = event.target.closest("[data-rsvp]");
  const reportButton = event.target.closest("[data-report]");
  try {
    if (rsvpButton) {
      await api(`/api/events/${rsvpButton.dataset.rsvp}/rsvp`, { method: "POST" });
      await loadEvents();
    }
    if (reportButton) {
      const reason = window.prompt("Why are you reporting this event?");
      if (reason?.trim()) {
        await api("/api/reports", { method: "POST", body: { target_type: "event", target_id: Number(reportButton.dataset.report), reason: reason.trim() } });
        showToast("Your report has been sent to the administrators.");
      }
    }
  } catch (error) { showToast(error.message); }
});

const hostModal = document.getElementById("hostModal");
document.getElementById("openHostModal").addEventListener("click", () => hostModal.classList.remove("hidden"));
document.getElementById("closeHostModal").addEventListener("click", () => hostModal.classList.add("hidden"));
hostModal.addEventListener("click", (event) => { if (event.target === hostModal) hostModal.classList.add("hidden"); });
document.getElementById("hostForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const result = await api("/api/events", { method: "POST", body: payload });
    event.currentTarget.reset();
    hostModal.classList.add("hidden");
    await loadEvents();
    showToast(result.status === "approved" ? "Event published." : "Event submitted for administrator approval.");
  } catch (error) { showToast(error.message); }
});

refreshSession().catch((error) => {
  document.getElementById("authScreen").classList.remove("hidden");
  showToast(`Could not connect to the app: ${error.message}`);
});
