from typing import Optional
from pydantic import BaseModel, Field


class UpdateExampleDto(BaseModel):
    """
    Data transfer object for updating an Example entity.
    Contains optional fields for partial updates.
    """

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Name field for the Example entity",
    )
