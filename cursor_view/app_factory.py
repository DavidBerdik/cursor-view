"""Flask application factory."""

import logging
import os

from flask import Flask
from flask_cors import CORS

from cursor_view.paths import BASE_PATH
from cursor_view.routes import bp as main_bp


def create_app() -> Flask:
    """Build the Flask app with static assets, CORS, and registered HTTP routes."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    app = Flask(
        __name__,
        static_folder=os.path.join(BASE_PATH, "frontend", "build"),
    )
    CORS(app)
    app.register_blueprint(main_bp)
    return app
