from datetime import datetime
from .db import db


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(2000), unique=True, nullable=False)
    title = db.Column(db.String(1000))
    author = db.Column(db.String(200))
    date = db.Column(db.DateTime)
    description = db.Column(db.Text)
    content = db.Column(db.Text)
    source = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "date": self.date.isoformat() if self.date else None,
            "description": self.description,
            "content": self.content,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
        }


class ScrapeJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    spider = db.Column(db.String(200))
    status = db.Column(db.String(50), default="running")
    items_count = db.Column(db.Integer, default=0)
    notified = db.Column(db.Boolean, default=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            "id": self.id,
            "spider": self.spider,
            "status": self.status,
            "items_count": self.items_count,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
