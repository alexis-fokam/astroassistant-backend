import os
import tempfile

# Le moteur de risque de fond est piloté explicitement dans les tests.
os.environ.setdefault("AV_PIPELINE_ENABLED", "false")
# Les modèles entraînés vont dans un dossier jetable, jamais dans data/models.
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
