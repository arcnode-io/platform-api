from fastapi import FastAPI
from src.app_controller import AppController
from src.call_api.call_api_module import CallApiModule
from src.config import load_config, LogLevel, PostgresHost
from src.example.example_module import ExampleModule
import os
from tortoise.contrib.fastapi import RegisterTortoise
from pydantic_settings import BaseSettings
from ipaddress import IPv4Address


class Settings(BaseSettings):  # type: ignore[explicit-any]  # upstream: pydantic-settings PRs #557/#559 reverted Any fix
    """Application settings with all config values and override capability."""

    log_level: LogLevel
    port: int
    host: IPv4Address
    e2e: bool
    reload: bool
    postgres_host: PostgresHost
    postgres_port: int


class AppModule:
    """Module for creating basic FastAPI applications."""

    def import_module(self, app: FastAPI) -> None:
        """Register basic routes (app_controller, call_api)."""
        app_controller = AppController()
        call_api = CallApiModule()
        app.include_router(app_controller.router)
        app.include_router(call_api.router)

    def create_app(self) -> FastAPI:
        """Create and configure the basic FastAPI application."""
        app = FastAPI()
        self.import_module(app)
        return app


class AppWithDatabaseModule:
    """Module for creating FastAPI applications with database configuration."""

    def __init__(self) -> None:
        """Initialize the database app module with settings."""
        config = load_config()
        self.settings = Settings(
            log_level=config.log_level,
            port=config.port,
            host=config.host,
            e2e=config.e2e,
            reload=config.reload,
            postgres_host=config.postgres_host,
            postgres_port=5432,
        )

    def import_module(self, app: FastAPI) -> None:
        """Register all routes including database-dependent ones."""
        app_controller = AppController()
        call_api = CallApiModule()
        example = ExampleModule()
        app.include_router(app_controller.router)
        app.include_router(call_api.router)
        app.include_router(example.router)

    def create_app(self) -> FastAPI:
        """Create and configure the FastAPI application with database."""
        app = FastAPI()

        # Configure Tortoise ORM
        db_url = f"postgres://postgres:{os.environ['POSTGRES_PASSWORD']}@{self.settings.postgres_host.value}:{self.settings.postgres_port}/postgres"

        RegisterTortoise(
            app,
            db_url=db_url,
            modules={"models": ["src.example.entities.example_entity"]},
            generate_schemas=True,
            add_exception_handlers=True,
        )

        self.import_module(app)
        return app
