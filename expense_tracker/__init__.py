from __future__ import annotations

from pathlib import Path

from flask import Flask

from .categories import category_color
from .db import register_db
from .formatting import format_currency, format_date
from .models import CATEGORIES


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY="dev-only-secret-key-change-if-deployed",
        DATABASE=str(Path(app.instance_path) / "expenses.db"),
    )

    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    register_db(app)

    app.jinja_env.filters["currency"] = format_currency
    app.jinja_env.filters["nicedate"] = format_date

    @app.context_processor
    def inject_globals():
        return {"ALL_CATEGORIES": CATEGORIES, "category_color": category_color}

    from .routes.dashboard import bp as dashboard_bp
    from .routes.expenses import bp as expenses_bp
    from .routes.export import bp as export_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(export_bp)

    return app
