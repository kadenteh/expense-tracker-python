# Expense Tracker (Python / Flask)

A Python port of the Expense Tracker web app, built with **Flask**, server-rendered
**Jinja2** templates, vanilla CSS/JS, and a local **SQLite** database (via the
standard-library `sqlite3` module — no ORM). This is a second, independent
implementation of the same app that also exists as a Next.js/TypeScript project;
the two share no code.

## Features

- Add, edit, and delete expenses (description, amount, category, date)
- Categories: Food, Transportation, Entertainment, Shopping, Bills, Other
- Dashboard with total spend, monthly spend, transaction count, top category,
  a category breakdown donut chart, and a 6-month spending trend chart
  (both charts are plain inline SVG, computed server-side in Python — no JS
  charting library)
- Search, category filter, date-range filter, and sorting on the Expenses page
- CSV export of the currently filtered expenses
- **Export Center** (`/exports`): report templates (Tax Report, Monthly Summary,
  Category Analysis, Full Backup) run as background jobs with live progress, an
  export history with SHA-256 fingerprints, expiring share links with QR codes and
  optional description redaction, recurring schedules, and live sync that notices
  when your data changes. Email delivery and the Google Sheets, Dropbox, OneDrive
  and Slack connections are **simulated**: they show the full flow and a preview of
  what would be delivered, but nothing leaves your computer.
- Server-side form validation, flash-message toasts, inline delete confirmation
- Responsive layout (card list on mobile, table on larger screens)
- Automatic light/dark mode based on system preference
- 58 automated tests (pytest) covering stats, CSV export, validation, routes, and the Export Center

## Requirements

- Python 3.10+

## Getting started

```bash
cd expense-tracker-python

# Create and activate a virtual environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1      # PowerShell
# or: .venv\Scripts\activate.bat  # cmd.exe
# or: source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000).

The SQLite database is created automatically on first run at
`instance/expenses.db`. To reset all data, stop the app and delete that file
(or delete just its contents with a `DELETE FROM expenses;`) — it will be
recreated empty on the next request.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Testing the app manually

1. **Add an expense** from the Dashboard's empty state or the "+ Add Expense"
   button. Try submitting the form empty, with a negative amount, or with no
   date to see server-side validation messages.
2. **Edit / delete** a row from the Expenses table (desktop) or card list
   (mobile) — delete requires an inline "Confirm" click.
3. **Filter and search** on the Expenses page: search by description, filter
   by category (auto-submits), restrict to a date range, and change sort order.
4. **Export CSV** — exports whatever is currently filtered/sorted.
5. **Reload the page** — data persists because it's in the SQLite file, not
   browser storage.
6. **Resize the window** below ~640px to see the mobile card layout, and
   toggle your OS's dark mode to see the app's dark theme.

## Project structure

```
app.py                        Entry point (flask run / python app.py)
expense_tracker/
  __init__.py                  App factory, Jinja filters, blueprint registration
  db.py                        SQLite connection + schema management
  models.py                    Expense dataclass, queries, validation
  stats.py                     Totals, category breakdown, monthly trend, donut geometry
  csv_export.py                CSV generation
  categories.py                Category -> CSS color variable mapping
  formatting.py                Currency / date formatting for templates
  routes/
    dashboard.py                GET /
    expenses.py                 /expenses/*, add/edit/delete/export
  templates/                    Jinja2 templates (base, dashboard, expenses list/form)
  static/css/style.css          All styling (design tokens shared in spirit with
                                 the Next.js version's palette, for a consistent look)
  static/js/app.js              Small progressive-enhancement script: flash
                                 auto-dismiss, filter auto-submit, inline delete
                                 confirm, donut/bar chart hover interactivity
tests/                          pytest suite (stats, csv, validation, routes)
instance/expenses.db            SQLite database (created on first run, gitignored)
```

This is a classic server-rendered ("MPA") Flask app: forms POST to the server,
the server validates and redirects, and pages are rendered with Jinja2. The
handful of small JavaScript enhancements (auto-dismissing toasts, inline
delete confirmation, chart hover states, auto-submitting filters) are
progressive — the app is still fully functional with JavaScript disabled,
aside from those conveniences.
