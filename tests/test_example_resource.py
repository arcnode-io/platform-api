import os

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from src.example.example_module import ExampleModule
from tests.fixtures.containers import start_postgres


class TestExampleResource:
    """Integration tests for Example resource HTTP endpoints with database."""

    @pytest.mark.asyncio
    async def test_can_create_and_retrieve_example_from_database_via_http(self) -> None:
        """Test that an Example can be created via service layer and retrieved via HTTP endpoint."""
        with start_postgres(password=os.environ["POSTGRES_PASSWORD"]) as pg:
            # Initialize Tortoise manually for testing
            await Tortoise.init(
                db_url=pg.url,
                modules={"models": ["src.example.entities.example_entity"]},
            )
            await Tortoise.generate_schemas()

            try:
                # Create simple app without RegisterTortoise to avoid double initialization
                app = FastAPI()
                example_module = ExampleModule()
                app.include_router(example_module.router)

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    # Act
                    create_response = await client.post(
                        "/example", json={"name": "Test Example Item"}
                    )
                    create_example = create_response.json()
                    response = await client.get(f"/example/{create_example['id']}")
                    result = response.json()
                    # Assert
                    assert result["name"] == "Test Example Item"
            finally:
                await Tortoise.close_connections()
