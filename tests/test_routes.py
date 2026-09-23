def test_dashboard_shows_empty_state(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"No expenses yet" in resp.data


def test_add_expense_then_appears_in_list(client):
    resp = client.post(
        "/expenses/add",
        data={
            "description": "Groceries",
            "amount": "42.10",
            "category": "Food",
            "date": "2026-09-20",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Groceries" in resp.data
    assert "$42.10".encode() in resp.data


def test_add_expense_validation_error_rerenders_form(client):
    resp = client.post(
        "/expenses/add",
        data={"description": "", "amount": "", "category": "Food", "date": ""},
    )
    assert resp.status_code == 200
    assert b"Description is required." in resp.data


def test_edit_expense_updates_it(client):
    client.post(
        "/expenses/add",
        data={"description": "Original description", "amount": "10", "category": "Food", "date": "2026-09-20"},
    )
    resp = client.post(
        "/expenses/1/edit",
        data={"description": "Updated description", "amount": "12", "category": "Food", "date": "2026-09-20"},
        follow_redirects=True,
    )
    assert b"Updated description" in resp.data
    assert b"Original description" not in resp.data


def test_delete_expense_removes_it(client):
    client.post(
        "/expenses/add",
        data={"description": "Temp", "amount": "10", "category": "Food", "date": "2026-09-20"},
    )
    resp = client.post("/expenses/1/delete", follow_redirects=True)
    assert b"0 transactions" in resp.data
    assert b'class="expense-card__desc">Temp<' not in resp.data


def test_category_filter(client):
    client.post(
        "/expenses/add",
        data={"description": "Coffee", "amount": "5", "category": "Food", "date": "2026-09-20"},
    )
    client.post(
        "/expenses/add",
        data={"description": "Bus", "amount": "3", "category": "Transportation", "date": "2026-09-20"},
    )
    resp = client.get("/expenses/?category=Food")
    assert b"Coffee" in resp.data
    assert b"Bus" not in resp.data


def test_search_filter(client):
    client.post(
        "/expenses/add",
        data={"description": "Movie night", "amount": "20", "category": "Entertainment", "date": "2026-09-20"},
    )
    resp = client.get("/expenses/?q=movie")
    assert b"Movie night" in resp.data


def test_csv_export(client):
    client.post(
        "/expenses/add",
        data={"description": "Coffee", "amount": "5", "category": "Food", "date": "2026-09-20"},
    )
    resp = client.get("/expenses/export.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert b"Date,Category,Amount,Description" in resp.data
    assert b"Coffee" in resp.data


def test_dashboard_export_button_downloads_all_expenses(client):
    for desc, cat in [("Coffee", "Food"), ("Bus pass", "Transportation")]:
        client.post(
            "/expenses/add",
            data={"description": desc, "amount": "5", "category": cat, "date": "2026-09-20"},
        )
    page = client.get("/")
    assert b"Export Data" in page.data
    assert b'href="/expenses/export.csv" download' in page.data

    resp = client.get("/expenses/export.csv")
    assert resp.headers["Content-Disposition"] == "attachment; filename=expenses.csv"
    lines = resp.get_data(as_text=True).strip().splitlines()
    assert lines[0] == "Date,Category,Amount,Description"
    assert len(lines) == 3
