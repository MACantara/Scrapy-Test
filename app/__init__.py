import os
from flask import Flask
from .db import init_db
from dotenv import load_dotenv

load_dotenv()

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    # Allow switching databases via the DATABASE_URL environment variable.
    # Example: mysql+pymysql://phuser:secret@localhost:3306/phnews
    database_url = os.environ.get("DATABASE_URL", "sqlite:///articles.db")
    app.config.from_mapping(
        SECRET_KEY="dev",
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    # ensure models are imported so SQLAlchemy knows about them before create_all()
    from . import models  # noqa: F401

    init_db(app)

    from .views import main_bp
    app.register_blueprint(main_bp)

    return app
