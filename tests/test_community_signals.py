from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from skillify.index.db import init_db
from skillify.index.events import record_event


def test_install_success_uninstall_and_feedback_signals_store_no_task_content() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    init_db(engine)
    with Session(engine) as session:
        events = [
            record_event(
                session, namespace="skillify", name="bugfix", version="1.0.0",
                event_type=kind, success=success,
                occurred_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            )
            for kind, success in (
                ("install", None), ("run", True), ("uninstall", None), ("feedback", True),
            )
        ]
        assert [event.event_type for event in events] == ["install", "run", "uninstall", "feedback"]
        assert all(not hasattr(event, "prompt") and not hasattr(event, "source_code") for event in events)
