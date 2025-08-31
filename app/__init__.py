from flask import Flask
from .db import init_db


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        SECRET_KEY="dev",
        SQLALCHEMY_DATABASE_URI="sqlite:///articles.db",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    # ensure models are imported so SQLAlchemy knows about them before create_all()
    from . import models  # noqa: F401

    init_db(app)

    from .views import main_bp
    app.register_blueprint(main_bp)

    return app
