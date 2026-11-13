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
const searchEl = document.getElementById("event-search");
const laneCountInput = document.getElementById("lane-count");

const boot = {
  signedIn: document.body.dataset.signedIn === "true",
  sessionExpired: document.body.dataset.sessionExpired === "true",
  lastRefresh: document.body.dataset.lastRefresh || "",
  events: document.body.dataset.events || "",
  allEvents: document.body.dataset.allEvents || "",
  filterRevision: document.body.dataset.filterRevision || "",
  laneCount: Number(laneCountInput?.defaultValue),
  lastError: null,
  primed: false,
  loginDesktopDismissed: false,
};

let actionInFlight = false;
let filterSavePending = false;
let filterGeneration = 0;
const languageToggle = document.getElementById("hide-spanish");
let confirmedHideSpanish = Boolean(languageToggle?.defaultChecked);
if (languageToggle) languageToggle.checked = confirmedHideSpanish;
boot.hideSpanish = confirmedHideSpanish;

function confirmLanguage(value) {
  if (typeof value !== "boolean") return;
  confirmedHideSpanish = value;
  boot.hideSpanish = value;
  if (languageToggle) languageToggle.checked = value;
}
const liveOnAirToggle = document.getElementById("xmltv-live-on-air");
let confirmedLiveOnAir = Boolean(liveOnAirToggle?.defaultChecked);
if (liveOnAirToggle) liveOnAirToggle.checked = confirmedLiveOnAir;
boot.liveOnAir = confirmedLiveOnAir;

function confirmLiveOnAir(value) {
  if (typeof value !== "boolean") return;
  confirmedLiveOnAir = value;
  if (liveOnAirToggle) liveOnAirToggle.checked = value;
}
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
  if (boot.sessionExpired && !boot.loginDesktopDismissed) {
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
  if (filterSavePending) return;
  if (searchEl) sessionStorage.setItem(SEARCH_KEY, searchEl.value);
  sessionStorage.setItem(SCROLL_KEY, String(window.scrollY));
  window.location.reload();
}

async function runAction(message, request, options = {}) {
  errorEl.textContent = "";
  actionInFlight = true;
  showToast(message);
  try {
    const response = await request();
    if (!response.ok) {
      if (options.reloadOnError) {
        reloadDashboard();
        return;
      }
      if (errorEl) errorEl.textContent = await readError(response);
      setUserBusy(false);
      hideToast();
      return;
    }
    showToast("Updated. Reloading…");
    reloadDashboard();
  } catch (exc) {
    if (options.reloadOnError) {
      reloadDashboard();
      return;
    }
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
  runAction("Refreshing the guide…", () => fetch("/api/refresh", { method: "POST" }), {
    reloadOnError: true,
  });
});

document.getElementById("logout-btn")?.addEventListener("click", () => {
  runAction("Signing out…", () => fetch("/api/auth/logout", { method: "POST" }));
});

function chromePageUrl(status) {
  try {
    return new URL(status.url || "");
  } catch {
    return null;
  }
}

function isLiveYoutubeTvApp(status) {
  if (!status?.signed_in || status.on_login) return false;
  if (status.on_app) return true;
  const parsed = chromePageUrl(status);
  if (!parsed) return false;
  const host = parsed.hostname.toLowerCase();
  if (host !== "tv.youtube.com" && !host.endsWith(".tv.youtube.com")) return false;
  const path = parsed.pathname.replace(/\/+$/, "") || "/";
  return path === "/" || path.startsWith("/watch");
}

function dismissLoginDesktop() {
  const signedAuth = document.getElementById("signed-auth");
  const frame = document.getElementById("desktop-frame");
  if (frame) frame.removeAttribute("src");
  if (idleAuth) idleAuth.hidden = true;
  const authCard = document.getElementById("auth-card");
  if (authCard) authCard.hidden = true;
  if (signedAuth) signedAuth.hidden = false;
  if (errorEl) errorEl.textContent = "";
  boot.signedIn = true;
  boot.sessionExpired = false;
  boot.loginDesktopDismissed = true;
  paintSessionStatus(false);
}

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
    } else if (isLiveYoutubeTvApp(status)) {
      if (note) note.textContent = "Signed in. Saving the session…";
      showToast("Signed in. Saving the session…");
      const capture = await fetch("/api/auth/chrome/capture", { method: "POST" });
      if (capture.ok) {
        dismissLoginDesktop();
        hideToast();
        return;
      }
      hideToast();
      errorEl.textContent = await readError(capture);
    } else if (status.on_welcome) {
      if (note) note.textContent = "YouTube TV signed this tab out. Sign in again on tv.youtube.com…";
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
        dismissLoginDesktop();
        hideToast();
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

function applyFilterState(body) {
  if (liveOnAirToggle && typeof body.xmltv_live_on_air === "boolean") liveOnAirToggle.checked = body.xmltv_live_on_air;
  const languageToggle = document.getElementById("hide-spanish");
  if (languageToggle && typeof body.hide_spanish === "boolean") languageToggle.checked = body.hide_spanish;
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
      (channel && channels.has(channel)) ||
      (document.getElementById("hide-spanish")?.checked && row.dataset.language === "es");
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

async function postFilter(body, message, saveError = errorEl) {
  if (filterSavePending) return;
  filterSavePending = true;
  filterGeneration += 1;
  const previous = snapshotChipState();
  applyFilterState(body);
  applyEventVisibility();
  saveError.textContent = "";
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
      if (languageToggle) languageToggle.checked = confirmedHideSpanish;
      if (liveOnAirToggle) liveOnAirToggle.checked = confirmedLiveOnAir;
      applyEventVisibility();
      saveError.textContent = await readError(response);
      hideToast();
      return;
    }
    const data = await response.json();
    applyFilterState(data);
    confirmLanguage(data.hide_spanish);
    confirmLiveOnAir(data.xmltv_live_on_air);
    applyEventVisibility();
    boot.filterRevision = data.filter_revision ?? boot.filterRevision;
    const countEl = document.getElementById("event-count");
    if (countEl && data.events != null) countEl.textContent = data.events;
    boot.events = String(data.events ?? boot.events);
    boot.allEvents = String(data.all_events ?? boot.allEvents);
    if (Number.isInteger(data.lane_count)) {
      const lanesUsed = document.getElementById("lanes-used");
      const droppedEvents = document.getElementById("dropped-events");
      const droppedCount = document.getElementById("dropped-count");
      if (lanesUsed) lanesUsed.textContent = `${data.lanes_used} / ${data.lane_count}`;
      if (droppedEvents) droppedEvents.hidden = data.dropped === 0;
      if (droppedCount) droppedCount.textContent = data.dropped;
      if (laneCountInput && ("lane_count" in body || laneCountInput.valueAsNumber === boot.laneCount)) {
        laneCountInput.value = String(data.lane_count);
      }
      boot.laneCount = data.lane_count;
    }
    hideToast();
    return data;
  } catch (exc) {
    restoreChipState(previous);
    if (languageToggle) languageToggle.checked = confirmedHideSpanish;
    if (liveOnAirToggle) liveOnAirToggle.checked = confirmedLiveOnAir;
    applyEventVisibility();
    saveError.textContent = exc.message || "Request failed";
    hideToast();
  } finally {
    filterSavePending = false;
    actionInFlight = false;
  }
}

document.getElementById("lane-count-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (actionInFlight || reloading) return;
  const saveButton = document.getElementById("save-lane-count");
  const status = document.getElementById("lane-count-status");
  status.hidden = true;
  const previousCount = boot.laneCount;
  saveButton.disabled = true;
  laneCountInput.disabled = true;
  try {
    const saved = await postFilter(
      { lane_count: laneCountInput.valueAsNumber },
      "Saving lane count…",
      document.getElementById("lane-count-error"),
    );
    if (saved) {
      status.textContent = saved.lane_count === previousCount
        ? "Lane count saved."
        : `Lane count saved. ${saved.lane_count > previousCount ? "Import only the new lanes into APITuner." : "Remove the extra lanes from APITuner."} Then refresh the Channels DVR source and guide.`;
      status.hidden = false;
    }
  } finally {
    saveButton.disabled = false;
    laneCountInput.disabled = false;
  }
});

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
  if (typeof status.hide_spanish === "boolean" && status.hide_spanish !== boot.hideSpanish) return true;
  if (status.signed_in !== boot.signedIn) return true;
  if (Boolean(status.session_expired) !== boot.sessionExpired) {
    if (!(boot.loginDesktopDismissed && status.session_expired)) return true;
  }
  if (lastRefresh !== boot.lastRefresh) return true;
  if (boot.lastError !== null && lastError !== boot.lastError) return true;
  if (!status.refreshing && String(status.all_events ?? "") !== String(boot.allEvents)) return true;
  return false;
}

function guideFiltersChanged(status) {
  return (typeof status.filter_revision === "string" && status.filter_revision !== boot.filterRevision)
    || (typeof status.xmltv_live_on_air === "boolean" && status.xmltv_live_on_air !== boot.liveOnAir)
    || (Number.isInteger(status.lane_count) && status.lane_count !== boot.laneCount);
}

function snapshotStatus(status) {
  confirmLanguage(status.hide_spanish);
  confirmLiveOnAir(status.xmltv_live_on_air);
  applyEventVisibility();
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
  const generation = filterGeneration;
  let status;
  try {
    const response = await fetch("/api/status");
    if (!response.ok) return;
    status = await response.json();
  } catch {
    return;
  }
  if (actionInFlight || filterSavePending || reloading || generation !== filterGeneration) return;
  setBackgroundUpdating(Boolean(status.refreshing));
  if (laneCountInput && document.activeElement === laneCountInput
      && laneCountInput.valueAsNumber !== boot.laneCount) return;
  const filtersChanged = guideFiltersChanged(status);
  if (!boot.primed && !filtersChanged) {
    snapshotStatus(status);
    return;
  }
  if (status.refreshing) return;
  if ((filtersChanged || statusChanged(status)) && !(cookieDraftOpen() && !status.signed_in)) {
    if (filterSavePending || generation !== filterGeneration) return;
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


document.getElementById("hide-spanish")?.addEventListener("change", (event) => {
  if (actionInFlight) {
    event.target.checked = confirmedHideSpanish;
    return;
  }
  postFilter({ hide_spanish: event.target.checked }, "Updating broadcast language…");
});


liveOnAirToggle?.addEventListener("change", (event) => {
  if (actionInFlight) {
    event.target.checked = confirmedLiveOnAir;
    return;
  }
  postFilter({ xmltv_live_on_air: event.target.checked }, "Updating Live labeling…");
});
