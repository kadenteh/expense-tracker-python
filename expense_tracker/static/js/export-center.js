(function () {
  "use strict";

  const dataEl = document.getElementById("xc-data");
  if (!dataEl) return;
  const DATA = JSON.parse(dataEl.textContent);
  const API = DATA.urls.api;

  const POLL_ACTIVE_MS = 900; // while exports are running
  const POLL_IDLE_MS = 10000; // keeps relative times, schedules and sync status fresh
  const CONNECT_DELAY_MS = 900; // a beat for the simulated handshake

  const state = {
    connected: new Set(DATA.connected),
    jobStatus: new Map(),
    watchShare: new Set(), // share-link jobs started here: pop the link open when they finish
    panelHtml: {},
    active: 0,
    pollTimer: null,
  };

  // ---------- Helpers ----------

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function wait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function api(method, url, body) {
    // The server refuses API writes without this header (CSRF protection).
    const headers = { [DATA.api_header[0]]: DATA.api_header[1] };
    if (body) headers["Content-Type"] = "application/json";
    const response = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let data = {};
    try {
      data = await response.json();
    } catch (_) {
      /* empty or non-JSON body */
    }
    return { ok: response.ok, status: response.status, data };
  }

  function firstError(data) {
    const errors = (data && data.errors) || {};
    return Object.values(errors)[0] || "Something went wrong. Please try again.";
  }

  function toast(message, kind) {
    let stack = document.getElementById("flash-stack");
    if (!stack) {
      stack = el("div", "flash-stack");
      stack.id = "flash-stack";
      document.body.appendChild(stack);
    }
    const item = el("div", "flash flash-" + (kind || "success"), message);
    item.setAttribute("role", "status");
    stack.appendChild(item);
    window.setTimeout(() => {
      item.classList.add("is-dismissed");
      window.setTimeout(() => item.remove(), 220);
    }, 4200);
  }

  function setBusy(button, busy, busyLabel) {
    const label = button.querySelector("[data-label]");
    if (busy) {
      button.dataset.idleLabel = label ? label.textContent : "";
      if (label && busyLabel) label.textContent = busyLabel;
    } else if (label && button.dataset.idleLabel) {
      label.textContent = button.dataset.idleLabel;
    }
    button.disabled = busy;
    button.classList.toggle("is-loading", busy);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      const input = el("textarea");
      input.value = text;
      document.body.appendChild(input);
      input.select();
      const ok = document.execCommand("copy");
      input.remove();
      return ok;
    }
  }

  // Close buttons and backdrop clicks for every dialog on the page.
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog || event.target.closest("[data-close]")) dialog.close();
    });
  });

  // ---------- Live panels ----------

  function schedulePoll() {
    window.clearTimeout(state.pollTimer);
    if (document.hidden) return; // resumes on visibilitychange
    state.pollTimer = window.setTimeout(refresh, state.active ? POLL_ACTIVE_MS : POLL_IDLE_MS);
  }

  async function refresh() {
    window.clearTimeout(state.pollTimer);
    try {
      const { ok, data } = await api("GET", DATA.urls.panels);
      if (ok) applyPanels(data);
    } catch (_) {
      /* offline for a moment; try again on the next tick */
    }
    schedulePoll();
  }

  function applyPanels(data) {
    Object.entries(data.panels).forEach(([name, html]) => {
      if (state.panelHtml[name] === html) return;
      state.panelHtml[name] = html;
      const target = document.getElementById("panel-" + name);
      // Server-rendered, auto-escaped template output.
      if (target) target.innerHTML = html;
    });

    state.connected = new Set(data.connected);
    state.active = data.active;
    syncDestinationTiles();

    data.jobs.forEach((job) => {
      const before = state.jobStatus.get(job.id);
      state.jobStatus.set(job.id, job.status);
      if (before && before !== job.status && (job.status === "done" || job.status === "failed")) {
        announce(job);
      }
    });
  }

  function announce(job) {
    if (job.status === "failed") {
      toast(job.title + " failed: " + (job.error || "unknown error"), "error");
      return;
    }
    if (state.watchShare.has(job.id)) {
      state.watchShare.delete(job.id);
      api("GET", API + "/jobs/" + job.id + "/share").then(({ ok, data }) => {
        if (ok) openShareResult(data);
      });
      return;
    }
    const verb = { download: "is ready to download", email: "was emailed", slack: "was posted" }[job.destination_key];
    toast(job.title + (verb ? " " + verb : " → " + job.destination));
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });

  // ---------- New export drawer ----------

  const drawer = document.getElementById("new-export");
  const form = document.getElementById("new-export-form");
  const periodSelect = form.elements.period;
  const formatSelect = form.elements.format;
  const repeatSelect = form.elements.repeat;
  const submitBtn = document.getElementById("new-export-submit");
  const summary = document.getElementById("new-export-summary");
  const scheduleHint = document.getElementById("schedule-hint");
  const simNote = form.querySelector("[data-sim-note]");

  const selected = (name) => form.querySelector('input[name="' + name + '"]:checked');

  function populatePeriods() {
    const template = DATA.templates[selected("template").value];
    const current = periodSelect.value;
    periodSelect.replaceChildren(
      ...template.periods.map(([value, label]) => {
        const option = el("option", "", label);
        option.value = value;
        return option;
      })
    );
    const values = template.periods.map(([value]) => value);
    periodSelect.value = values.includes(current) ? current : template.default_period;
  }

  // Formats the template offers; Google Sheets can only take a table. A new
  // template starts from its own default; other changes keep the current pick.
  function populateFormats({ reset = false } = {}) {
    const template = DATA.templates[selected("template").value];
    const needsTable = selected("destination").value === "google-sheets";
    const current = reset ? template.formats[0][0] : formatSelect.value;
    formatSelect.replaceChildren(
      ...template.formats.map(([value, label, tabular]) => {
        const option = el("option", "", label + (needsTable && !tabular ? " (not for Sheets)" : ""));
        option.value = value;
        option.disabled = needsTable && !tabular;
        return option;
      })
    );
    const usable = [...formatSelect.options].filter((o) => !o.disabled).map((o) => o.value);
    formatSelect.value = usable.includes(current) ? current : usable[0];
  }

  function syncDestinationTiles() {
    form.querySelectorAll("[data-integration]").forEach((tile) => {
      tile.classList.toggle("is-disconnected", !state.connected.has(tile.dataset.integration));
    });
  }

  function clearErrors() {
    form.querySelectorAll("[data-error-for]").forEach((p) => (p.textContent = ""));
  }

  function showErrors(errors) {
    clearErrors();
    Object.entries(errors).forEach(([field, message]) => {
      const target =
        form.querySelector('[data-error-for="' + field + '"]') || form.querySelector('[data-error-for="general"]');
      target.textContent = message;
    });
  }

  function updateDrawer() {
    const templateKey = selected("template").value;
    const template = DATA.templates[templateKey];
    const destinationKey = selected("destination").value;
    const destination = DATA.destinations[destinationKey];
    const repeat = repeatSelect.value;
    const once = repeat === "once";

    form.querySelectorAll('[data-show-when="once"]').forEach((node) => (node.hidden = !once));
    form.querySelectorAll('[data-show-when="repeat"]').forEach((node) => (node.hidden = once));
    scheduleHint.textContent =
      "Each run exports the latest period (right now: " + template.scheduled_period + ").";

    form.querySelectorAll("[data-options-for]").forEach((section) => {
      section.hidden = section.dataset.optionsFor !== destinationKey;
    });

    if (destination.simulated) {
      simNote.hidden = false;
      simNote.querySelector("span").textContent =
        destinationKey === "email"
          ? "Simulated: the email is rendered and logged in Activity, but not actually sent."
          : "Simulated: nothing is uploaded to " + destination.name + ". Activity shows a preview of what it would receive.";
    } else {
      simNote.hidden = true;
    }

    summary.replaceChildren(
      el("strong", "", template.name),
      " · " + (once ? periodSelect.selectedOptions[0]?.textContent || "" : DATA.frequencies[repeat].toLowerCase()),
      " · " + (formatSelect.selectedOptions[0]?.textContent || ""),
      " → ",
      el("strong", "", destination.name)
    );

    submitBtn.querySelector("[data-label]").textContent = !once
      ? "Create schedule"
      : destinationKey === "share"
        ? "Create link"
        : "Start export";
  }

  function openDrawer({ template, repeat } = {}) {
    if (template) form.querySelector('input[name="template"][value="' + template + '"]').checked = true;
    repeatSelect.value = repeat || "once";
    clearErrors();
    populatePeriods();
    populateFormats({ reset: true });
    syncDestinationTiles();
    updateDrawer();
    drawer.showModal();
  }

  form.addEventListener("change", (event) => {
    if (event.target.name === "template") {
      populatePeriods();
      populateFormats({ reset: true });
    }
    if (event.target.name === "destination") populateFormats();
    clearErrors();
    updateDrawer();
  });

  // Picking a service that isn't connected starts the connect flow first.
  form.querySelectorAll("[data-integration]").forEach((tile) => {
    tile.addEventListener("click", (event) => {
      const key = tile.dataset.integration;
      if (state.connected.has(key)) return;
      event.preventDefault();
      openConnect(key, () => {
        tile.querySelector("input").checked = true;
        syncDestinationTiles();
        populateFormats();
        updateDrawer();
      });
    });
  });

  function destinationOptions(destinationKey) {
    const f = form.elements;
    if (destinationKey === "email") {
      return { recipients: f.recipients.value, subject: f.subject.value, message: f.message.value };
    }
    if (destinationKey === "share") {
      return { expiry: f.expiry.value, redact: f.redact.checked };
    }
    return {};
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const template = selected("template").value;
    const destination = selected("destination").value;
    const format = formatSelect.value;
    const repeat = repeatSelect.value;
    const options = destinationOptions(destination);

    setBusy(submitBtn, true);
    try {
      const { ok, data } =
        repeat === "once"
          ? await api("POST", DATA.urls.jobs, { template, period: periodSelect.value, format, destination, options })
          : await api("POST", DATA.urls.schedules, { template, format, destination, frequency: repeat, options });
      if (!ok) {
        showErrors(data.errors || { general: firstError(data) });
        return;
      }
      drawer.close();
      if (repeat === "once") {
        state.jobStatus.set(data.id, "queued");
        if (destination === "share") state.watchShare.add(data.id);
      } else {
        toast(
          "Scheduled " + DATA.templates[template].name + " → " + DATA.destinations[destination].name +
            ", " + DATA.frequencies[repeat].toLowerCase()
        );
      }
      refresh();
    } catch (_) {
      showErrors({ general: "Couldn’t reach the server. Please try again." });
    } finally {
      setBusy(submitBtn, false);
    }
  });

  // ---------- Connect (simulated OAuth) ----------

  const connectDialog = document.getElementById("connect-dialog");
  const allowBtn = connectDialog.querySelector("[data-connect-allow]");
  let connectKey = null;
  let onConnected = null;

  function openConnect(key, callback) {
    const integration = DATA.integrations[key];
    connectKey = key;
    onConnected = callback || null;
    connectDialog.querySelectorAll("[data-connect-name]").forEach((node) => (node.textContent = integration.name));
    const tile = connectDialog.querySelector("[data-connect-tile]");
    tile.textContent = integration.monogram;
    tile.style.setProperty("--tile", integration.color);
    connectDialog.querySelector("[data-connect-account]").textContent = integration.account;
    connectDialog
      .querySelector("[data-connect-scopes]")
      .replaceChildren(...integration.scopes.map((scope) => el("li", "", scope)));
    setBusy(allowBtn, false);
    connectDialog.showModal();
    allowBtn.focus();
  }

  allowBtn.addEventListener("click", async () => {
    const key = connectKey;
    setBusy(allowBtn, true, "Connecting…");
    try {
      const [{ ok, data }] = await Promise.all([
        api("POST", API + "/integrations/" + key + "/connect"),
        wait(CONNECT_DELAY_MS),
      ]);
      if (!ok) throw new Error(firstError(data));
      state.connected.add(key);
      connectDialog.close();
      toast("Connected to " + DATA.integrations[key].name);
      if (onConnected) onConnected();
      refresh();
    } catch (err) {
      toast(err.message || "Couldn’t connect.", "error");
    } finally {
      setBusy(allowBtn, false);
    }
  });

  // ---------- Share dialog ----------

  const shareDialog = document.getElementById("share-dialog");
  const shareSetup = shareDialog.querySelector("[data-share-setup]");
  const shareResult = shareDialog.querySelector("[data-share-result]");
  const shareCopyBtn = shareDialog.querySelector("[data-share-copy]");
  const shareNativeBtn = shareDialog.querySelector("[data-share-native]");
  let shareJobId = null;
  let shareCurrent = null;

  function openShareSetup(jobId, title) {
    shareJobId = jobId;
    shareSetup.hidden = false;
    shareResult.hidden = true;
    shareSetup.querySelector('[data-error-for="share"]').textContent = "";
    shareDialog.querySelector("[data-share-subtitle]").textContent = "Create a read-only link to “" + title + "”.";
    shareDialog.querySelector("#share-title").textContent = "Share export";
    if (!shareDialog.open) shareDialog.showModal();
  }

  function openShareResult(link) {
    shareCurrent = link;
    shareSetup.hidden = true;
    shareResult.hidden = false;
    shareDialog.querySelector("#share-title").textContent = "Link ready";
    shareDialog.querySelector("[data-share-title]").textContent = link.title;
    // SVG generated server-side by segno from our own URL.
    shareDialog.querySelector("[data-share-qr]").innerHTML = link.qr_svg;
    shareDialog.querySelector("[data-share-url]").value = link.url;
    shareDialog.querySelector("[data-share-expires]").textContent = link.expires;
    shareDialog.querySelector("[data-share-expires]").title = link.expires_at || "";
    shareDialog.querySelector("[data-share-views]").textContent =
      link.views + " view" + (link.views === 1 ? "" : "s") + " so far";
    shareDialog.querySelector("[data-share-redact]").textContent = link.redact
      ? "Descriptions hidden from viewers"
      : "Full details visible";
    shareDialog.querySelector("[data-share-open]").href = link.url;
    shareNativeBtn.hidden = typeof navigator.share !== "function";
    shareCopyBtn.querySelector("span").textContent = "Copy";
    if (!shareDialog.open) shareDialog.showModal();
  }

  shareSetup.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = shareSetup.querySelector('button[type="submit"]');
    setBusy(button, true, "Creating…");
    try {
      const { ok, data } = await api("POST", API + "/jobs/" + shareJobId + "/share", {
        expiry: shareSetup.elements.expiry.value,
        redact: shareSetup.elements.redact.checked,
      });
      if (!ok) {
        shareSetup.querySelector('[data-error-for="share"]').textContent = firstError(data);
        return;
      }
      openShareResult(data);
      refresh();
    } finally {
      setBusy(button, false);
    }
  });

  shareCopyBtn.addEventListener("click", async () => {
    if (!shareCurrent) return;
    const copied = await copyText(shareCurrent.url);
    shareCopyBtn.querySelector("span").textContent = copied ? "Copied!" : "Press Ctrl+C";
    if (!copied) shareDialog.querySelector("[data-share-url]").select();
  });

  shareNativeBtn.addEventListener("click", () => {
    if (shareCurrent) navigator.share({ title: shareCurrent.title, url: shareCurrent.url }).catch(() => {});
  });

  shareDialog.querySelector("[data-share-revoke]").addEventListener("click", async () => {
    if (!shareCurrent) return;
    await api("POST", API + "/shares/" + shareCurrent.token + "/revoke");
    shareDialog.close();
    toast("Link revoked. Anyone opening it now sees “no longer available”.");
    refresh();
  });

  // ---------- Panel actions ----------

  async function runAction(request, successMessage) {
    const { ok, data } = await request;
    if (!ok) {
      toast(firstError(data), "error");
      return null;
    }
    if (successMessage) toast(successMessage);
    refresh();
    return data;
  }

  document.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-action]");
    if (!target || target.matches('input[type="checkbox"]')) return;
    const { action } = target.dataset;
    const d = target.dataset;

    switch (action) {
      case "new-export":
        openDrawer({ template: d.template, repeat: d.repeat });
        break;
      case "share-job": {
        const item = target.closest("[data-job-id]");
        openShareSetup(d.job, item.querySelector(".activity-item__title").textContent);
        break;
      }
      case "rerun": {
        const data = await runAction(api("POST", API + "/jobs/" + d.job + "/rerun"));
        if (data) state.jobStatus.set(data.id, "queued");
        break;
      }
      case "delete-job":
        if (window.confirm("Remove this export from history? Its file and share links go with it.")) {
          runAction(api("DELETE", API + "/jobs/" + d.job));
        }
        break;
      case "connect":
        openConnect(d.key);
        break;
      case "disconnect":
        if (window.confirm("Disconnect " + DATA.integrations[d.key].name + "? Live sync and schedules to it will stop.")) {
          runAction(api("POST", API + "/integrations/" + d.key + "/disconnect"), "Disconnected " + DATA.integrations[d.key].name);
        }
        break;
      case "sync-now": {
        const data = await runAction(api("POST", API + "/integrations/" + d.key + "/sync"));
        if (data) state.jobStatus.set(data.id, "queued");
        break;
      }
      case "show-share": {
        const { ok, data } = await api("GET", API + "/shares/" + d.token);
        if (ok) openShareResult(data);
        break;
      }
      case "copy-link":
        toast((await copyText(d.url)) ? "Link copied" : "Couldn’t copy the link", "success");
        break;
      case "revoke-share":
        runAction(api("POST", API + "/shares/" + d.token + "/revoke"), "Link revoked");
        break;
      case "run-schedule": {
        const data = await runAction(api("POST", API + "/schedules/" + d.id + "/run"));
        if (data) state.jobStatus.set(data.id, "queued");
        break;
      }
      case "toggle-schedule":
        runAction(api("POST", API + "/schedules/" + d.id + "/toggle"));
        break;
      case "delete-schedule":
        if (window.confirm("Delete this schedule? Past exports stay in Activity.")) {
          runAction(api("DELETE", API + "/schedules/" + d.id), "Schedule deleted");
        }
        break;
    }
  });

  document.addEventListener("change", (event) => {
    const toggle = event.target.closest('[data-action="auto-sync"]');
    if (!toggle) return;
    const name = DATA.integrations[toggle.dataset.key].name;
    runAction(
      api("POST", API + "/integrations/" + toggle.dataset.key + "/auto-sync", { enabled: toggle.checked }),
      toggle.checked ? "Live sync on: " + name + " will mirror every change" : "Live sync off for " + name
    );
  });

  // ---------- Start ----------

  syncDestinationTiles();
  refresh();
})();
