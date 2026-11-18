let csrfToken = "";
let currentUser = null;
const adminToast = document.getElementById("adminToast");
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

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);
}

function showToast(message) {
  adminToast.textContent = message;
  adminToast.classList.add("show");
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => adminToast.classList.remove("show"), 2800);
}

async function loadAdminData() {
  const [users, events, groups, reports] = await Promise.all([
    api("/api/admin/users"), api("/api/admin/events"), api("/api/groups"), api("/api/admin/reports")
  ]);
  const adminCount = users.filter((user) => user.role === "admin").length;
  document.getElementById("adminLimitMessage").textContent = `Administrator accounts: ${adminCount} of 3.`;
  document.getElementById("adminUserList").innerHTML = users.length ? users.map((user) => `
    <article class="admin-card">
      <div><strong>${escapeHtml(user.name)}</strong><span>${escapeHtml(user.email)}</span><small>${escapeHtml(user.role)} · ${escapeHtml(user.status)}</small></div>
      <div class="admin-user-actions">
        <select aria-label="Role for ${escapeHtml(user.name)}" data-user-role="${user.id}" ${user.id === currentUser.id ? "disabled" : ""}>
          <option value="user" ${user.role === "user" ? "selected" : ""}>Member</option>
          <option value="admin" ${user.role === "admin" ? "selected" : ""} ${user.role !== "admin" && adminCount >= 3 ? "disabled" : ""}>Administrator</option>
        </select>
        ${user.id !== currentUser.id ? `<button class="secondary-button" type="button" data-user-status="${user.id}" data-next-status="${user.status === "active" ? "disabled" : "active"}">${user.status === "active" ? "Disable" : "Enable"}</button>` : "<small>Current account</small>"}
      </div>
    </article>`).join("") : '<div class="empty-state">No accounts yet.</div>';
  document.getElementById("adminEventList").innerHTML = events.length ? events.map((item) => `
    <article class="admin-card">
      <div><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.creator_name)} · ${escapeHtml(item.location)}</span><small>${escapeHtml(item.status)} · ${item.attendee_count} attending · ${escapeHtml(new Date(item.starts_at).toLocaleString())}</small></div>
      <div class="admin-actions">
        <select aria-label="Event status" data-event-status="${item.id}"><option ${item.status === "pending" ? "selected" : ""}>pending</option><option ${item.status === "approved" ? "selected" : ""}>approved</option><option ${item.status === "rejected" ? "selected" : ""}>rejected</option></select>
        <button class="danger-button" type="button" data-delete-event="${item.id}">Delete</button>
      </div>
    </article>`).join("") : '<div class="empty-state">No events to review.</div>';
  document.getElementById("adminGroupList").innerHTML = groups.length ? groups.map((group) => `
    <article class="admin-card"><div><strong>${escapeHtml(group.name)}</strong><span>${escapeHtml(group.category)} · ${escapeHtml(group.description)}</span></div><button class="danger-button" type="button" data-delete-group="${group.id}">Delete</button></article>`).join("") : '<div class="empty-state">No groups yet. Create the first one above.</div>';
  document.getElementById("adminReportList").innerHTML = reports.length ? reports.map((report) => `
    <article class="admin-card"><div><strong>${escapeHtml(report.event_title || "Removed event")}</strong><span>Reported by ${escapeHtml(report.reporter_name)} · ${escapeHtml(report.reason)}</span><small>${escapeHtml(report.status)}</small></div>
      <select aria-label="Report status" data-report-status="${report.id}"><option ${report.status === "open" ? "selected" : ""}>open</option><option ${report.status === "resolved" ? "selected" : ""}>resolved</option><option ${report.status === "dismissed" ? "selected" : ""}>dismissed</option></select>
    </article>`).join("") : '<div class="empty-state">No reports have been submitted.</div>';
}

document.querySelectorAll("[data-admin-view]").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll("[data-admin-view]").forEach((tab) => tab.classList.toggle("selected", tab === button));
  document.querySelectorAll(".admin-section").forEach((section) => section.classList.toggle("hidden", section.id !== `admin${button.dataset.adminView[0].toUpperCase()}${button.dataset.adminView.slice(1)}`));
}));

document.getElementById("groupForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/admin/groups", { method: "POST", body: Object.fromEntries(new FormData(event.currentTarget)) });
    event.currentTarget.reset();
    await loadAdminData();
    showToast("Group created.");
  } catch (error) { showToast(error.message); }
});

document.getElementById("adminShell").addEventListener("change", async (event) => {
  const eventStatus = event.target.closest("[data-event-status]");
  const reportStatus = event.target.closest("[data-report-status]");
  const userRole = event.target.closest("[data-user-role]");
  try {
    if (userRole) {
      await api(`/api/admin/users/${userRole.dataset.userRole}`, { method: "PATCH", body: { role: userRole.value } });
      await loadAdminData();
      showToast("Account role updated.");
    }
    if (eventStatus) {
      await api(`/api/admin/events/${eventStatus.dataset.eventStatus}`, { method: "PATCH", body: { status: eventStatus.value } });
      await loadAdminData();
      showToast("Event status updated.");
    }
    if (reportStatus) {
      await api(`/api/admin/reports/${reportStatus.dataset.reportStatus}`, { method: "PATCH", body: { status: reportStatus.value } });
      await loadAdminData();
      showToast("Report updated.");
    }
  } catch (error) { showToast(error.message); }
});

document.getElementById("adminShell").addEventListener("click", async (event) => {
  const userButton = event.target.closest("[data-user-status]");
  const deleteEventButton = event.target.closest("[data-delete-event]");
  const deleteGroupButton = event.target.closest("[data-delete-group]");
  try {
    if (userButton) {
      await api(`/api/admin/users/${userButton.dataset.userStatus}`, { method: "PATCH", body: { status: userButton.dataset.nextStatus } });
      await loadAdminData();
      showToast("Account status updated.");
    }
    if (deleteEventButton && window.confirm("Delete this event and its RSVPs?")) {
      await api(`/api/admin/events/${deleteEventButton.dataset.deleteEvent}`, { method: "DELETE" });
      await loadAdminData();
      showToast("Event deleted.");
    }
    if (deleteGroupButton && window.confirm("Delete this group?")) {
      await api(`/api/admin/groups/${deleteGroupButton.dataset.deleteGroup}`, { method: "DELETE" });
      await loadAdminData();
      showToast("Group deleted.");
    }
  } catch (error) { showToast(error.message); }
});

document.getElementById("adminLogoutButton").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
    window.location.assign("/");
  } catch (error) { showToast(error.message); }
});

async function initializeAdminPanel() {
  const response = await fetch(`${API_BASE_URL}/api/status`, { credentials: "include" });
  const status = await response.json();
  if (!response.ok || !status.user || status.user.role !== "admin") {
    window.location.replace("/");
    return;
  }
  csrfToken = status.csrf_token;
  currentUser = status.user;
  document.getElementById("adminGate").classList.add("hidden");
  document.getElementById("adminShell").classList.remove("hidden");
  await loadAdminData();
}

initializeAdminPanel().catch((error) => showToast(error.message));
