"""Top-level FastAPI assembly. Wires modules + DB + AWS clients.

DB registration is a separate `register_database` step so smoke tests can build
a fully-functional app without spinning Postgres. Production `main.py` always
calls both `create_app()` and `register_database()`.
"""

import os

from fastapi import FastAPI
from tortoise.contrib.fastapi import RegisterTortoise

from src.app_controller import AppController
from src.config import load_config


class AppModule:
    """Top-level DI for platform-api."""

    def __init__(self) -> None:
        self.config = load_config()

    def import_module(self, app: FastAPI) -> None:
        """Register feature routers. Feature modules wired here as they land."""
        app_controller = AppController()
        app.include_router(app_controller.router)

    def register_database(self, app: FastAPI) -> None:
        """Attach Tortoise ORM startup/shutdown hooks. Reads POSTGRES_PASSWORD."""
        password = os.environ["POSTGRES_PASSWORD"]
        db_url = (
            f"postgres://postgres:{password}"
            f"@{self.config.postgres_host.value}:5432/postgres"
        )
        RegisterTortoise(
            app,
            db_url=db_url,
            modules={"models": []},  # feature modules append here
            generate_schemas=True,
            add_exception_handlers=True,
        )

    def create_app(self) -> FastAPI:
        """Create the FastAPI app + register routers (no DB)."""
        app = FastAPI(
            title="platform-api",
            description="Order intake + delivery orchestration",
        )
        self.import_module(app)
        return app
