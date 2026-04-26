"""Top-level FastAPI assembly. Wires modules + DB + AWS clients.

Tortoise ORM init runs inside the FastAPI lifespan context so DB connections are
opened on startup and closed on shutdown. `register_database` (called once before
`create_app`) flips on the lifespan; smoke tests skip it for a no-DB app.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from tortoise.contrib.fastapi import RegisterTortoise

from src.app_controller import AppController
from src.aws.aws_module import AwsModule
from src.config import Config, load_config
from src.edp_client.edp_client_module import EdpClientModule
from src.orchestrator.orchestrator_module import OrchestratorModule
from src.orders.orders_module import OrdersModule


class AppModule:
    """Top-level DI for platform-api."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.edp_client_module = EdpClientModule(edp_api_url=self.config.edp_api_url)
        self.aws_module = AwsModule(
            s3_endpoint_url=self.config.s3_endpoint_url,
            s3_bucket=self.config.s3_bucket,
            ses_endpoint_url=self.config.ses_endpoint_url,
            ses_sender_email=self.config.ses_sender_email,
        )
        self.orchestrator_module = OrchestratorModule(
            edp=self.edp_client_module,
            aws=self.aws_module,
            ems_hmi_apk_url=self.config.ems_hmi_apk_url,
        )
        self.orders_module = OrdersModule(orchestrator=self.orchestrator_module)
        self._db_lifespan_enabled = False

    def import_module(self, app: FastAPI) -> None:
        """Register feature routers."""
        app_controller = AppController()
        app.include_router(app_controller.router)
        app.include_router(self.orders_module.router)

    def register_database(self) -> None:
        """Enable Tortoise ORM init in the FastAPI lifespan. Call before `create_app`.

        Reads POSTGRES_PASSWORD from env. Skip for smoke tests that don't need a DB.
        """
        self._db_lifespan_enabled = True

    def create_app(self) -> FastAPI:
        """Create the FastAPI app + register routers."""
        lifespan = self._build_lifespan() if self._db_lifespan_enabled else None
        app = FastAPI(
            title="platform-api",
            description="Order intake + delivery orchestration",
            lifespan=lifespan,
        )
        self.import_module(app)
        return app

    def _build_lifespan(self):  # noqa: ANN202 — async context manager type is awkward
        password = os.environ["POSTGRES_PASSWORD"]
        db_url = (
            f"postgres://postgres:{password}"
            f"@{self.config.postgres_host}:{self.config.postgres_port}/postgres"
        )

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with RegisterTortoise(
                app,
                db_url=db_url,
                modules={"models": ["src.orders.order_entity"]},
                generate_schemas=True,
            ):
                yield

        return lifespan
