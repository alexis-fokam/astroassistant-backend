import os
import tempfile

# The background risk engine is driven explicitly in tests.
os.environ.setdefault("AV_PIPELINE_ENABLED", "false")
# Trained models go to a throwaway folder, never into data/models.
os.environ.setdefault("AV_MODELS_DIR", tempfile.mkdtemp(prefix="astro-models-"))

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import Base


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
