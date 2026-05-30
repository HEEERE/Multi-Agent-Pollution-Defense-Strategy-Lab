import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    db_dir = Path(tempfile.mkdtemp())
    events_db = db_dir / "events.db"

    db_dir.mkdir(parents=True, exist_ok=True)

    import app.event_store
    import app.settings_manager

    orig_event_db = app.event_store.DB_PATH
    orig_settings_db = app.settings_manager.DB_PATH
    app.event_store.DB_PATH = events_db
    app.settings_manager.DB_PATH = events_db

    app.event_store._event_store = None
    if hasattr(app.settings_manager, "_manager"):
        app.settings_manager._manager = None

    from app.main import create_app
    fastapi_app = create_app()

    with TestClient(fastapi_app) as tc:
        yield tc

    app.event_store.DB_PATH = orig_event_db
    app.settings_manager.DB_PATH = orig_settings_db
    app.event_store._event_store = None
    if hasattr(app.settings_manager, "_manager"):
        app.settings_manager._manager = None

    try:
        shutil.rmtree(db_dir)
    except OSError:
        pass
