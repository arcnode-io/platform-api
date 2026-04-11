from typing import Optional
from collections.abc import Sequence
from .dto.create_example_dto import CreateExampleDto
from .dto.update_example_dto import UpdateExampleDto
from .entities.example_entity import Example


class ExampleService:
    """
    Service for handling Example resource business logic and data operations.
    Uses Tortoise ORM for database persistence.
    """

    async def create_example(self, create_example_dto: CreateExampleDto) -> Example:
        """
        Creates a new Example resource and persists it to the database.

        Args:
            create_example_dto: Data transfer object containing Example creation data

        Returns:
            The created Example entity
        """
        return await Example.create(**create_example_dto.model_dump())

    async def find_all(self) -> Sequence[Example]:
        """
        Retrieves all Example resources from the database.

        Returns:
            Sequence containing all Example entities
        """
        return await Example.all()

    async def find_one(self, id: int) -> Optional[Example]:
        """
        Retrieves a specific Example resource by its ID from the database.

        Args:
            id: Numeric identifier of the Example resource to retrieve

        Returns:
            The Example entity or None if not found
        """
        return await Example.filter(id=id).first()

    async def update_example(
        self, id: int, update_example_dto: UpdateExampleDto
    ) -> Optional[Example]:
        """
        Updates an existing Example resource with new data.

        Args:
            id: Numeric identifier of the Example resource to update
            update_example_dto: Data transfer object containing updated Example data

        Returns:
            The updated Example entity or None if not found
        """
        example = await Example.filter(id=id).first()
        if not example:
            return None

        update_data = update_example_dto.model_dump(exclude_unset=True)
        await example.update_from_dict(update_data)
        await example.save()
        return example

    async def remove(self, id: int) -> bool:
        """
        Removes an Example resource from the system.

        Args:
            id: Numeric identifier of the Example resource to remove

        Returns:
            Boolean indicating successful removal
        """
        deleted_count = await Example.filter(id=id).delete()
        return deleted_count > 0
