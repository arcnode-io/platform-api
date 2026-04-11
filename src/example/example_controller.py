from collections.abc import Sequence
from classy_fastapi import Routable, get, post, patch, delete
from .example_service import ExampleService
from .dto.create_example_dto import CreateExampleDto
from .dto.update_example_dto import UpdateExampleDto
from .entities.example_entity import Example


class ExampleController(Routable):
    """Example controller."""

    def __init__(self, example_service: ExampleService) -> None:
        super().__init__()
        self.service = example_service

    @post("/example")
    async def create(self, create_example_dto: CreateExampleDto) -> Example:
        """Create a new example."""
        return await self.service.create_example(create_example_dto)

    @get("/example")
    async def find_all(self) -> Sequence[Example]:
        """Find all example."""
        return await self.service.find_all()

    @get("/example/{id}")
    async def find_one(self, id: int) -> Example | None:
        """Find one example by ID."""
        return await self.service.find_one(id)

    @patch("/example/{id}")
    async def update(
        self, id: int, update_example_dto: UpdateExampleDto
    ) -> Example | None:
        """Update an example."""
        return await self.service.update_example(id, update_example_dto)

    @delete("/example/{id}")
    async def remove(self, id: int) -> bool:
        """Remove an example."""
        return await self.service.remove(id)
