from flask_sqlalchemy import SQLAlchemy
import os

db = SQLAlchemy()


def init_db(app):
    db.init_app(app)
    # Allow scripts to opt-out of automatic create_all() using an env var.
    if os.environ.get('SKIP_DB_CREATE') == '1':
        return
    with app.app_context():
        db.create_all()
