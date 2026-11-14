from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    """Response model read straight from SQLAlchemy objects."""

    model_config = ConfigDict(from_attributes=True)
