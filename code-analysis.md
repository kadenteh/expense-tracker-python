# Data Export — Code Analysis of v1, v2 and v3

| | |
|---|---|
| **Date** | 2026-09-23 |
| **Base commit** | `8b9bdb3` (original app, shared by all three branches) |
| **Branches** | `feature-data-export-v1` @ `ab0bf87` · `feature-data-export-v2` @ `9f8eb92` · `feature-data-export-v3` @ `8b8290c` (= `main`) |
| **Method** | Diffed each branch against the base, read every changed file, ran each branch's test suite, computed per-function cyclomatic complexity (AST branch count), and ran targeted probes: edge-case inputs, a 20,000-expense dataset, CSRF-style requests, concurrent jobs. All numbers below come from those runs, not estimates. |
| **Disclosure** | All three versions were written by the same author (Claude) earlier in this session. The weaknesses below were found by probing each branch, not taken from memory, and several are defects in code I wrote. |

---

## 1. At a glance

| | **v1 — Simple** | **v2 — Advanced local** | **v3 — Cloud-style** |
|---|---|---|---|
| Files changed / added | 4 (0 new source files) | 16 (10 new) | 30 (25 new) |
| Lines added (incl. tests, CSS) | 27 | 2,287 | 5,267 |
| Python added (non-test) | ~4 | ~800 | ~1,690 |
| JavaScript | 0 | 401 lines (`export.js`) | 547 lines (`export-center.js`) |
| CSS | 0 | 618 lines | 1,925 lines |
| New runtime dependencies | none | none | `segno` (QR codes) |
| New DB tables | none | none | 4 (`export_jobs`, `share_links`, `integrations`, `schedules`) |
| New HTTP routes | 0 (reuses `/expenses/export.csv`) | 2 | 21 |
| Output formats | CSV | CSV, JSON, PDF | CSV ×3 templates, JSON backup |
| Tests (total / added) | 26 / +1 | 64 / +39 | 58 / +33 |
| Highest function complexity | 2 (`expenses_to_csv`) | 13 (`parse_export_options`) | 12 (`run_job`) |
| Mean complexity of new code | 2.0 | ~2.7 | ~2.9 |
| Real vs simulated | all real | all real | real core; email and 4 services simulated |

---

## 2. Version 1 — Simple CSV export

### 2.1 Files created / modified

| File | Change |
|---|---|
| `expense_tracker/templates/dashboard.html` | Adds an **Export Data** `<a download>` next to "+ Add Expense" |
| `expense_tracker/csv_export.py` | Column order changed to `Date, Category, Amount, Description` |
| `tests/test_csv_export.py` | Updated for the new column order |
| `tests/test_routes.py` | +1 test: button present, header correct, all rows exported |

### 2.2 Architecture overview

There is no new architecture. v1 reuses what the base app already had:

```
Dashboard <a href="/expenses/export.csv" download>
        │  (plain GET, no params → Filters() defaults → all expenses, newest first)
        ▼
routes/expenses.py: export_csv()  ──► models.list_expenses(Filters) ──► csv_export.expenses_to_csv()
        │
        ▼
Response(text/csv, Content-Disposition: attachment; filename=expenses.csv)
```

### 2.3 Key components

| Component | Responsibility |
|---|---|
| `export_csv` route (pre-existing) | Parses optional filter params, queries, returns the CSV |
| `expenses_to_csv` (pre-existing, modified) | Serialises rows with `csv.writer`; handles quoting |
| Dashboard link | The whole UI |

### 2.4 Libraries and dependencies
Standard library only: `csv`, `io`. No JavaScript.

### 2.5 Implementation patterns
- **Reuse over new code.** The existing filtered-export endpoint called with no parameters *is* "export everything".
- **Browser-native download.** `Content-Disposition: attachment` plus the `download` attribute. No JS, no blobs.
- **One shared serializer.** v1 and the Expenses page export use the same function.

### 2.6 Complexity
Trivial: one function, complexity 2, 7 lines. Nothing to maintain.

### 2.7 Error handling
- There's nothing to validate: the endpoint takes no user input from this entry point.
- An empty database returns a valid header-only CSV (probe: `Date,Category,Amount,Description\r\n`).
- The button is only rendered when there are expenses, because the empty dashboard shows a different header.
- A server failure surfaces as the browser's own "download failed". There's no in-app feedback.

### 2.8 Security considerations

| Issue | Status | Evidence |
|---|---|---|
| **CSV / formula injection** | ❌ **Vulnerable.** A description like `=HYPERLINK("http://x")` is written verbatim, and Excel/Sheets will evaluate it. | Probe: formula present, unescaped |
| Encoding for Excel | ⚠️ No UTF-8 BOM, so Excel on Windows shows `Café` as `CafÃ©` | Probe: `BOM present: False` |
| Injection / traversal | ✅ No user-controlled filename or SQL | Fixed filename, parameterised queries |
| Side effects of GET | ✅ Read-only | — |

### 2.9 Performance
The whole CSV is built in memory, then sent. **20,000 rows → 671 KB in ~100 ms.** Memory scales linearly with the data. That's fine for a personal tracker, but at 10⁶ rows it would need a streaming response.

### 2.10 Extensibility and maintainability
- ✅ Nothing to maintain, and it's easy to understand.
- ⚠️ **Coupling side effect:** reordering the columns in the shared serializer also changed the existing Expenses-page export (documented in the commit).
- ❌ There's no seam for more formats or options. Any growth would mean redesigning it, which is what v2 does.

### 2.11 Technical deep dive

| Question | Answer |
|---|---|
| How does export work? | A synchronous GET; the server queries all rows and returns them as the response body |
| File generation | `csv.writer` into `io.StringIO`, CRLF line endings, returned as `str` |
| User interaction | One click. The browser handles the download natively and there's no in-app feedback |
| State management | None, client or server |
| Edge cases | Empty data → header-only file. Commas and quotes in descriptions → quoted correctly by `csv`. Formulas and non-ASCII → **not** handled (see 2.8) |

---

## 3. Version 2 — Advanced local export

### 3.1 Files created / modified

**New**
| File | Lines | Purpose |
|---|---|---|
| `exports/options.py` | 104 | `ExportOptions` dataclass, `parse_export_options`, `sanitize_filename` |
| `exports/report.py` | 87 | `ExportReport`: selected rows plus derived totals, per-category totals, period label |
| `exports/formats.py` | 112 | `ExportFormat` registry, CSV and JSON renderers |
| `exports/pdf_canvas.py` | 166 | Hand-written PDF 1.4 writer: text, lines, rects, Helvetica metrics, xref |
| `exports/pdf_report.py` | 161 | Report layout: header, key figures, category bars, paginated table, footer |
| `exports/__init__.py` | 16 | Public API of the package |
| `routes/export.py` | 81 | `/export/preview` (JSON), `/export/download` (file) |
| `templates/partials/export_dialog.html` | 162 | `<dialog>` markup |
| `static/js/export.js` | 401 | Dialog behaviour |
| `tests/test_exports.py` | 306 | 39 tests |

**Modified:** `models.py` (+`find_expenses`, `count_by_category`), `categories.py` (+print colours), `__init__.py` (blueprint), `base.html` (+`scripts` block), `dashboard.html` (trigger + include), `style.css` (+618 lines).

### 3.2 Architecture overview

This is a layered design with a clean split between parsing, data, rendering and transport:

```
            ┌──────────── export.js (dialog controller) ────────────┐
            │ form state ─► buildParams() ─► debounce 200ms          │
            │   GET /export/preview ─► render summary/table/chips    │
            │   GET /export/download ─► blob ─► <a download> click    │
            └─────────────────────────────────────────────────────────┘
                                  │ query string
routes/export.py ── parse_export_options(args, EXPORT_FORMATS) ──► (ExportOptions, errors)
                        │ errors → 400 JSON {errors:{field:msg}}
                        ▼
                  build_report(options) ──► models.find_expenses(range, categories, sort)
                        ▼
                  ExportReport (count, total, by_category, period_label …)
                        ▼
            EXPORT_FORMATS[fmt].render(report) → bytes
              ├─ render_csv   (BOM + formula neutralisation)
              ├─ render_json  (export meta + summary + rows)
              └─ render_pdf ──► pdf_report layout ──► pdf_canvas.PdfDocument.to_bytes()
                        ▼
            send_file(BytesIO, as_attachment, download_name=sanitized)
```

### 3.3 Key components

| Component | Responsibility |
|---|---|
| `parse_export_options` | Single source of truth for validating format, dates, date order, categories and sort, plus filename sanitising. Returns a field → message map |
| `ExportReport` | Immutable-ish view model; derived values are cached with `cached_property` |
| `ExportFormat` registry | Strategy pattern: `key, label, extension, mimetype, render()`. Adding a format means adding one entry |
| `pdf_canvas` | Minimal PDF object model: pages, content streams, font resources, xref table with byte offsets, WinAnsi string escaping, AFM glyph widths for right-aligning and truncating |
| `pdf_report` | Pure layout: pagination loop, repeated table header, total row, "Page X of Y" (two-pass: lay out, then add footers) |
| `export.js` | Controller: form → params, debounced preview fetch, `AbortController` for stale requests, presets, category bulk toggles, submit and loading states, toast |

### 3.4 Libraries and dependencies
- **Python:** standard library only (`csv`, `json`, `io`, `re`, `dataclasses`, `functools`). The PDF is generated without ReportLab or WeasyPrint.
- **Browser APIs:** `<dialog>`/`showModal`, `fetch`, `AbortController`, `URL.createObjectURL`, `FormData`, `inert`, CSS `:has()`, `color-mix()`. All current evergreen browsers support these; **pre-2023 browsers won't**.

### 3.5 Implementation patterns
- **Strategy/registry** for formats. **Parse, don't validate:** handlers only ever see an `ExportOptions`.
- **Two endpoints with the same contract:** preview and download share a parser, so they can't disagree about what's being exported.
- **Server-authoritative preview:** the client never filters data. It only renders server results.
- **Progressive loading UI:** skeleton rows on first load, then a dimmed table plus a progress bar on refresh.
- **Accessibility:** `aria-busy`, `aria-live` on the summary, `role=radiogroup`, focus-visible outlines, and `prefers-reduced-motion`.

### 3.6 Complexity
- The hot spot is `parse_export_options` (complexity 13, 44 lines). It's linear validation code, so the number is high but it reads easily.
- `pdf_canvas.to_bytes` (7) is the most error-prone code, because the byte offsets must be exact. Tests re-parse the xref table and check every offset, and during development pypdf opened the output in strict mode with no warnings.
- Mean complexity is about 2.7. The complexity is contained: each module has one job.

### 3.7 Error handling
- **Server:** every input is validated. The probe `from=2026-02-30&categories=Rent` returned `{"from": "Enter a valid date.", "categories": "Unknown category: Rent."}`. Errors come back as a 400 with per-field messages, which the UI shows under each field.
- **Client:**
  - network failure → "Couldn't load the preview…"
  - failed download → inline error, and the dialog stays open
  - stale preview responses are discarded via an `AbortController` identity check
  - Export is disabled on validation errors or a zero-record result
- **Three client bugs were found by browser testing and fixed before commit:**
  1. A click was swallowed when the filename field lost focus.
  2. `FormData` came back empty because the fieldset was disabled before its values were read.
  3. A preview refresh could fire mid-export while the controls were disabled.

  Each fix has a comment explaining the constraint.

### 3.8 Security considerations

| Issue | Status | Evidence |
|---|---|---|
| CSV formula injection | ✅ Cells starting with `= + - @ \t \r` are prefixed with `'` | Probe: `'=HYPERLINK` |
| Excel encoding | ✅ UTF-8 BOM | Probe: BOM present |
| Filename injection / traversal | ✅ Allow-list regex, dot/dash trimming, 80-char cap | `../../etc/passwd` → `etc-passwd.csv` |
| Header injection | ✅ `send_file(download_name=…)` quotes and encodes | — |
| XSS in preview | ✅ Rows are built with `textContent`/`createElement` and never `innerHTML` | `export.js` `renderRows` |
| Caching of personal data | ✅ `Cache-Control: no-store` on downloads | Test asserts it |
| State-changing GETs | ✅ None: both endpoints are read-only | — |
| PDF string injection | ✅ `( ) \` escaped; non-printables emitted as octal escapes | Test with `Lunch (team)` |

### 3.9 Performance (20,000 expenses)

| Operation | Size | Time |
|---|---|---|
| Preview (runs on every option change, debounced) | 8 KB | ~80 ms |
| CSV download | 664 KB | ~99 ms |
| JSON download | 2.7 MB | ~128 ms |
| **PDF download** | **7.0 MB, 589 pages** | **~994 ms** |

- The PDF content streams **aren't compressed**. That made debugging and testing easier, but Flate would shrink them roughly 5–8×.
- Downloads go through `fetch → blob`, so the whole file is held in browser memory. That's fine at these sizes.
- The preview also runs `count_by_category`, a second query, to label the chips.

### 3.10 Extensibility and maintainability
- ✅ A new format is one `ExportFormat` entry plus a render function. A new filter touches the parser, the model query and one form control.
- ✅ Well tested (39 tests), including structural PDF validation and pagination.
- ⚠️ **Custom PDF writer limits:**
  - **Non-Latin text is lost.** Probe: `東京の寿司` → `?????`, `Ωμέγα` → `?????`. The writer only has the 14 standard fonts with WinAnsi encoding and doesn't embed TrueType fonts.
  - The page is fixed at US Letter (no A4).
  - The glyph-width tables are hand-maintained.

  If the app needs multilingual PDFs, swapping `pdf_canvas` for ReportLab or fpdf2 is contained: only `pdf_report.py` depends on it.
- ⚠️ A module-level `assert` checks that the sort labels match the sort options. Running with `python -O` skips it silently.

### 3.11 Technical deep dive

| Question | Answer |
|---|---|
| How does export work? | Synchronous and request-scoped: parse → query → build report → render bytes → `send_file` |
| File generation | CSV via `csv.writer` + BOM; JSON via `json.dumps(indent=2, ensure_ascii=False)`; PDF via a custom object writer (5 fixed objects + 2 per page, byte-accurate xref) |
| User interaction | Modal `<dialog>`. Controls change → 200 ms debounced preview → summary, table (first 50 rows) and chip counts update. Submit → `fetch` → blob → object URL → synthetic `<a download>` click → dialog closes → toast. There's a minimum 500 ms spinner so it doesn't flicker |
| State management | One `state` object in a closure (`previewController`, `lastPreview`, `hasErrors`, `exporting`). The DOM is the source of truth for option values (`FormData`); the server is the source of truth for counts. Options persist between openings within a page load |
| Edge cases | Empty result → valid empty CSV/JSON and a PDF with a "No expenses match" message, and Export is disabled. Reversed dates or no categories → field errors. Preview capped at 50 rows with "Showing first 50 of N". Long descriptions truncated with an ellipsis in the PDF using real glyph widths. Rapid option changes → debounce + abort |

---

## 4. Version 3 — Cloud-style Export Center

### 4.1 Files created / modified

**New: backend (`expense_tracker/cloud/`, 1,209 lines)**
| File | Lines | Purpose |
|---|---|---|
| `templates.py` | 349 | 4 report templates (Tax Report, Monthly Summary, Category Analysis, Full Backup) → `ExportArtifact` |
| `store.py` | 408 | SQLite data access for jobs, share links, integrations, schedules; change fingerprint |
| `jobs.py` | 335 | Validation, background job runner, destination stages and delivery, schedules, live sync, `tick()` |
| `services.py` | 106 | Static catalog of destinations and (simulated) integrations |
| `qr.py` | 10 | `segno` → inline SVG |

**New: web layer**
| File | Lines | Purpose |
|---|---|---|
| `routes/exports.py` | 367 | Page, panel polling, 15 JSON API endpoints, before/after-request hooks |
| `routes/share.py` | 75 | Public `/s/<token>` page and download, with redaction |
| `templates/exports/*.html` (10 files) | 617 | Page, 5 live panels, drawer, dialogs, icon macros, delivery previews |
| `templates/share/*.html` (2 files) | 80 | Public share page, "no longer available" page |
| `static/js/export-center.js` | 547 | Polling, drawer, OAuth mock, share dialog, delegated actions |
| `tests/test_export_center.py` | 330 | 33 tests |

**Modified:**
- `db.py`: +4 tables
- `__init__.py`: blueprints, filters, orphan-job cleanup at startup
- `formatting.py`: `format_relative`, `format_local`
- `base.html`: nav item with a live dot
- `dashboard.html`: entry button
- `style.css`: +1,925 lines
- `requirements.txt`: `segno`
- `README.md`

### 4.2 Architecture overview

This is an event-ish, job-based design with server-rendered panels that are refreshed by polling:

```
Browser (export-center.js)
  ├─ poll GET /exports/panels  (900 ms while jobs run, 10 s idle, paused when tab hidden)
  │     ◄─ {panels:{status,activity,services,schedules,shares: HTML}, jobs:[{id,status}], connected, active}
  │     → swap changed panels' innerHTML; diff job statuses → toasts / auto-open share dialog
  └─ POST/DELETE /exports/api/*  (start job, rerun, share, revoke, connect, sync, schedule …)

Flask request
  ├─ before_app_request: jobs.tick()  (throttled to 20 s: run due schedules + live sync)
  ├─ after_app_request:  live sync after a successful expense add/edit/delete
  └─ start_job → validate → INSERT export_jobs(status=queued) → threading.Thread(run_job)

Worker thread: run_job(app, id)   (own app context and SQLite connection)
  queued → running: "Collecting" → template.build(period) → store bytes + SHA-256 + preview JSON
        → destination stages (simulated latency, re-checks the integration is still connected)
        → _deliver(): share → INSERT share_links | email/sheets/dropbox/onedrive/slack → result JSON only
        → done (mark_synced(fingerprint, time)) | failed(error)

Public: GET /s/<token> → active? → record view → render (redacted rows if requested) | 410
```

### 4.3 Key components

| Component | Responsibility |
|---|---|
| `ExportTemplate` / `ExportArtifact` | Template = metadata + period catalog + builder. Artifact = file bytes + a display table + highlights + which column is sensitive |
| `store` | Thin data-access layer; `Job`, `ShareLink` and `Schedule` dataclasses parsed from rows. Keeps SQL out of routes |
| `jobs.run_job` | The pipeline, with progress checkpoints written to the database. The database *is* the message bus between the worker and the UI |
| `jobs.tick` | Request-driven scheduler: there's no cron or daemon; due work runs when someone uses the app |
| `jobs.sync_state` / `store.expenses_fingerprint` | SHA-256 over all expense rows → "Up to date", "N new since last sync" or "Edited since last sync" |
| `routes/exports._panel_context` | Builds the view model for all five panels. The same templates are used for the first render and for polling |
| `routes/share` | Public, unauthenticated read-only view. Redaction is applied on the server |
| `export-center.js` | Poll loop, panel diffing, completion detection, drawer and dialog controllers, event delegation via `data-action` |

### 4.4 Libraries and dependencies
- **New:** `segno==1.6.6` (pure Python, MIT-licensed, no transitive dependencies) for QR codes.
- **Standard library:** `threading`, `secrets` (tokens), `hashlib` (SHA-256), `calendar`, `json`.
- **Browser:** same modern-API baseline as v2, plus `navigator.clipboard` and `navigator.share` (feature-detected, with an `execCommand` fallback).

### 4.5 Implementation patterns
- **Asynchronous job pattern** with persisted state and polling (no WebSockets or SSE).
- **Server-rendered fragments over JSON:** panels are Jinja partials swapped with `innerHTML`. That means one rendering path and no client templating, but coarse updates.
- **Template-method style** for destinations: a shared pipeline with per-destination stage lists and `_deliver()`.
- **Honest simulation boundary:** simulated destinations share the real pipeline and only differ in `_deliver()`. The UI labels them in four places (badge, drawer note, consent screen, preview banner).
- **Catch-up-once scheduling:** `next_run_at` is advanced *before* the run starts, so a failing run is never retried in a loop and missed runs aren't replayed.

### 4.6 Complexity
- This is the largest surface: **21 routes, 4 tables, 3 background mechanisms** (job threads, request-driven tick, after-edit live sync) and a polling client.
- Hot spots:
  - `run_job` (complexity 12, 49 lines)
  - `_build_category_analysis` (11)
  - `format_relative` (10)
- Most functions are small (`store` averages 1.7).
- The complexity sits in **interactions**: threads × SQLite × polling × multiple processes, rather than in any single function. That's where the defects below were found.

### 4.7 Error handling
- **Validation:** the same field → message 400 contract as v2 (template, period, destination, integration connected, email addresses, expiry, frequency). Shares can't be scheduled.
- **Job failures:** caught in `run_job` and saved as `status=failed` plus the error text, then shown in Activity and as a toast. A service disconnected mid-job fails at the next stage with "Dropbox was disconnected".
- **Schedules that can't start** (service disconnected) create a visible failed job instead of failing silently.
- **Restart safety:** `fail_orphaned_jobs()` at startup marks jobs that were queued or running as "Interrupted by a server restart" (but see 4.8, D5).
- **Client:** every action goes through `runAction`, which shows the first server error as a toast. Poll failures are swallowed and retried next tick. `confirm()` guards destructive actions.

### 4.8 Security considerations and defects found

| # | Issue | Severity | Evidence |
|---|---|---|---|
| D1 | **No CSRF protection on 11 state-changing POST endpoints.** Endpoints without a body accept a plain form-encoded POST, so another site could make your browser revoke links, connect or disconnect services, or trigger exports. The base app's own forms have no CSRF protection either, so this is app-wide, but v3 adds much more surface. | High (if the app is ever reachable beyond localhost) | Probe: form-encoded `POST /api/shares/<t>/revoke` → 200, link → 410 |
| D2 | **Report CSVs don't neutralise formulas**: a regression from v2. Tax Report and Monthly/Category CSVs write descriptions verbatim. | Medium | Probe: Tax Report contains unescaped `=HYPERLINK` |
| D3 | **Redacted share downloads are silently truncated to 500 rows.** They're built from the capped preview table, not the source data. A 20,001-row export downloads as 500 rows with no warning. They also use display-formatted values (`"Sep 1, 2026"`, `"$5.00"`), not raw data. | Medium (data loss) | Probe: 500 data rows |
| D4 | **Share view counts include every GET**, so link unfurlers (Slack, iMessage) and prefetchers inflate them. | Low | Probe: 2 GETs → 2 views |
| D5 | **Multi-process race on startup.** `fail_orphaned_jobs()` runs in every new process and marks *another* process's running jobs as failed. Those threads then finish and overwrite `status` to `done` but leave `error` set, giving inconsistent records. Also triggered by the Flask debug reloader. | Medium (only with >1 process) | Probe: 15/15 `done`, yet `error = "Interrupted by a server restart"` present |
| D6 | **Duplicate schedule runs across processes:** `tick()` throttling is per process, and "read due → advance" isn't atomic. | Low (single-process today) | Code review: `run_due_schedules` |
| — | Share tokens | ✅ `secrets.token_urlsafe(9)` gives 72 bits, which isn't guessable. Links expire, are revocable, and are served with `noindex` | — |
| — | Redaction | ✅ Enforced on the server for both the page and the download. The original file isn't served for redacted links | Probe: no descriptions leaked (40 of 40 cells hidden in browser test) |
| — | XSS | ✅ Panels are autoescaped Jinja. The only `innerHTML` besides panels is segno's SVG, generated from our own URL | — |
| — | Simulated OAuth | ✅ No credentials are collected, and "Simulated" labelling is explicit | — |
| — | Share URL | ⚠️ Built from the request's `Host` header (`url_for(_external=True)`). Behind a proxy, set `SERVER_NAME` or `ProxyFix` | — |

### 4.9 Performance and resource use (20,000 expenses)

| Concern | Measurement / behaviour |
|---|---|
| **Panel poll cost** | **~166 ms per `/exports/panels` call.** Each poll hashes every expense for the fingerprint and renders 5 templates, every 0.9 s while jobs run and every 10 s idle. It's O(n) per poll |
| **Storage growth** | **+17.7 MB for 5 backups.** Every job's file is kept as a BLOB forever, and live sync adds one per edit. There's **no retention policy** |
| Threads | One unbounded daemon thread per job (probe: 9 alive right after 15 enqueues). There's no queue, concurrency limit or backpressure |
| SQLite contention | 15 concurrent jobs all completed (no "database is locked"), but every progress checkpoint is a write and commit. Heavier concurrency would need WAL mode and a busy timeout |
| Per-request overhead | A context processor counts active jobs on every page render. `before_app_request` checks the tick on every GET (throttled) |

### 4.10 Extensibility and maintainability
- ✅ New templates and destinations are clear extension points (`TEMPLATES` dict; `DESTINATIONS` + stages + `_deliver`). Replacing a simulated destination with a real API call is a local change in `_deliver()` (plus real OAuth storage).
- ✅ The data layer is isolated (`store.py`), and the tests cover lifecycle, validation, sharing, expiry and revocation, schedules including catch-up and clamping, and live sync.
- ⚠️ **The operational model is the weak point.** In-process threads and a request-driven scheduler work for a single-user desktop app, but break down with multiple workers (D5, D6), with no traffic (schedules don't run), or at scale (polling cost). A production version would want:
  - a real job queue (RQ, Celery or Dramatiq)
  - a scheduler (cron or APScheduler)
  - Server-Sent Events instead of polling
  - blob storage with retention
- ⚠️ `style.css` is now about 2,950 lines in one file, with v3 accounting for 65% of it. It should be split per feature.
- ⚠️ **It doesn't reuse v2 at all.** v2's validated option parser, formula-safe CSV writer and PDF renderer exist on a different branch, so v3 duplicates or misses them (D2).

### 4.11 Technical deep dive

| Question | Answer |
|---|---|
| How does export work? | **Asynchronously.** `POST /exports/api/jobs` validates, inserts a `queued` row, starts a thread and returns `201 {id}` immediately. The thread writes progress checkpoints to SQLite. The browser learns about progress by polling |
| File generation | Each template builds an `ExportArtifact`: CSV via `csv.writer` + BOM (multi-section "report" CSVs for Tax and Monthly), JSON for the backup. The bytes, SHA-256, size and a ≤500-row preview are saved on the job row |
| User interaction | Template cards / "New export" → right-hand **drawer** (template → when/period → destination → destination options). Picking an unconnected service opens the **consent dialog** first. Submit → the drawer closes → the job appears in Activity with a live progress bar → a toast on completion. Share jobs auto-open the **share dialog** (link, QR, copy, native share, revoke) |
| State management | **The server is the source of truth**: job, share, schedule and integration state lives in SQLite. The client keeps only transient state: a `jobStatus` map (to detect transitions), `watchShare`, a panel-HTML cache (to skip unchanged swaps), `connected` and the poll timer. The polling rate adapts to activity and pauses on hidden tabs |
| Edge cases | Service disconnected mid-run → fails cleanly. Schedule to a disconnected service → visible failed job. Missed schedules → one catch-up run. Resuming a paused schedule → no backlog burst. Month-end clamping (Jan 31 → Feb 28). Expired or revoked links → 410 page. Deleting a running job → 409. Same-second change detection (fixed during development via full-precision sync timestamps). **Not handled:** D2–D6 above |

---

## 5. Cross-version comparison

### 5.1 Capability matrix

| Capability | v1 | v2 | v3 |
|---|:-:|:-:|:-:|
| Export all data as CSV | ✅ | ✅ | ✅ (backup is JSON; reports are CSV) |
| Multiple formats | — | CSV · JSON · PDF | CSV · JSON |
| PDF | — | ✅ (Latin-only) | — |
| Arbitrary date-range / category filters | — | ✅ | — (fixed template periods) |
| Purpose-built reports | — | — | ✅ 4 templates |
| Live preview before export | — | ✅ | — (preview after, per destination) |
| Custom filename | — | ✅ | — |
| Background processing and progress | — | — (synchronous; spinner) | ✅ |
| Export history / re-download | — | — | ✅ with SHA-256 |
| Share links and QR codes | — | — | ✅ (expiry, revoke, redaction) |
| Scheduling | — | — | ✅ (request-driven) |
| Third-party integrations | — | — | Simulated |
| Formula-injection safe | ❌ | ✅ | ❌ (D2) |
| Excel-safe encoding (BOM) | ❌ | ✅ | ✅ |
| Works with JS disabled | ✅ | — | — |

### 5.2 Engineering trade-offs

| Dimension | v1 | v2 | v3 |
|---|---|---|---|
| Time to understand | Minutes | ~1 hour | Half a day |
| Moving parts | 1 | 5 modules, 2 endpoints | 5 modules, 21 endpoints, 4 tables, threads, scheduler, poller |
| Deployment constraints | None | None | Single process only (D5/D6); disk growth; `segno` dependency |
| Failure modes | Download fails | Validation errors | Plus job failures, races, stale state, storage growth |
| Best fit | Personal/local use, "just give me my data" | Power users who need a specific slice in a specific format | Collaboration and recurring hand-offs (accountant, partner, backups) |

### 5.3 Defect summary (all found by probing, not yet fixed)

| Version | Defect | Suggested fix |
|---|---|---|
| v1 | Formula injection; no BOM | Reuse v2's `render_csv` |
| v2 | Non-Latin text lost in PDF | Embed a TrueType font (fpdf2 or ReportLab), or document the limitation |
| v2 | PDF uncompressed (7 MB / 20k rows) | Flate-compress content streams (`zlib`, stdlib) |
| v3 | D1: CSRF on POST APIs | Flask-WTF `CSRFProtect`, or require a custom header / `Content-Type: application/json` on `/exports/api/*` |
| v3 | D2: formula injection in report CSVs | Route all CSV writing through one safe writer |
| v3 | D3: redacted downloads truncated to 500 rows | Re-render from source rows with the sensitive column masked (the template knows its column) |
| v3 | D4: views counted for bots | Count on first human interaction or dedupe by client; label as "opens" |
| v3 | D5: orphan cleanup across processes | Record the owning process ID or a heartbeat on the job; only fail jobs whose owner is dead. Make `run_job` stop if its row isn't `running` |
| v3 | D6: duplicate schedule runs | Claim atomically: `UPDATE … SET next_run_at=? WHERE id=? AND next_run_at=?` and check `rowcount` |
| v3 | Unbounded storage | Retention (keep last N per destination, or X days); keep only checksum and metadata for old jobs |
| v3 | O(n) poll cost | Maintain the fingerprint incrementally (update on write), or cache it and invalidate on expense change |

---

## 6. Recommendation: combine, don't pick

The three versions are layers of one feature, not competing designs. v2 has the strongest **export engine**, v3 has the strongest **product surface**, and v1 is the right **zero-friction entry point**.

1. **Adopt v2's `exports/` package as the single engine.** Use `parse_export_options` for validation, `ExportFormat` as the registry, and `render_csv` as the one formula-safe CSV writer, plus the PDF renderer. v3's templates become *presets* that produce an `ExportOptions` (date range + categories + format) plus a template-specific renderer registered in the same format registry. This fixes D2 by construction and gives v3 PDF output.
2. **Keep v1's one-click path** as a secondary "Download all (CSV)" action, pointed at the v2 engine so it inherits the BOM and formula safety.
3. **Layer v3's history, sharing and scheduling on top**, after fixing D1, D3 and D5 and adding a retention policy. Keep the simulated integrations clearly labelled until real OAuth exists, or cut them from a first release.
4. **Choose the operational model deliberately:**
   - If this stays a single-user local app, v3's in-process threads plus the request-driven tick are acceptable once D5 and D6 are fixed.
   - If it will be deployed with multiple workers, move jobs to a queue and schedules to a real scheduler before shipping v3's features.

**Suggested order of work:**
1. Merge v2 into `main` (low risk: self-contained, well tested).
2. Port v1's button to the v2 engine.
3. Rebase v3's `cloud/` onto the v2 engine and fix D1–D5.
4. Ship sharing and history first.
5. Add scheduling and live sync after that.

---

## 7. Outcome — combined implementation

The recommendation in section 6 was carried out on `feature-data-export-combined`:

| Step | What changed |
|---|---|
| Engine | v2's `exports/` package is the only export core. One CSV writer (`exports/csvutil.py`) adds the BOM and neutralises formulas while leaving signed numbers such as `-12.50` and `+8%` alone. It's used by every CSV, including the Expenses page export. PDF streams are Flate-compressed: a 20k-row PDF drops from 7.0 MB to 0.84 MB. |
| v1 | The one-click **Download CSV** is a plain link to `/export/download?format=csv`, so it inherits the engine's safety. |
| v3 on the engine | Templates are now presets: period → date range + format + summary table. The engine renders the file, so templates gain PDF and formula-safe CSV. The new **Summary CSV** format renders a template's table. Google Sheets only accepts table formats. |

| Defect | Fix |
|---|---|
| D1 CSRF | `/exports/api/*` writes require an `X-Requested-With: ExportCenter` header, and cross-origin `Origin` headers are refused |
| D2 formula injection in report CSVs | Fixed by construction: all CSVs go through `csvutil` |
| D3 redacted downloads truncated | Jobs keep a snapshot of the exported rows. Redacted downloads are re-rendered from it in the original format: complete, raw values, descriptions hidden |
| D4 inflated view counts | Link-preview bots are ignored, and views are counted once per browser (cookie) |
| D5 cross-process orphan cleanup | Workers write a heartbeat. Only jobs silent for 2+ minutes are failed, and workers stop instead of overwriting a job someone else has failed |
| D6 duplicate schedule runs | Due schedules are claimed with a compare-and-set `UPDATE`, so only one caller wins |
| Unbounded storage | Retention: finished jobs keep their file for 30 days / the latest 50 (configurable). Exports behind a live share link are kept. History rows remain |
| O(n) change detection per poll | SQLite triggers maintain an `expenses_version` counter, so change detection is a single-row read. `/exports/panels` at 20k rows: 166 ms → 55 ms |

**Not changed:** PDFs are still Latin-only (no embedded TrueType font). The base app's own HTML forms still have no CSRF tokens. Jobs still run on in-process threads with a request-driven scheduler, which is fine for a single-process local app. A multi-worker deployment would want a real job queue and scheduler.
