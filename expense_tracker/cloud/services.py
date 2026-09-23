"""Catalog of export destinations and the third-party services behind some of them.

Download and share links are real. Email and the third-party services are
simulated: they run the same background pipeline and record what *would* have
been delivered, but nothing leaves this computer. The UI labels them as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Integration:
    key: str
    name: str
    monogram: str
    color: str  # tile background
    category: str
    description: str
    scopes: tuple[str, ...]
    demo_account: str
    live_sync: bool  # can mirror data automatically when it changes


@dataclass(frozen=True)
class Destination:
    key: str
    name: str
    icon: str
    blurb: str
    simulated: bool
    integration: Optional[str] = None


INTEGRATIONS: dict[str, Integration] = {
    i.key: i
    for i in (
        Integration(
            key="google-sheets",
            name="Google Sheets",
            monogram="GS",
            color="#1e8e3e",
            category="Spreadsheets",
            description="Send reports to a spreadsheet and keep a live mirror of your expenses.",
            scopes=(
                "Create spreadsheets in your Drive",
                "Edit spreadsheets that Expense Tracker created",
            ),
            demo_account="you@gmail.example",
            live_sync=True,
        ),
        Integration(
            key="dropbox",
            name="Dropbox",
            monogram="DB",
            color="#0061fe",
            category="Cloud storage",
            description="Save exports to an app folder, versioned automatically.",
            scopes=("Write files to /Apps/Expense Tracker", "Read files in that folder only"),
            demo_account="you@dropbox.example",
            live_sync=True,
        ),
        Integration(
            key="onedrive",
            name="OneDrive",
            monogram="OD",
            color="#0f6cbd",
            category="Cloud storage",
            description="Store exports in Documents › Expense Tracker.",
            scopes=("Create and update files in one folder",),
            demo_account="you@outlook.example",
            live_sync=True,
        ),
        Integration(
            key="slack",
            name="Slack",
            monogram="SL",
            color="#611f69",
            category="Messaging",
            description="Post report highlights to a channel, e.g. a monthly spend recap.",
            scopes=("Post messages to #finance",),
            demo_account="Household workspace",
            live_sync=False,
        ),
    )
}

DESTINATIONS: dict[str, Destination] = {
    d.key: d
    for d in (
        Destination("download", "Download", "download", "Save the file to this device", simulated=False),
        Destination("share", "Share link", "link", "Expiring link and QR code", simulated=False),
        Destination("email", "Email", "mail", "Send as an attachment", simulated=True),
        Destination(
            "google-sheets", "Google Sheets", "sheet", "New sheet in your Drive", True, "google-sheets"
        ),
        Destination("dropbox", "Dropbox", "cloud", "/Apps/Expense Tracker", True, "dropbox"),
        Destination("onedrive", "OneDrive", "cloud", "Documents › Expense Tracker", True, "onedrive"),
        Destination("slack", "Slack", "message", "Post highlights to #finance", True, "slack"),
    )
}

FREQUENCIES = {"daily": "Every day", "weekly": "Every week", "monthly": "Every month"}
SHARE_EXPIRY_OPTIONS = {"1": "1 day", "7": "7 days", "30": "30 days", "never": "Never"}
