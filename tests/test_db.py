from datetime import datetime, timedelta, timezone

from bot.db import Database


def test_lifecycle():
    db = Database(":memory:")
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    a = db.add_post("text", "سلام", [{"type": "bold", "offset": 0, "length": 4}], None, now - timedelta(minutes=1), 1)
    b = db.add_post("photo", "cap", [], "FILE", now + timedelta(hours=1), 1)

    assert [p.id for p in db.pending()] == [a, b]
    due = db.due(now)
    assert [p.id for p in due] == [a]
    assert due[0].entities[0]["type"] == "bold"

    db.mark_sent(a)
    assert db.due(now) == []
    assert db.cancel(b) is True
    assert db.cancel(b) is False
    assert db.pending() == []
