(function () {
  "use strict";

  const dialog = document.getElementById("export-dialog");
  if (!dialog) return;

  const PREVIEW_DEBOUNCE_MS = 200;
  const MIN_EXPORT_SPINNER_MS = 500; // keeps the loading state from flickering on fast exports
  const SKELETON_ROWS = 6;

  const form = document.getElementById("export-form");
  const controls = document.getElementById("export-controls");
  const preview = document.getElementById("export-preview");
  const rowsBody = document.getElementById("export-preview-rows");
  const emptyState = document.getElementById("export-empty");
  const status = document.getElementById("export-status");
  const submitBtn = document.getElementById("export-submit");
  const submitLabel = submitBtn.querySelector("[data-submit-label]");
  const fromInput = document.getElementById("export-from");
  const toInput = document.getElementById("export-to");
  const filenameInput = document.getElementById("export-filename");
  const extensionLabel = document.getElementById("export-extension");
  const resolvedName = document.getElementById("export-resolved-name");
  const summaryEls = {};
  dialog.querySelectorAll("[data-summary]").forEach((el) => (summaryEls[el.dataset.summary] = el));

  const state = {
    previewController: null,
    debounceTimer: null,
    lastPreview: null, // last successful preview response
    hasErrors: false,
    exporting: false,
  };

  // ---------- Helpers ----------

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function isoDate(d) {
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function selectedFormat() {
    return form.querySelector('input[name="format"]:checked');
  }

  function formatLabel() {
    return selectedFormat().value.toUpperCase();
  }

  function plural(n, word) {
    return n.toLocaleString() + " " + word + (n === 1 ? "" : "s");
  }

  function buildParams() {
    const data = new FormData(form);
    const params = new URLSearchParams();
    params.set("format", data.get("format"));
    if (data.get("from")) params.set("from", data.get("from"));
    if (data.get("to")) params.set("to", data.get("to"));
    params.set("categories", data.getAll("categories").join(","));
    params.set("sort", data.get("sort"));
    const filename = (data.get("filename") || "").trim();
    if (filename) params.set("filename", filename);
    return params;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function setStatus(message, isError) {
    status.textContent = message || "";
    status.classList.toggle("is-error", Boolean(isError));
  }

  function showToast(message, kind) {
    let stack = document.getElementById("flash-stack");
    if (!stack) {
      stack = el("div", "flash-stack");
      stack.id = "flash-stack";
      document.body.appendChild(stack);
    }
    const toast = el("div", "flash flash-" + kind, message);
    toast.setAttribute("role", "status");
    stack.appendChild(toast);
    window.setTimeout(() => {
      toast.classList.add("is-dismissed");
      window.setTimeout(() => toast.remove(), 220);
    }, 4000);
  }

  // ---------- Date presets ----------

  const PRESETS = {
    all: () => ["", ""],
    "this-month": (t) => [isoDate(new Date(t.getFullYear(), t.getMonth(), 1)), isoDate(t)],
    "last-month": (t) => [
      isoDate(new Date(t.getFullYear(), t.getMonth() - 1, 1)),
      isoDate(new Date(t.getFullYear(), t.getMonth(), 0)),
    ],
    "last-90": (t) => [isoDate(new Date(t.getFullYear(), t.getMonth(), t.getDate() - 89)), isoDate(t)],
    "this-year": (t) => [isoDate(new Date(t.getFullYear(), 0, 1)), isoDate(t)],
  };
  const presetButtons = dialog.querySelectorAll("[data-preset]");

  function syncPresetButtons() {
    const today = new Date();
    presetButtons.forEach((btn) => {
      const [from, to] = PRESETS[btn.dataset.preset](today);
      btn.setAttribute("aria-pressed", String(fromInput.value === from && toInput.value === to));
    });
  }

  presetButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const [from, to] = PRESETS[btn.dataset.preset](new Date());
      fromInput.value = from;
      toInput.value = to;
      syncPresetButtons();
      schedulePreview();
    });
  });

  // ---------- Category bulk select ----------

  dialog.querySelectorAll("[data-select-categories]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const checked = btn.dataset.selectCategories === "all";
      form.querySelectorAll('input[name="categories"]').forEach((box) => (box.checked = checked));
      schedulePreview();
    });
  });

  // ---------- Errors ----------

  function renderErrors(errors) {
    state.hasErrors = Object.keys(errors).length > 0;
    dialog.querySelectorAll("[data-error-for]").forEach((p) => {
      p.textContent = errors[p.dataset.errorFor] || "";
    });
    fromInput.classList.toggle("has-error", Boolean(errors.from));
    toInput.classList.toggle("has-error", Boolean(errors.to));
  }

  // ---------- Preview ----------

  function setPreviewBusy(busy) {
    preview.setAttribute("aria-busy", String(busy));
    updateSubmit();
  }

  function renderSkeleton() {
    rowsBody.replaceChildren();
    for (let i = 0; i < SKELETON_ROWS; i++) {
      const tr = el("tr");
      [70, 80, 160, 56].forEach((width, col) => {
        const td = el("td", col === 3 ? "right" : "");
        const bar = el("span", "skeleton");
        bar.style.width = width + "px";
        if (col === 3) bar.style.marginLeft = "auto";
        td.appendChild(bar);
        tr.appendChild(td);
      });
      rowsBody.appendChild(tr);
    }
  }

  function renderRows(rows) {
    const fragment = document.createDocumentFragment();
    rows.forEach((row) => {
      const tr = el("tr");
      tr.appendChild(el("td", "", row.date_display));

      const catCell = el("td");
      const badge = el("span", "badge");
      const dot = el("span", "dot");
      dot.style.background = "var(--cat-" + row.category.toLowerCase() + ")";
      badge.append(dot, row.category);
      catCell.appendChild(badge);
      tr.appendChild(catCell);

      const desc = el("td", "desc-cell", row.description);
      desc.title = row.description;
      tr.appendChild(desc);
      tr.appendChild(el("td", "right amount-cell", row.amount_display));
      fragment.appendChild(tr);
    });
    rowsBody.replaceChildren(fragment);
  }

  function renderPreview(data) {
    state.lastPreview = data;
    const { summary, rows, row_limit: limit } = data;

    summaryEls.count.textContent = summary.count.toLocaleString();
    summaryEls.total.textContent = summary.total_display;
    summaryEls.period.textContent = summary.period;
    summaryEls.period.title = summary.period;
    summaryEls.note.textContent =
      summary.count > limit
        ? "Showing first " + limit + " of " + summary.count.toLocaleString()
        : summary.count > 0
          ? "Showing all " + plural(summary.count, "record")
          : "";

    renderRows(rows);
    emptyState.hidden = summary.count > 0;

    Object.entries(data.category_counts).forEach(([category, n]) => {
      const badge = dialog.querySelector('[data-count-for="' + category + '"]');
      if (badge) badge.textContent = n.toLocaleString();
    });

    filenameInput.placeholder = data.default_stem;
    resolvedName.textContent = data.filename;
    setStatus(
      summary.count > 0
        ? plural(summary.count, "record") + " · " + summary.total_display + " · " + summary.categories
        : ""
    );
  }

  function renderInvalid() {
    state.lastPreview = null;
    ["count", "total", "period"].forEach((key) => (summaryEls[key].textContent = "—"));
    summaryEls.note.textContent = "";
    rowsBody.replaceChildren();
    emptyState.hidden = false;
    setStatus("Fix the highlighted options to see a preview.", true);
  }

  function schedulePreview() {
    window.clearTimeout(state.debounceTimer);
    setPreviewBusy(true);
    state.debounceTimer = window.setTimeout(loadPreview, PREVIEW_DEBOUNCE_MS);
  }

  async function loadPreview() {
    if (state.previewController) state.previewController.abort();
    const controller = new AbortController();
    state.previewController = controller;

    try {
      const response = await fetch(dialog.dataset.previewUrl + "?" + buildParams(), {
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      const body = await response.json();
      if (controller !== state.previewController) return; // a newer request superseded this one

      if (!response.ok) {
        renderErrors(body.errors || {});
        renderInvalid();
      } else {
        renderErrors({});
        renderPreview(body);
      }
    } catch (err) {
      if (err.name === "AbortError") return;
      state.lastPreview = null;
      setStatus("Couldn’t load the preview. Check your connection and try again.", true);
    } finally {
      if (controller === state.previewController) {
        state.previewController = null;
        setPreviewBusy(false);
      }
    }
  }

  // ---------- Submit button ----------

  // A preview refresh in flight deliberately doesn't disable the button: blurring
  // a field fires `change` on mousedown, and disabling there would swallow the
  // click. The download reads the current options itself, so it is never stale.
  function updateSubmit() {
    const count = state.lastPreview ? state.lastPreview.summary.count : 0;
    if (!state.exporting) {
      submitLabel.textContent = state.lastPreview
        ? "Export " + plural(count, "record") + " as " + formatLabel()
        : "Export " + formatLabel();
    }
    submitBtn.disabled = state.exporting || state.hasErrors || !state.lastPreview || count === 0;
  }

  function setExporting(exporting) {
    state.exporting = exporting;
    // `inert` rather than `disabled`: it blocks interaction but keeps the fields in
    // FormData, so a preview refresh that fires mid-export still sees the options.
    controls.inert = exporting;
    dialog.querySelectorAll("[data-export-close]").forEach((btn) => (btn.disabled = exporting));
    submitBtn.classList.toggle("is-loading", exporting);
    submitBtn.setAttribute("aria-busy", String(exporting));
    if (exporting) {
      submitLabel.textContent = "Preparing " + formatLabel() + "…";
      setStatus("Generating your file…");
    }
    updateSubmit();
  }

  // ---------- Export ----------

  function filenameFromResponse(response) {
    const header = response.headers.get("Content-Disposition") || "";
    const encoded = header.match(/filename\*=UTF-8''([^;]+)/i);
    if (encoded) return decodeURIComponent(encoded[1]);
    const plain = header.match(/filename="?([^";]+)"?/i);
    return plain ? plain[1] : null;
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = el("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function wait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submitBtn.disabled) return;

    const started = performance.now();
    // Read the options before disabling the controls: disabled fields are left out of FormData.
    const params = buildParams();
    setExporting(true);
    try {
      const response = await fetch(dialog.dataset.downloadUrl + "?" + params);
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        renderErrors(body.errors || {});
        throw new Error("Export failed with status " + response.status);
      }
      const blob = await response.blob();
      const filename = filenameFromResponse(response) || state.lastPreview.filename;
      const count = Number(response.headers.get("X-Export-Record-Count") || 0);

      await wait(Math.max(0, MIN_EXPORT_SPINNER_MS - (performance.now() - started)));
      saveBlob(blob, filename);
      setExporting(false);
      dialog.close();
      showToast("Exported " + plural(count, "record") + " to " + filename, "success");
    } catch (err) {
      setExporting(false);
      setStatus("The export didn’t complete. Please try again.", true);
    }
  });

  // ---------- Live updates ----------

  form.addEventListener("change", (event) => {
    if (event.target === filenameInput) return; // already handled on `input`
    if (event.target.name === "format") {
      extensionLabel.textContent = "." + event.target.dataset.extension;
    }
    if (event.target === fromInput || event.target === toInput) syncPresetButtons();
    schedulePreview();
  });

  filenameInput.addEventListener("input", schedulePreview);

  // ---------- Open / close ----------

  document.querySelectorAll("[data-export-open]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setStatus("");
      if (!state.lastPreview) renderSkeleton();
      dialog.showModal();
      selectedFormat().focus();
      schedulePreview();
    });
  });

  dialog.querySelectorAll("[data-export-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!state.exporting) dialog.close();
    });
  });

  // Esc closes the dialog natively; don't allow it mid-export.
  dialog.addEventListener("cancel", (event) => {
    if (state.exporting) event.preventDefault();
  });

  // Clicking the backdrop (the dialog element itself, outside the frame) closes it.
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog && !state.exporting) dialog.close();
  });
})();
