"""
Flask entry point for the GT Cotizador.

Run:
    cd cotizador/
    source .venv/bin/activate
    flask --app api.app run --debug
or:
    python -m api.app
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

load_dotenv(Path(__file__).parent.parent / ".env")

from api.routes import bp
from core.db import init_db


def create_app() -> Flask:
    _root = Path(__file__).parent.parent
    app = Flask(
        __name__,
        template_folder=str(_root / "templates"),
        static_folder=str(_root / "static"),
    )

    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-in-prod")
    app.config["APP_BASE_URL"] = os.environ.get("APP_BASE_URL", "http://localhost:5000")

    app.register_blueprint(bp)

    with app.app_context():
        init_db()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
