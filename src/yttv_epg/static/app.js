async function readError(response) {
  try {
    const data = await response.json();
    return data.detail || data.error || response.statusText;
  } catch {
    return response.statusText;
  }
}

const SEARCH_KEY = "yttv-event-search";
const SCROLL_KEY = "yttv-scroll";
const errorEl = document.getElementById("auth-error");
const idleAuth = document.getElementById("idle-auth");
const refreshBtn = document.getElementById("refresh-btn");
const toastEl = document.getElementById("refresh-toast");
const toastText = document.getElementById("refresh-toast-text");
const sessionStatus = document.getElementById("session-status");
const lastRefreshValue = document.getElementById("last-refresh-value");
const searchEl = document.getElementById("event-search");
const lastRefreshLabel = lastRefreshValue?.textContent || "—";

const boot = {
  signedIn: document.body.dataset.signedIn === "true",
  sessionExpired: document.body.dataset.sessionExpired === "true",
  lastRefresh: document.body.dataset.lastRefresh || "",
  events: document.body.dataset.events || "",
  allEvents: document.body.dataset.allEvents || "",
  lastError: null,
  primed: false,
};

let actionInFlight = false;
let guideBusy = false;
let reloading = false;

function cookieDraftOpen() {
  const text = document.getElementById("cookie-text");
  return Boolean(idleAuth && !idleAuth.hidden && text && text.value.trim());
}

function showToast(message) {
  if (toastText) toastText.textContent = message;
  if (toastEl) toastEl.hidden = false;
}

function hideToast() {
  if (guideBusy) return;
  if (toastEl) toastEl.hidden = true;
}

function setUserBusy(active, message) {
  guideBusy = active;
  if (refreshBtn) refreshBtn.disabled = active;
  if (active) showToast(message || "Refreshing the guide…");
  else hideToast();
}

function paintSessionStatus(refreshing) {
  if (!sessionStatus) return;
  if (boot.sessionExpired) {
    sessionStatus.textContent = "Session expired";
    sessionStatus.className = "status err";
    return;
  }
  if (boot.signedIn) {
    sessionStatus.textContent = refreshing ? "Updating…" : "Signed in";
    sessionStatus.className = "status ok";
  }
}

function setBackgroundUpdating(active) {
  if (guideBusy) return;
  paintSessionStatus(active);
  if (lastRefreshValue) {
    lastRefreshValue.textContent = active ? "Updating…" : lastRefreshLabel;
  }
}

function restoreView() {
  if (searchEl) {
    const saved = sessionStorage.getItem(SEARCH_KEY) || "";
    if (saved && searchEl.value !== saved) {
      searchEl.value = saved;
      searchEl.dispatchEvent(new Event("input"));
    }
  }
  const y = sessionStorage.getItem(SCROLL_KEY);
  if (y) {
    sessionStorage.removeItem(SCROLL_KEY);
    window.scrollTo(0, Number(y));
  }
}

function reloadDashboard() {
  if (searchEl) sessionStorage.setItem(SEARCH_KEY, searchEl.value);
  sessionStorage.setItem(SCROLL_KEY, String(window.scrollY));
  window.location.reload();
}

async function runAction(message, request) {
  errorEl.textContent = "";
  actionInFlight = true;
  showToast(message);
  try {
    const response = await request();
    if (!response.ok) {
      if (errorEl) errorEl.textContent = await readError(response);
      setUserBusy(false);
      hideToast();
      return;
    }
    showToast("Updated. Reloading…");
    reloadDashboard();
  } catch (exc) {
    if (errorEl) errorEl.textContent = exc.message || "Request failed";
    setUserBusy(false);
    hideToast();
  } finally {
    actionInFlight = false;
  }
}

document.getElementById("import-btn")?.addEventListener("click", () => {
  const text = document.getElementById("cookie-text").value;
  const fileInput = document.getElementById("cookie-file");
  const file = fileInput?.files[0];
  runAction("Importing session and refreshing the guide…", async () => {
    let response;
    if (file) {
      const body = new FormData();
      body.append("file", file);
      body.append("cookies", text);
      response = await fetch("/api/auth/cookies", { method: "POST", body });
    } else {
      response = await fetch("/api/auth/cookies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cookies: text }),
      });
    }
    if (response.ok) {
      const box = document.getElementById("cookie-text");
      if (box) box.value = "";
      if (fileInput) fileInput.value = "";
    }
    return response;
  });
});

document.getElementById("capture-btn")?.addEventListener("click", () => {
  runAction("Saving the session and refreshing the guide…", () =>
    fetch("/api/auth/chrome/capture", { method: "POST" }),
  );
});

refreshBtn?.addEventListener("click", () => {
  setUserBusy(true, "Refreshing the guide…");
  runAction("Refreshing the guide…", () => fetch("/api/refresh", { method: "POST" }));
});

document.getElementById("logout-btn")?.addEventListener("click", () => {
  runAction("Signing out…", () => fetch("/api/auth/logout", { method: "POST" }));
});

async function watchChromeLogin() {
  if (!idleAuth || idleAuth.hidden || !document.getElementById("desktop-wrap")) {
    return;
  }
  const note = document.getElementById("chrome-note");
  while (idleAuth && !idleAuth.hidden) {
    const statusResponse = await fetch("/api/auth/chrome/status");
    const status = statusResponse.ok ? await statusResponse.json() : { available: false };
    if (!status.available) {
      if (note) {
        note.textContent = "The in-container browser is not ready yet. Wait a moment, or paste cookies below.";
      }
      await new Promise((resolve) => setTimeout(resolve, 15000));
      continue;
    }
    if (status.on_login) {
      if (note) note.textContent = "Waiting for you to finish signing in…";
    } else if (status.on_detour || (status.signed_in && !status.on_app)) {
      if (note) {
        note.textContent = "YouTube TV sent this tab away from the app. Opening tv.youtube.com…";
      }
      await fetch("/api/auth/chrome/open", { method: "POST" });
    } else if (!status.signed_in) {
      if (note) note.textContent = "Waiting for you to finish signing in on tv.youtube.com…";
    } else {
      if (note) note.textContent = "Signed in. Saving the session…";
      showToast("Signed in. Saving the session and refreshing the guide…");
      const capture = await fetch("/api/auth/chrome/capture", { method: "POST" });
      if (capture.ok) {
        reloadDashboard();
        return;
      }
      hideToast();
      errorEl.textContent = await readError(capture);
    }
    await new Promise((resolve) => setTimeout(resolve, 4000));
  }
}

watchChromeLogin();

function chipOn(button, on) {
  button.classList.toggle("on", on);
  button.classList.toggle("off", !on);
}

function snapshotChipState() {
  return [...document.querySelectorAll("#sport-chips .chip, #channel-chips .chip")].map((el) => ({
    el,
    on: el.classList.contains("on"),
  }));
}

function restoreChipState(snapshot) {
  snapshot.forEach(({ el, on }) => chipOn(el, on));
}

function applyOptimisticFilter(body) {
  if (body.toggle) {
    const button = document.querySelector(`#sport-chips [data-sport="${body.toggle}"]`);
    if (button) chipOn(button, button.classList.contains("off"));
  }
  if (body.toggle_channel) {
    const button = document.querySelector(`#channel-chips [data-channel="${body.toggle_channel}"]`);
    if (button) chipOn(button, button.classList.contains("off"));
  }
  if (Array.isArray(body.hidden)) {
    const blocked = new Set(body.hidden);
    document.querySelectorAll("#sport-chips [data-sport]").forEach((button) => {
      chipOn(button, !blocked.has(button.dataset.sport));
    });
  }
  if (Array.isArray(body.hidden_channels)) {
    const blocked = new Set(body.hidden_channels);
    document.querySelectorAll("#channel-chips [data-channel]").forEach((button) => {
      chipOn(button, !blocked.has(button.dataset.channel));
    });
  }
}

function hiddenNames(selector, attr) {
  return new Set(
    [...document.querySelectorAll(selector)]
      .filter((el) => el.classList.contains("off"))
      .map((el) => el.getAttribute(attr))
      .filter(Boolean),
  );
}

function applyEventVisibility() {
  const query = (searchEl?.value || "").trim().toLowerCase();
  const sports = hiddenNames("#sport-chips .chip.off", "data-sport");
  const channels = hiddenNames("#channel-chips .chip.off", "data-channel");
  let shown = 0;
  document.querySelectorAll("[data-event-row]").forEach((row) => {
    const haystack = row.getAttribute("data-search") || "";
    const sport = row.getAttribute("data-sport") || "";
    const channel = row.getAttribute("data-channel") || "";
    const hide =
      Boolean(query && !haystack.includes(query)) ||
      (sport && sports.has(sport)) ||
      (channel && channels.has(channel));
    row.hidden = hide;
    if (!hide) shown += 1;
  });
  document.querySelectorAll("[data-day-group]").forEach((group) => {
    const visible = [...group.querySelectorAll("[data-event-row]")].some((row) => !row.hidden);
    group.hidden = !visible;
  });
  const empty = document.getElementById("events-empty");
  if (empty) {
    empty.hidden = shown > 0 || !document.querySelector("[data-event-row]");
  }
}

async function postFilter(body, message) {
  const previous = snapshotChipState();
  applyOptimisticFilter(body);
  applyEventVisibility();
  errorEl.textContent = "";
  actionInFlight = true;
  showToast(message);
  try {
    const response = await fetch("/api/filters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      restoreChipState(previous);
      applyEventVisibility();
      errorEl.textContent = await readError(response);
      hideToast();
      return;
    }
    const data = await response.json();
    const countEl = document.getElementById("event-count");
    if (countEl && data.events != null) countEl.textContent = data.events;
    boot.events = String(data.events ?? boot.events);
    boot.allEvents = String(data.all_events ?? boot.allEvents);
    hideToast();
  } catch (exc) {
    restoreChipState(previous);
    applyEventVisibility();
    errorEl.textContent = exc.message || "Request failed";
    hideToast();
  } finally {
    actionInFlight = false;
  }
}

document.getElementById("sport-chips")?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-sport]");
  if (!button || actionInFlight) return;
  postFilter({ toggle: button.dataset.sport }, "Updating sports…");
});

document.getElementById("channel-chips")?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-channel]");
  if (!button || actionInFlight) return;
  postFilter({ toggle_channel: button.dataset.channel }, "Updating channels…");
});

function listedNames(selector, attr) {
  return [...document.querySelectorAll(selector)].map((el) => el.getAttribute(attr)).filter(Boolean);
}

document.getElementById("select-sports")?.addEventListener("click", () => {
  postFilter({ hidden: [] }, "Including all sports…");
});

document.getElementById("unselect-sports")?.addEventListener("click", () => {
  postFilter({ hidden: listedNames("#sport-chips [data-sport]", "data-sport") }, "Excluding all sports…");
});

document.getElementById("select-channels")?.addEventListener("click", () => {
  postFilter({ hidden_channels: [] }, "Including all stations…");
});

document.getElementById("unselect-channels")?.addEventListener("click", () => {
  postFilter({ hidden_channels: listedNames("#channel-chips [data-channel]", "data-channel") }, "Excluding all stations…");
});

searchEl?.addEventListener("input", () => {
  sessionStorage.setItem(SEARCH_KEY, searchEl.value);
  applyEventVisibility();
});

function statusChanged(status) {
  const lastRefresh = status.last_refresh || "";
  const lastError = status.last_error || "";
  if (status.signed_in !== boot.signedIn) return true;
  if (Boolean(status.session_expired) !== boot.sessionExpired) return true;
  if (lastRefresh !== boot.lastRefresh) return true;
  if (boot.lastError !== null && lastError !== boot.lastError) return true;
  if (!status.refreshing && String(status.all_events ?? "") !== String(boot.allEvents)) return true;
  return false;
}

function snapshotStatus(status) {
  boot.lastError = status.last_error || "";
  boot.lastRefresh = status.last_refresh || boot.lastRefresh;
  boot.events = String(status.events ?? boot.events);
  boot.allEvents = String(status.all_events ?? boot.allEvents);
  boot.signedIn = Boolean(status.signed_in);
  boot.sessionExpired = Boolean(status.session_expired);
  boot.primed = true;
}

async function pollStatus() {
  if (actionInFlight || reloading) return;
  let status;
  try {
    const response = await fetch("/api/status");
    if (!response.ok) return;
    status = await response.json();
  } catch {
    return;
  }
  setBackgroundUpdating(Boolean(status.refreshing));
  if (!boot.primed) {
    snapshotStatus(status);
    return;
  }
  if (status.refreshing) return;
  if (statusChanged(status) && !(cookieDraftOpen() && !status.signed_in)) {
    reloading = true;
    showToast("Guide updated. Reloading…");
    reloadDashboard();
    return;
  }
  boot.lastError = status.last_error || "";
}

restoreView();
applyEventVisibility();
pollStatus();
setInterval(pollStatus, 15000);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") pollStatus();
});
