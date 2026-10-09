"""Setup wizard HTTP controller — the wizard UI + one route per daemon page.

Standalone app (see main.py), not mounted into platform-api's own router.
Plain FastAPI APIRouter, not classy_fastapi: the appliance runs this
natively from apt (python3-fastapi), and classy_fastapi has no Debian
package.
"""

from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse

from src.wizard.docker_service import DockerService, DockerStepNotAvailableError
from src.wizard.neo4j_service import Neo4jService, Neo4jStepNotAvailableError
from src.wizard.postgres_service import PostgresService, PostgresStepNotAvailableError
from src.wizard.preflight_service import PreflightService
from src.wizard.ssh_service import (
    InvalidSshKeyError,
    SshService,
    SshStepNotAvailableError,
)
from src.wizard.wizard_record import (
    ApplyRequest,
    ApplyResult,
    Deployment,
    PasswordRequest,
    SetupInfo,
    SshAccount,
    StepResult,
)
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

_STATIC_DIR: Final[Path] = Path(__file__).parent / "static"
# Reason: a re-flashed box usually comes back on the same DHCP address; a
# browser that cached the old wizard's JSX would mix versions and crash.
# no-cache still caches, but revalidates against the ETag on every load.
_NO_CACHE: Final[dict[str, str]] = {"Cache-Control": "no-cache"}


class WizardController:
    """GET / (+ its static assets), GET /api/config, and one POST per page:
    /api/preflight (everywhere), /api/ssh, /api/docker, /api/postgres,
    /api/neo4j (on-prem only). The wizard has its own
    port (8080), so it lives at the root — no path prefix."""

    def __init__(
        self,
        *,
        preflight: PreflightService,
        ssh: SshService,
        docker: DockerService,
        postgres: PostgresService,
        neo4j: Neo4jService,
        tracker: StepTracker,
        deployment: Deployment,
        account: SshAccount,
    ) -> None:
        self._preflight = preflight
        self._ssh = ssh
        self._docker = docker
        self._postgres = postgres
        self._neo4j = neo4j
        self._tracker = tracker
        self._deployment = deployment
        self._account = account
        self.router = APIRouter()
        self.router.add_api_route(
            "/",
            self.index,
            methods=["GET"],
            summary="Serve the wizard UI, or 404 once every page is done",
        )
        self.router.add_api_route(
            "/{filename}",
            self.static_asset,
            methods=["GET"],
            summary="Serve a static JSX/JS asset the UI references",
        )
        self.router.add_api_route(
            "/api/config",
            self.config,
            methods=["GET"],
            response_model=SetupInfo,
            summary="Cloud or on-prem, and whose login SSH is for",
        )
        self.router.add_api_route(
            "/api/preflight",
            self.preflight,
            methods=["POST"],
            response_model=StepResult,
            summary="Hardware check: GPU, NVMe, CPU, memory against wizard-cfg.yml",
        )
        self.router.add_api_route(
            "/api/ssh",
            self.ssh,
            methods=["POST"],
            response_model=ApplyResult,
            summary="On-prem SSH step: authorize your public key, verify SSH works",
        )
        self.router.add_api_route(
            "/api/docker",
            self.docker,
            methods=["POST"],
            response_model=StepResult,
            summary="On-prem Docker step: create the arcnode network, verify",
        )
        self.router.add_api_route(
            "/api/postgres",
            self.postgres,
            methods=["POST"],
            response_model=StepResult,
            summary="On-prem PostgreSQL step: set the password, add extensions, verify",
        )
        self.router.add_api_route(
            "/api/neo4j",
            self.neo4j,
            methods=["POST"],
            response_model=StepResult,
            summary="On-prem Neo4j step: fix memory, set the password, verify",
        )

    async def index(self) -> HTMLResponse:
        """Entry point the person's browser loads."""
        self._refuse_if_applied()
        return HTMLResponse((_STATIC_DIR / "index.html").read_text(), headers=_NO_CACHE)

    async def static_asset(self, filename: str) -> FileResponse:
        """tokens.jsx / setup-wizard.jsx — whatever index.html's script tags need.

        FastAPI path params can't contain "/", so this only ever matches
        single-segment filenames — safe against path traversal.
        """
        self._refuse_if_applied()
        path = _STATIC_DIR / filename
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return FileResponse(path, headers=_NO_CACHE)

    async def config(self) -> SetupInfo:
        """Deployment, login account, and which pages are already done —
        so a reload resumes at the first unfinished page."""
        self._refuse_if_applied()
        return SetupInfo(
            deployment=self._deployment,
            account=self._account.name,
            completed=self._tracker.completed(),
        )

    async def preflight(self) -> StepResult:
        """The hardware check page — see PreflightService.apply."""
        try:
            return self._preflight.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    async def ssh(self, request: ApplyRequest) -> ApplyResult:
        """The on-prem SSH page — see SshService.apply."""
        try:
            return self._ssh.apply(request)
        except (StepAlreadyDoneError, SshStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidSshKeyError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    async def docker(self) -> StepResult:
        """The on-prem Docker page — see DockerService.apply."""
        try:
            return self._docker.apply()
        except (StepAlreadyDoneError, DockerStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    async def postgres(self, request: PasswordRequest) -> StepResult:
        """The on-prem PostgreSQL page — see PostgresService.apply."""
        try:
            return self._postgres.apply(request)
        except (StepAlreadyDoneError, PostgresStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    async def neo4j(self, request: PasswordRequest) -> StepResult:
        """The on-prem Neo4j page — see Neo4jService.apply."""
        try:
            return self._neo4j.apply(request)
        except (StepAlreadyDoneError, Neo4jStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def _refuse_if_applied(self) -> None:
        if self._tracker.all_done():
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="setup already applied"
            )
