"""Setup wizard HTTP controller — the wizard UI + one route per daemon page.

Standalone app (see main.py), not mounted into platform-api's own router.
Plain FastAPI APIRouter, not classy_fastapi: the appliance runs this
natively from apt (python3-fastapi), and classy_fastapi has no Debian
package.
"""

from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from src.wizard.device_api_service import (
    DeviceApiService,
)
from src.wizard.grafana_service import GrafanaService
from src.wizard.hmi_service import HmiService
from src.wizard.ssh_lockdown_service import (
    SshKeyNotProvenError,
    SshLockdownService,
)
from src.wizard.industrial_gateway_service import (
    IndustrialGatewayService,
)
from src.wizard.docker_service import DockerService
from src.wizard.hivemq_service import HivemqService
from src.wizard.neo4j_service import Neo4jService
from src.wizard.ollama_service import OllamaService
from src.wizard.postgres_service import PostgresService
from src.wizard.analyst_server_service import (
    AnalystServerService,
)
from src.wizard.der_control_service import (
    DerControlService,
)
from src.wizard.analyst_model_service import (
    AnalystModelService,
)
from src.wizard.mlflow_service import MlflowService
from src.wizard.preflight_service import PreflightService
from src.wizard.prometheus_service import (
    PrometheusService,
)
from src.wizard.site_service import SiteService
from src.wizard.telemetry_writer_service import (
    TelemetryWriterService,
)
from src.wizard.ssh_service import (
    InvalidSshKeyError,
    SshService,
)
from src.wizard.analyst_server_progress import StageProgress
from src.wizard.wizard_record import (
    DerControlRequest,
    AnalystServerKeys,
    ApplyRequest,
    ApplyResult,
    BrokerPasswords,
    DeviceApiSecrets,
    PasswordRequest,
    SetupInfo,
    SiteInfo,
    SshAccount,
    SshLockdownRequest,
    StepResult,
)
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker

_STATIC_DIR: Final[Path] = Path(__file__).parent / "static"
# Reason: a re-flashed box usually comes back on the same DHCP address; a
# browser that cached the old wizard's JSX would mix versions and crash.
# no-cache still caches, but revalidates against the ETag on every load.
_NO_CACHE: Final[dict[str, str]] = {"Cache-Control": "no-cache"}


class WizardController:
    """GET / (+ its static assets), GET /api/config, and one POST per page
    (/api/preflight, /api/site, /api/ssh, ...). The wizard has its own port
    (8080), so it lives at the root — no path prefix."""

    def __init__(
        self,
        *,
        preflight: PreflightService,
        ssh: SshService,
        docker: DockerService,
        postgres: PostgresService,
        neo4j: Neo4jService,
        ollama: OllamaService,
        site: SiteService,
        hivemq: HivemqService,
        telemetry: TelemetryWriterService,
        prometheus: PrometheusService,
        mlflow: MlflowService,
        analyst_model: AnalystModelService,
        analyst_server: AnalystServerService,
        der_control: DerControlService,
        device_api: DeviceApiService,
        industrial_gateway: IndustrialGatewayService,
        hmi: HmiService,
        grafana: GrafanaService,
        ssh_lockdown: SshLockdownService,
        tracker: StepTracker,
        account: SshAccount,
    ) -> None:
        self._preflight = preflight
        self._ssh = ssh
        self._docker = docker
        self._postgres = postgres
        self._neo4j = neo4j
        self._ollama = ollama
        self._site = site
        self._hivemq = hivemq
        self._telemetry = telemetry
        self._prometheus = prometheus
        self._mlflow = mlflow
        self._analyst_model = analyst_model
        self._analyst_server = analyst_server
        self._der_control = der_control
        self._device_api = device_api
        self._industrial_gateway = industrial_gateway
        self._hmi = hmi
        self._grafana = grafana
        self._ssh_lockdown = ssh_lockdown
        self._tracker = tracker
        self._account = account
        self.router = APIRouter()
        # Reason: FastAPI takes each route's response model from the handler's
        # return annotation and its description from the docstring.
        routes = [
            ("GET", "/", self.index),
            ("GET", "/{filename}", self.static_asset),
            ("GET", "/api/config", self.config),
            ("POST", "/api/preflight", self.preflight),
            ("GET", "/api/site", self.site_info),
            ("POST", "/api/site", self.site),
            ("POST", "/api/ssh", self.ssh),
            ("POST", "/api/docker", self.docker),
            ("POST", "/api/postgres", self.postgres),
            ("POST", "/api/neo4j", self.neo4j),
            ("POST", "/api/ollama", self.ollama),
            ("POST", "/api/hivemq", self.hivemq),
            ("POST", "/api/telemetry", self.telemetry),
            ("POST", "/api/prometheus", self.prometheus),
            ("POST", "/api/mlflow", self.mlflow),
            ("POST", "/api/analyst-model", self.analyst_model),
            ("POST", "/api/analyst-server", self.analyst_server),
            ("GET", "/api/analyst-server/progress", self.analyst_server_progress),
            ("POST", "/api/der-control", self.der_control),
            ("POST", "/api/der-control/skip", self.der_control_skip),
            ("POST", "/api/device-api", self.device_api),
            ("POST", "/api/industrial-gateway", self.industrial_gateway),
            ("POST", "/api/hmi", self.hmi),
            ("POST", "/api/grafana", self.grafana),
            ("POST", "/api/ssh-lockdown", self.ssh_lockdown),
        ]
        for method, path, handler in routes:
            self.router.add_api_route(path, handler, methods=[method])

    def index(self) -> HTMLResponse:
        """Entry point the person's browser loads."""
        self._refuse_if_applied()
        return HTMLResponse((_STATIC_DIR / "index.html").read_text(), headers=_NO_CACHE)

    def static_asset(self, filename: str) -> FileResponse:
        """tokens.jsx / setup-wizard.jsx — whatever index.html's script tags need.

        FastAPI path params can't contain "/", so this only ever matches
        single-segment filenames — safe against path traversal.
        """
        self._refuse_if_applied()
        path = _STATIC_DIR / filename
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return FileResponse(path, headers=_NO_CACHE)

    def config(self) -> SetupInfo:
        """Login account and which pages are already done —
        so a reload resumes at the first unfinished page."""
        self._refuse_if_applied()
        return SetupInfo(
            account=self._account.name,
            completed=self._tracker.completed(),
        )

    def preflight(self) -> StepResult:
        """The hardware check page — see PreflightService.apply."""
        try:
            return self._preflight.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def ssh(self, request: ApplyRequest) -> ApplyResult:
        """The on-prem SSH page — see SshService.apply."""
        try:
            return self._ssh.apply(request)
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidSshKeyError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    def docker(self) -> StepResult:
        """The on-prem Docker page — see DockerService.apply."""
        try:
            return self._docker.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def postgres(self, request: PasswordRequest) -> StepResult:
        """The on-prem PostgreSQL page — see PostgresService.apply."""
        try:
            return self._postgres.apply(request)
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def neo4j(self, request: PasswordRequest) -> StepResult:
        """The on-prem Neo4j page — see Neo4jService.apply."""
        try:
            return self._neo4j.apply(request)
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def ollama(self) -> StreamingResponse:
        """The on-prem Ollama page — see OllamaService.apply. NDJSON: model
        downloads take minutes to hours, so progress streams as it happens."""
        try:
            events = self._ollama.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        # Reason: a sync iterator — Starlette runs it in a worker thread, so
        # the blocking curl reads don't stall the event loop.
        lines = (event.model_dump_json(exclude_none=True) + "\n" for event in events)
        return StreamingResponse(lines, media_type="application/x-ndjson")

    def site_info(self) -> SiteInfo:
        """The order this ISO was built for — see SiteService.info."""
        return self._site.info()

    def site(self) -> StepResult:
        """The on-prem Site page: the customer confirms the order — see SiteService.apply."""
        try:
            return self._site.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def hivemq(self, request: BrokerPasswords) -> StepResult:
        """The on-prem HiveMQ page — see HivemqService.apply."""
        try:
            return self._hivemq.apply(request)
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def telemetry(self) -> StepResult:
        """The on-prem Telemetry writer page — see TelemetryWriterService.apply."""
        try:
            return self._telemetry.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def prometheus(self) -> StepResult:
        """The on-prem Prometheus page — see PrometheusService.apply."""
        try:
            return self._prometheus.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def mlflow(self) -> StepResult:
        """The on-prem MLflow page — see MlflowService.apply."""
        try:
            return self._mlflow.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def analyst_model(self) -> StepResult:
        """The on-prem analyst model page — see AnalystModelService.apply."""
        try:
            return self._analyst_model.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def analyst_server(self, request: AnalystServerKeys) -> StreamingResponse:
        """The on-prem analyst server page: streams its stages as NDJSON while it seeds, then the verdict."""
        try:
            self._analyst_server.ensure_startable()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return StreamingResponse(
            self._analyst_server.start_stream(request),
            media_type="application/x-ndjson",
        )

    def der_control_skip(self) -> StepResult:
        """Skip the DER page for now: the utility isn't connected yet."""
        try:
            return self._der_control.skip()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def der_control(self, request: DerControlRequest) -> StepResult:
        """The on-prem DER control API page — see DerControlService.apply."""
        try:
            return self._der_control.apply(request)
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def analyst_server_progress(self) -> list[StageProgress]:
        """The analyst server's startup stages, for the page to poll while it starts."""
        return self._analyst_server.progress()

    def device_api(self, request: DeviceApiSecrets) -> StepResult:
        """The on-prem Device API page — see DeviceApiService.apply."""
        try:
            return self._device_api.apply(request)
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def industrial_gateway(self) -> StepResult:
        """The on-prem Industrial gateway page — see IndustrialGatewayService.apply."""
        try:
            return self._industrial_gateway.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def hmi(self) -> StepResult:
        """The on-prem HMI page — see HmiService.apply."""
        try:
            return self._hmi.apply()
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def grafana(self, request: PasswordRequest) -> StepResult:
        """The on-prem Grafana page — see GrafanaService.apply."""
        try:
            return self._grafana.apply(request)
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def ssh_lockdown(self, request: SshLockdownRequest) -> StepResult:
        """The last on-prem page — see SshLockdownService.apply."""
        try:
            return self._ssh_lockdown.apply(request)
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except SshKeyNotProvenError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    def _refuse_if_applied(self) -> None:
        if self._tracker.all_done():
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="setup already applied"
            )
