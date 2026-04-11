from pydantic import BaseModel, Field


class CreateExampleDto(BaseModel):
    """
    Data transfer object for creating an Example entity.
    Contains the name field provided by request.
    """

    name: str = Field(
        min_length=1, max_length=100, description="Name field for the Example entity"
    )
