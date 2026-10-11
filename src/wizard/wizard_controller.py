"""Setup wizard HTTP controller — the wizard UI + one route per daemon page.

Standalone app (see main.py), not mounted into platform-api's own router.
Plain FastAPI APIRouter, not classy_fastapi: the appliance runs this
natively from apt (python3-fastapi), and classy_fastapi has no Debian
package.
"""

from pathlib import Path
from collections.abc import Callable
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from src.wizard.device_api_service import DeviceApiService, DeviceApiStepNotAvailableError
from src.wizard.grafana_service import GrafanaService, GrafanaStepNotAvailableError
from src.wizard.hmi_service import HmiService, HmiStepNotAvailableError
from src.wizard.industrial_gateway_service import (
    IndustrialGatewayService,
    IndustrialGatewayStepNotAvailableError,
)
from src.wizard.docker_service import DockerService, DockerStepNotAvailableError
from src.wizard.hivemq_service import HivemqService, HivemqStepNotAvailableError
from src.wizard.neo4j_service import Neo4jService, Neo4jStepNotAvailableError
from src.wizard.ollama_service import OllamaService, OllamaStepNotAvailableError
from src.wizard.postgres_service import PostgresService, PostgresStepNotAvailableError
from src.wizard.analyst_server_service import (
    AnalystServerService,
    AnalystServerStepNotAvailableError,
)
from src.wizard.cloud_secrets_service import CloudSecretsService, CloudSecretsStepNotAvailableError
from src.wizard.der_control_service import DerControlService, DerControlStepNotAvailableError
from src.wizard.analyst_model_service import (
    AnalystModelService,
    AnalystModelStepNotAvailableError,
)
from src.wizard.mlflow_service import MlflowService, MlflowStepNotAvailableError
from src.wizard.preflight_service import PreflightService
from src.wizard.prometheus_service import PrometheusService, PrometheusStepNotAvailableError
from src.wizard.site_service import SiteService, SiteStepNotAvailableError
from src.wizard.telemetry_writer_service import (
    TelemetryWriterService,
    TelemetryWriterStepNotAvailableError,
)
from src.wizard.ssh_service import (
    InvalidSshKeyError,
    SshService,
    SshStepNotAvailableError,
)
from src.wizard.analyst_server_progress import StageProgress
from src.wizard.setup_token import TOKEN_HEADER
from src.wizard.wizard_record import (
    CloudSecrets,
    DerControlRequest,
    AnalystServerKeys,
    ApplyRequest,
    ApplyResult,
    BrokerPasswords,
    Deployment,
    DeviceApiSecrets,
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



def _require_setup_token(expected: str) -> Callable[[str | None], None]:
    """A dependency that refuses any change whose X-Setup-Token header isn't the stack owner's."""

    def check(setup_token: Annotated[str | None, Header(alias=TOKEN_HEADER)] = None) -> None:
        if setup_token != expected:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="setup token missing or wrong")

    return check

class WizardController:
    """GET / (+ its static assets), GET /api/config, and one POST per page:
    /api/preflight (everywhere), /api/ssh, /api/docker, /api/postgres,
    /api/neo4j, /api/ollama, /api/site (on-prem only). The wizard has its own
    port (8080), so it lives at the root — no path prefix."""

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
        cloud_secrets: CloudSecretsService,
        device_api: DeviceApiService,
        industrial_gateway: IndustrialGatewayService,
        hmi: HmiService,
        grafana: GrafanaService,
        tracker: StepTracker,
        deployment: Deployment,
        account: SshAccount,
        setup_token: str | None = None,
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
        self._cloud_secrets = cloud_secrets
        self._device_api = device_api
        self._industrial_gateway = industrial_gateway
        self._hmi = hmi
        self._grafana = grafana
        self._tracker = tracker
        self._deployment = deployment
        self._account = account
        self.router = APIRouter()
        token_deps = [Depends(_require_setup_token(setup_token))] if setup_token else []
        # Reason: FastAPI takes each route's response model from the handler's
        # return annotation and its description from the docstring.
        routes = [
            ("GET", "/", self.index),
            ("GET", "/{filename}", self.static_asset),
            ("GET", "/api/config", self.config),
            ("POST", "/api/preflight", self.preflight),
            ("POST", "/api/ssh", self.ssh),
            ("POST", "/api/docker", self.docker),
            ("POST", "/api/postgres", self.postgres),
            ("POST", "/api/neo4j", self.neo4j),
            ("POST", "/api/ollama", self.ollama),
            ("POST", "/api/site", self.site),
            ("POST", "/api/hivemq", self.hivemq),
            ("POST", "/api/telemetry", self.telemetry),
            ("POST", "/api/prometheus", self.prometheus),
            ("POST", "/api/mlflow", self.mlflow),
            ("POST", "/api/analyst-model", self.analyst_model),
            ("POST", "/api/analyst-server", self.analyst_server),
            ("GET", "/api/analyst-server/progress", self.analyst_server_progress),
            ("POST", "/api/der-control", self.der_control),
            ("POST", "/api/cloud-secrets", self.cloud_secrets),
            ("POST", "/api/device-api", self.device_api),
            ("POST", "/api/industrial-gateway", self.industrial_gateway),
            ("POST", "/api/hmi", self.hmi),
            ("POST", "/api/grafana", self.grafana),
        ]
        for method, path, handler in routes:
            self.router.add_api_route(
                path, handler, methods=[method],
                dependencies=token_deps if method == "POST" else [],
            )

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
        """Deployment, login account, and which pages are already done —
        so a reload resumes at the first unfinished page."""
        self._refuse_if_applied()
        return SetupInfo(
            deployment=self._deployment,
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
        except (StepAlreadyDoneError, SshStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidSshKeyError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    def docker(self) -> StepResult:
        """The on-prem Docker page — see DockerService.apply."""
        try:
            return self._docker.apply()
        except (StepAlreadyDoneError, DockerStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def postgres(self, request: PasswordRequest) -> StepResult:
        """The on-prem PostgreSQL page — see PostgresService.apply."""
        try:
            return self._postgres.apply(request)
        except (StepAlreadyDoneError, PostgresStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def neo4j(self, request: PasswordRequest) -> StepResult:
        """The on-prem Neo4j page — see Neo4jService.apply."""
        try:
            return self._neo4j.apply(request)
        except (StepAlreadyDoneError, Neo4jStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def ollama(self) -> StreamingResponse:
        """The on-prem Ollama page — see OllamaService.apply. NDJSON: model
        downloads take minutes to hours, so progress streams as it happens."""
        try:
            events = self._ollama.apply()
        except (StepAlreadyDoneError, OllamaStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        # Reason: a sync iterator — Starlette runs it in a worker thread, so
        # the blocking curl reads don't stall the event loop.
        lines = (event.model_dump_json(exclude_none=True) + "\n" for event in events)
        return StreamingResponse(lines, media_type="application/x-ndjson")

    def site(self) -> StepResult:
        """The on-prem Site page — see SiteService.apply."""
        try:
            return self._site.apply()
        except (StepAlreadyDoneError, SiteStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def hivemq(self, request: BrokerPasswords) -> StepResult:
        """The on-prem HiveMQ page — see HivemqService.apply."""
        try:
            return self._hivemq.apply(request)
        except (StepAlreadyDoneError, HivemqStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def telemetry(self) -> StepResult:
        """The on-prem Telemetry writer page — see TelemetryWriterService.apply."""
        try:
            return self._telemetry.apply()
        except (StepAlreadyDoneError, TelemetryWriterStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def prometheus(self) -> StepResult:
        """The on-prem Prometheus page — see PrometheusService.apply."""
        try:
            return self._prometheus.apply()
        except (StepAlreadyDoneError, PrometheusStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def mlflow(self) -> StepResult:
        """The on-prem MLflow page — see MlflowService.apply."""
        try:
            return self._mlflow.apply()
        except (StepAlreadyDoneError, MlflowStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def analyst_model(self) -> StepResult:
        """The on-prem analyst model page — see AnalystModelService.apply."""
        try:
            return self._analyst_model.apply()
        except (StepAlreadyDoneError, AnalystModelStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def analyst_server(self, request: AnalystServerKeys) -> StepResult:
        """The on-prem analyst server page — see AnalystServerService.apply."""
        try:
            return self._analyst_server.apply(request)
        except (StepAlreadyDoneError, AnalystServerStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def cloud_secrets(self, request: CloudSecrets) -> StepResult:
        """The cloud password page — see CloudSecretsService.apply."""
        try:
            return self._cloud_secrets.apply(request)
        except (StepAlreadyDoneError, CloudSecretsStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def der_control(self, request: DerControlRequest) -> StepResult:
        """The on-prem DER control API page — see DerControlService.apply."""
        try:
            return self._der_control.apply(request)
        except (StepAlreadyDoneError, DerControlStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def analyst_server_progress(self) -> list[StageProgress]:
        """The analyst server's startup stages, for the page to poll while it starts."""
        return self._analyst_server.progress()

    def device_api(self, request: DeviceApiSecrets) -> StepResult:
        """The on-prem Device API page — see DeviceApiService.apply."""
        try:
            return self._device_api.apply(request)
        except (StepAlreadyDoneError, DeviceApiStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def industrial_gateway(self) -> StepResult:
        """The on-prem Industrial gateway page — see IndustrialGatewayService.apply."""
        try:
            return self._industrial_gateway.apply()
        except (StepAlreadyDoneError, IndustrialGatewayStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def hmi(self) -> StepResult:
        """The on-prem HMI page — see HmiService.apply."""
        try:
            return self._hmi.apply()
        except (StepAlreadyDoneError, HmiStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def grafana(self, request: PasswordRequest) -> StepResult:
        """The on-prem Grafana page — see GrafanaService.apply."""
        try:
            return self._grafana.apply(request)
        except (StepAlreadyDoneError, GrafanaStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def _refuse_if_applied(self) -> None:
        if self._tracker.all_done():
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="setup already applied"
            )
