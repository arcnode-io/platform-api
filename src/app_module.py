"""Top-level FastAPI assembly. Wires modules + DB + AWS clients.

Tortoise ORM init runs inside the FastAPI lifespan context so DB connections are
opened on startup and closed on shutdown. `register_database` (called once before
`create_app`) flips on the lifespan; smoke tests skip it for a no-DB app.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from src.app_controller import AppController
from src.aws.aws_module import AwsModule
from src.aws.ses_service import SesService
from src.cfn.cfn_module import CfnModule
from src.config import Config, EmailProvider, load_config
from src.edp_client.edp_client_module import EdpClientModule
from src.email.resend_service import ResendService
from src.iso.iso_module import IsoModule
from src.manifest.manifest_module import ManifestModule
from src.orchestrator.orchestrator_module import OrchestratorModule
from src.bundle.bundle_module import BundleModule
from src.orders.orders_module import OrdersModule
from src.portal.portal_module import PortalModule
from src.sites.sites_module import SitesModule
from src.sizing.sizing_module import SizingModule


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
        self.cfn_module = CfnModule()
        self.iso_module = IsoModule(
            aws=self.aws_module, base_iso_url=self.config.base_iso_url
        )
        self.portal_module = PortalModule()
        self.manifest_module = ManifestModule()
        # Both secrets come from the environment, like the DB password; off where there is no zone.
        site_token_secret = (
            os.environ["SITE_TOKEN_SECRET"] if self.config.site_dns else None
        )
        self.sites_module = (
            SitesModule(
                dns_api_user=self.config.dns_api_user,
                dns_client_ip=self.config.dns_client_ip,
                namecheap_api_key=os.environ["NAMECHEAP_API_KEY"],
                token_secret=os.environ["SITE_TOKEN_SECRET"],
            )
            if self.config.site_dns
            else None
        )
        self.bundle_module = BundleModule(s3=self.aws_module.s3)
        self.orchestrator_module = OrchestratorModule(
            edp=self.edp_client_module,
            aws=self.aws_module,
            email=self._email_sender(),
            cfn=self.cfn_module,
            iso=self.iso_module,
            portal=self.portal_module,
            manifest=self.manifest_module,
            ems_hmi_apk_url=self.config.ems_hmi_apk_url,
            ems_industrial_gateway_tarball_url=(
                self.config.ems_industrial_gateway_tarball_url
            ),
            site_token_secret=site_token_secret,
            platform_public_url=self.config.platform_public_url,
        )
        self.orders_module = OrdersModule(
            orchestrator=self.orchestrator_module,
            rate_limit_count=self.config.order_rate_limit_count,
            rate_limit_window_s=self.config.order_rate_limit_window_s,
        )
        self.sizing_module = SizingModule(edp_api_url=self.config.edp_api_url)
        self._db_lifespan_enabled = False

    def _email_sender(self) -> SesService | ResendService:
        """cfg.yml picks the provider; Resend's key comes from the environment, like the DB password."""
        match self.config.email_provider:
            case EmailProvider.RESEND:
                return ResendService(
                    api_key=os.environ["RESEND_API_KEY"],
                    sender_email=self.config.ses_sender_email,
                )
            case EmailProvider.SES:
                return self.aws_module.ses

    def import_module(self, app: FastAPI) -> None:
        """Register feature routers."""
        app_controller = AppController()
        app.include_router(app_controller.router)
        app.include_router(self.orders_module.router)
        app.include_router(self.sizing_module.router)
        app.include_router(self.bundle_module.router)
        if self.sites_module is not None:
            app.include_router(self.sites_module.router)

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
        # arcnode.io's static configurator hits /platform-api/orders cross-origin.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=self.config.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            # The site reads Retry-After on a 429 to tell the customer how long to wait.
            expose_headers=["Retry-After"],
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
