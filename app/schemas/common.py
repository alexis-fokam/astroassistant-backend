from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    """Modèle de réponse lu directement depuis les objets SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True)
