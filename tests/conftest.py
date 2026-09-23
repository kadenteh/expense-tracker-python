import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from expense_tracker import create_app


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    app = create_app({"TESTING": True, "DATABASE": db_path})
    yield app
    import os

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()
